import hmac
import hashlib
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import settings
from app.models.entities import Payment, PaymentEvent, Customer
from app.services.cases import open_case_for_payment, run_recovery_cycle

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    # In dev with placeholder secret, skip verification; enforce in prod.
    if settings.razorpay_webhook_secret != "placeholder":
        if not _verify_signature(body, x_razorpay_signature or ""):
            raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()
    event_type = payload.get("event", "unknown")
    entity = (payload.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}

    rzp_id = entity.get("id") or f"synthetic_{event_type}"
    amount_paise = entity.get("amount", 0) or 0
    amount_inr = amount_paise / 100.0 if amount_paise else 0.0

    payment = db.query(Payment).filter_by(razorpay_payment_id=rzp_id).first()
    if not payment:
        # Best-effort customer stub
        cust_ext = entity.get("email") or entity.get("contact") or "unknown"
        customer = db.query(Customer).filter_by(external_id=cust_ext).first()
        if not customer:
            customer = Customer(external_id=cust_ext, email=entity.get("email"), phone=entity.get("contact"))
            db.add(customer); db.commit(); db.refresh(customer)
        payment = Payment(
            razorpay_payment_id=rzp_id,
            customer_id=customer.id,
            amount=amount_inr,
            currency=entity.get("currency", "INR"),
            status=entity.get("status", "failed"),
            method=entity.get("method"),
            failure_reason=entity.get("error_description") or entity.get("error_reason"),
        )
        db.add(payment); db.commit(); db.refresh(payment)

    db.add(PaymentEvent(payment_id=payment.id, event_type=event_type, raw=payload))
    db.commit()

    result = {"received": event_type, "payment_id": payment.id}
    if event_type in ("payment.failed", "checkout.abandoned"):
        case = open_case_for_payment(db, payment)
        action = run_recovery_cycle(db, case)
        result.update({
            "case_id": case.id,
            "case_status": case.status,
            "action": action.action_type,
            "action_result": action.result,
        })
    return result
