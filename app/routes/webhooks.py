import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.models.entities import AuditLog, Customer, Payment, PaymentEvent
from app.services.cases import (close_open_case_on_direct_capture,
                                 mark_case_recovered_by_link,
                                 mark_case_stopped_by_link,
                                 open_case_for_payment, run_recovery_cycle)

log = logging.getLogger("recoverai.webhook")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _run_cycle_bg(case_id: int) -> None:
    """Run the recovery cycle in a fresh session — safe for background execution."""
    db = SessionLocal()
    try:
        from app.models.entities import RecoveryCase
        case = db.query(RecoveryCase).get(case_id)
        if not case:
            return
        action = run_recovery_cycle(db, case)
        log.info("case=%s diag=%s action=%s policy=%s result=%s",
                 case.id, action.diagnosis, action.action_type,
                 action.policy_decision, action.result)
    finally:
        db.close()


def _verify_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(settings.razorpay_webhook_secret.encode(),
                        body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _upsert_payment(db: Session, entity: dict) -> Payment:
    rzp_id = entity.get("id") or "unknown"
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
        amount=(entity.get("amount", 0) or 0) / 100.0,
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
    background: BackgroundTasks,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    if settings.razorpay_webhook_secret != "placeholder":
        if not _verify_signature(body, x_razorpay_signature or ""):
            raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()
    event_type = payload.get("event", "unknown")
    event_id = request.headers.get("x-razorpay-event-id")
    p = payload.get("payload", {}) or {}

    # Idempotency: Razorpay may retry the same delivery. Skip if we've handled it.
    if event_id and db.query(PaymentEvent).filter_by(razorpay_event_id=event_id).first():
        log.info("duplicate webhook ignored event_id=%s type=%s", event_id, event_type)
        return {"received": event_type, "duplicate": True}


    if event_type in ("payment.failed", "payment.captured"):
        entity = (p.get("payment", {}) or {}).get("entity", {}) or {}
        payment = _upsert_payment(db, entity)
        db.add(PaymentEvent(payment_id=payment.id, event_type=event_type, razorpay_event_id=event_id, raw=payload))
        if payment.customer:
            if event_type == "payment.captured":
                payment.customer.success_count += 1
            else:
                payment.customer.failure_count += 1
        db.commit()

        if event_type == "payment.captured":
            closed = close_open_case_on_direct_capture(db, payment)
            if closed:
                log.info("direct-capture closed case=%s amount=%.2f",
                         closed.id, closed.recovered_amount)

        result = {"received": event_type, "payment_id": payment.id}
        if event_type == "payment.failed":
            case = open_case_for_payment(db, payment)
            # Recovery cycle runs async so we return 200 to Razorpay in <50ms
            # regardless of LLM / payment-link creation latency.
            background.add_task(_run_cycle_bg, case.id)
            result.update({"case_id": case.id, "case_status": "queued"})
        return result

    if event_type in ("payment_link.expired", "payment_link.cancelled"):
        link_id = ((p.get("payment_link", {}) or {}).get("entity", {}) or {}).get("id")
        case = mark_case_stopped_by_link(db, link_id)
        db.add(AuditLog(event=event_type, case_id=case.id if case else None,
                        payload={"link_id": link_id, "matched_case": bool(case)}))
        db.commit()
        return {"received": event_type, "link_id": link_id,
                "matched_case_id": case.id if case else None}

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

    # Unhandled: 200 so Razorpay stops retrying, audit for visibility.
    db.add(AuditLog(event=f"unhandled:{event_type}", payload=payload))
    db.commit()
    return {"received": event_type, "handled": False}
