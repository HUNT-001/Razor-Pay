import hmac
import hashlib
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import settings
from app.models.entities import Payment, PaymentEvent, Customer, AuditLog
from app.services.cases import (
    open_case_for_payment, run_recovery_cycle, mark_case_recovered_by_link,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _upsert_payment(db: Session, entity: dict) -> Payment:
    rzp_id = entity.get("id") or "unknown"
    amount_inr = (entity.get("amount", 0) or 0) / 100.0
    payment = db.query(Payment).filter_by(razorpay_payment_id=rzp_id).first()
    if payment:
        return payment
    cust_ext = entity.get("email") or entity.get("contact") or "unknown"
    customer = db.query(Customer).filter_by(external_id=cust_ext).first()
    if not customer:
        customer = Customer(external_id=cust_ext, email=entity.get("email"),
                            phone=entity.get("contact"))
        db.add(customer); db.commit(); db.refresh(customer)
    payment = Payment(
        razorpay_payment_id=rzp_id,
        customer_id=customer.id,
        amount=amount_inr,
        currency=entity.get("currency", "INR"),
        status=entity.get("status", "failed"),
        method=entity.get("method"),
        failure_reason=entity.get("error_description"),
        error_code=entity.get("error_code"),
        error_source=entity.get("error_source"),
        error_step=entity.get("error_step"),
        error_reason_code=entity.get("error_reason"),
    )
    db.add(payment); db.commit(); db.refresh(payment)
    return payment


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    if settings.razorpay_webhook_secret != "placeholder":
        if not _verify_signature(body, x_razorpay_signature or ""):
            raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()
    event_type = payload.get("event", "unknown")
    p = payload.get("payload", {}) or {}

    # payment.failed / payment.captured — has payload.payment.entity
    if event_type in ("payment.failed", "payment.captured"):
        entity = (p.get("payment", {}) or {}).get("entity", {}) or {}
        payment = _upsert_payment(db, entity)
        db.add(PaymentEvent(payment_id=payment.id, event_type=event_type, raw=payload))
        # bump customer counters
        if payment.customer:
            if event_type == "payment.captured":
                payment.customer.success_count += 1
            else:
                payment.customer.failure_count += 1
        db.commit()

        result = {"received": event_type, "payment_id": payment.id}
        if event_type == "payment.failed":
            case = open_case_for_payment(db, payment)
            action = run_recovery_cycle(db, case)
            result.update({
                "case_id": case.id,
                "case_status": case.status,
                "action": action.action_type,
                "action_result": action.result,
                "external_ref": action.external_ref,
            })
        return result

    # payment_link.paid — customer paid a recovery link we generated
    if event_type == "payment_link.paid":
        link_entity = (p.get("payment_link", {}) or {}).get("entity", {}) or {}
        pay_entity = (p.get("payment", {}) or {}).get("entity", {}) or {}
        link_id = link_entity.get("id")
        paid_amount = (pay_entity.get("amount") or link_entity.get("amount") or 0) / 100.0
        case = mark_case_recovered_by_link(db, link_id, paid_amount)
        db.add(AuditLog(event=event_type, case_id=case.id if case else None,
                        payload={"link_id": link_id, "amount": paid_amount,
                                 "matched_case": bool(case)}))
        db.commit()
        return {"received": event_type, "link_id": link_id,
                "matched_case_id": case.id if case else None}

    # Unhandled event — log and 200 so Razorpay doesn't retry forever
    db.add(AuditLog(event=f"unhandled:{event_type}", payload=payload))
    db.commit()
    return {"received": event_type, "handled": False}
