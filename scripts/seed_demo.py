"""Seed the dashboard with 3 varied failed payments for a smooth demo.

Fires synthetic `payment.failed` webhooks straight at the local server, each
with different structured error fields so the agent produces 3 distinct
diagnoses (transient_gateway_failure, insufficient_funds, invalid_instrument).

Signs each request with RAZORPAY_WEBHOOK_SECRET from .env so signature
verification passes. Skips signing if the secret is still the placeholder.

Usage:
    python scripts/seed_demo.py
    python scripts/seed_demo.py --url http://127.0.0.1:8000/webhooks/razorpay
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

import httpx

WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "placeholder")

# Three failure profiles, chosen so the agent picks 3 different actions.
CASES = [
    {
        "label": "Gateway timeout · ₹2,499 · reliable customer",
        "entity": {
            "id": f"pay_demo_gw_{int(time.time())}",
            "amount": 249900,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "email": "alice@example.com",
            "contact": "+919000000001",
            "error_code": "GATEWAY_ERROR",
            "error_source": "gateway",
            "error_step": "payment_authorization",
            "error_reason": "gateway_timeout",
            "error_description": "The bank was unable to process the transaction due to a temporary gateway issue.",
        },
    },
    {
        "label": "Insufficient funds · ₹8,750 · new customer",
        "entity": {
            "id": f"pay_demo_insuf_{int(time.time())}",
            "amount": 875000,
            "currency": "INR",
            "status": "failed",
            "method": "upi",
            "email": "bob@example.com",
            "contact": "+919000000002",
            "error_code": "BAD_REQUEST_ERROR",
            "error_source": "customer",
            "error_step": "payment_authorization",
            "error_reason": "insufficient_funds",
            "error_description": "Payment failed due to insufficient balance in the account.",
        },
    },
    {
        "label": "Invalid card · ₹1,299 · chronic failer",
        "entity": {
            "id": f"pay_demo_bad_{int(time.time())}",
            "amount": 129900,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "email": "carol@example.com",
            "contact": "+919000000003",
            "error_code": "BAD_REQUEST_ERROR",
            "error_source": "customer",
            "error_step": "payment_authentication",
            "error_reason": "invalid_card_number",
            "error_description": "The card number entered is invalid. Please check the card details and try again.",
        },
    },
]


def send(url: str, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET and WEBHOOK_SECRET != "placeholder":
        sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Razorpay-Signature"] = sig
    r = httpx.post(url, content=body, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/webhooks/razorpay")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between sends")
    args = ap.parse_args()

    if WEBHOOK_SECRET == "placeholder":
        print("⚠  RAZORPAY_WEBHOOK_SECRET is the placeholder — sending unsigned.")
        print("   Set it in .env if the server enforces signatures.\n")

    print(f"Seeding {len(CASES)} demo cases into {args.url}\n")
    for i, case in enumerate(CASES, 1):
        payload = {"event": "payment.failed",
                   "payload": {"payment": {"entity": case["entity"]}}}
        try:
            resp = send(args.url, payload)
            print(f"  [{i}] {case['label']}")
            print(f"      → case #{resp.get('case_id')}  status={resp.get('case_status')}")
            # The recovery cycle now runs async; check the dashboard for the outcome.
        except httpx.HTTPStatusError as e:
            print(f"  [{i}] {case['label']} — FAILED {e.response.status_code}")
            print(f"      {e.response.text[:200]}")
        except Exception as e:
            print(f"  [{i}] {case['label']} — {type(e).__name__}: {e}")
        time.sleep(args.delay)

    print("\nOpen the dashboard: http://127.0.0.1:8000/dashboard")


if __name__ == "__main__":
    main()
