"""Thin lazy wrapper around the razorpay SDK so tests/stubs don't need creds."""
from functools import lru_cache
import razorpay
from app.config import settings


@lru_cache(maxsize=1)
def client() -> razorpay.Client:
    c = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    c.set_app_details({"title": "RecoverAI", "version": "0.1"})
    return c


def create_payment_link(amount_inr: float, description: str,
                        customer_email: str | None = None,
                        customer_contact: str | None = None,
                        reference_id: str | None = None) -> dict:
    """Create a Test Mode Payment Link. Returns the raw Razorpay response."""
    payload = {
        "amount": int(round(amount_inr * 100)),  # paise
        "currency": "INR",
        "accept_partial": False,
        "description": description[:2048],
        "reminder_enable": True,
        "notify": {"sms": bool(customer_contact), "email": bool(customer_email)},
    }
    if reference_id:
        payload["reference_id"] = reference_id[:40]
    if customer_email or customer_contact:
        payload["customer"] = {
            k: v for k, v in {
                "email": customer_email,
                "contact": customer_contact,
            }.items() if v
        }
    return client().payment_link.create(data=payload)
