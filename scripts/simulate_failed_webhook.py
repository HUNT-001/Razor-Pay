"""Send a fake payment.failed webhook to the local server for smoke testing."""
import httpx, json

payload = {
    "event": "payment.failed",
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_test_001",
                "amount": 499900,  # paise
                "currency": "INR",
                "status": "failed",
                "method": "card",
                "email": "demo@example.com",
                "contact": "+919999999999",
                "error_description": "Bank gateway timeout",
                "error_reason": "gateway_timeout",
            }
        }
    },
}

r = httpx.post("http://127.0.0.1:8000/webhooks/razorpay", json=payload, timeout=10)
print(r.status_code, json.dumps(r.json(), indent=2))
