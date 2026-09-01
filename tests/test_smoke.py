from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


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
        }}},
    }
    r = client.post("/webhooks/razorpay", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["received"] == "payment.failed"
    assert "case_id" in body
