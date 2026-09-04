import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _disable_signature_check(monkeypatch):
    # test posts are unsigned; bypass HMAC by matching the dev sentinel
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "placeholder")


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_failed_webhook_creates_case():
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_test_xyz",
            "amount": 250000,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "email": "t@example.com",
            "error_description": "Bank gateway timeout",
            "error_reason": "gateway_timeout",
            "error_source": "gateway",
            "error_code": "GATEWAY_ERROR",
        }}},
    }
    r = client.post("/webhooks/razorpay", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["received"] == "payment.failed"
    assert "case_id" in body
