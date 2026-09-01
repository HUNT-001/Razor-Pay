# RecoverAI — Autonomous Revenue Recovery Agent

Track 3 buildathon project. Detects failed payments, diagnoses the failure,
runs a bounded recovery action through a policy engine, and proves how much
revenue it recovered.

## Phase 0 status (this scaffold)

- FastAPI app with `/webhooks/razorpay`, `/analytics/summary`, `/recovery/cases`
- SQLite via SQLAlchemy — models for customers, payments, events, cases,
  actions, audit logs
- Stub LLM agent (deterministic) that returns a structured `AgentDecision`
- Policy engine with attempt limit, amount threshold, action allowlist
- Simulated executor (returns success/failure probabilistically)
- Webhook signature verification (enforced when `RAZORPAY_WEBHOOK_SECRET`
  is set to something other than the placeholder)
- Smoke-test script that posts a synthetic `payment.failed` event

## Setup

```powershell
cd D:\Razor-Pay
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

In another terminal:

```powershell
python scripts\simulate_failed_webhook.py
```

Then hit http://127.0.0.1:8000/analytics/summary and
http://127.0.0.1:8000/recovery/cases in a browser.

## Getting Razorpay Test Mode keys (do this before Phase 1)

1. Sign in at https://dashboard.razorpay.com/ and switch the toggle at the
   top to **Test Mode** (nothing here charges real money).
2. Settings → API Keys → **Generate Test Key**. Copy `key_id` (starts
   `rzp_test_`) and `key_secret` into `.env`.
3. Settings → Webhooks → **Add New Webhook**.
   - URL: your public tunnel URL + `/webhooks/razorpay`
     (use `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`)
   - Active events: `payment.failed`, `payment.captured`, `payment_link.paid`
   - Set a **Secret** and paste it into `.env` as `RAZORPAY_WEBHOOK_SECRET`.
4. Send a test webhook from the dashboard — you should see a `case` row
   created and an action executed.

## Architecture (target)

```
Razorpay Test  →  /webhooks/razorpay  →  Event Processor
                                             ↓
                          Feature Builder (customer history, amount, …)
                                             ↓
                                  Agent (stub → LLM)
                                             ↓
                                    Policy Engine
                                             ↓
                    ┌─────────┬────────┬────────────┐
                  retry  delayed_retry  payment_link  notify
                                             ↓
                                     Result Observer
                                             ↓
                                       Audit Log
                                             ↓
                                       Dashboard
```

## Roadmap

- **Phase 1** — real Razorpay Payment Link creation in `executor.py`
- **Phase 2** — richer rule-based diagnosis + customer features
- **Phase 3** — swap `LLM_MODE=stub` for Anthropic/OpenAI with JSON schema
- **Phase 4** — `scripts/simulator.py` generates 1k–10k synthetic cases
- **Phase 5** — baseline (always-retry) vs RecoverAI benchmark
- **Phase 6** — React dashboard (Recharts)
- **Phase 7** — end-to-end live demo with Razorpay Test Mode
- **Phase 8** — signature enforcement, idempotency, stop-rule polish

## Layout

```
app/
  main.py              FastAPI entrypoint
  config.py            env-driven settings
  db.py                SQLAlchemy setup
  models/entities.py   ORM models
  agent/
    schema.py          AgentContext / AgentDecision (pydantic)
    stub_llm.py        deterministic stand-in
    router.py          selects stub vs real LLM
  services/
    policy.py          deterministic guardrails
    executor.py        action execution (stub → Razorpay)
    cases.py           open cases, run recovery cycle
  routes/
    webhooks.py        /webhooks/razorpay
    analytics.py       /analytics/summary
    cases.py           /recovery/cases[/{id}]
scripts/
  simulate_failed_webhook.py
```
