<p align="left">
  <img src="assets/RazorPay.png" alt="Razorpay" height="36" />
</p>

# RecoverAI

**Autonomous Revenue Recovery Agent for Razorpay** — detects failed payments, diagnoses *why* revenue is at risk, chooses a bounded recovery action, executes it against Razorpay Test Mode, and proves how much revenue it actually recovered.

> Built for the Razorpay AI Buildathon · Track 3 (Autonomous Agents).

---

## Why this exists

Merchants don't just lose revenue when a payment fails. They lose it when the recovery *policy* doesn't adapt to *why* the payment failed. Retrying an expired card fails identically the second time. Retrying a gateway timeout usually works. Retrying an insufficient-funds error only works after the customer tops up. A single fixed retry loop is wrong for every one of these.

RecoverAI closes the loop: **detect → diagnose → decide (bounded) → execute → observe → measure → escalate/audit.**

## What it does

For every failed payment Razorpay sends:

1. **Ingests** the `payment.failed` webhook and captures the structured error fields (`error_code`, `error_source`, `error_step`, `error_reason`), not just the pretty description.
2. **Opens a recovery case** with the payment's revenue-at-risk.
3. **Diagnoses** the failure into one of 8 concrete classes: `transient_gateway_failure`, `insufficient_funds`, `invalid_instrument`, `authentication_failed`, `bank_declined`, `risk_declined`, `customer_action_required`, `unknown_failure`.
4. **Chooses an action** from a fixed allowlist: `retry`, `delayed_retry`, `payment_link`, `notify`, `escalate` — driven by the diagnosis, customer history (success rate, previous failures), and attempt number.
5. **Passes the action through a deterministic policy engine** (max 3 attempts, ₹50k ceiling, action allowlist, no-duplicate guard). The LLM proposes; policy disposes.
6. **Executes** — for `payment_link` this creates a real Razorpay Test Mode Payment Link; the customer's phone/email are notified.
7. **Waits for `payment_link.paid`** — when the customer pays, the case flips to `recovered`, `recovered_amount` is set, and the audit log records it.
8. **Escalates** when attempts are exhausted or the diagnosis is `risk_declined` — no infinite retry loops.
9. **Audits every step** — one JSON row per event, viewable per-case in the dashboard.

## Screenshots

### Operations dashboard
The whole product on one page — KPI row with a hero recovered-revenue tile, live agent status, cases table with per-case confidence bars, AI decision breakdown, recovery funnel, and a live activity feed at the bottom.

![Dashboard](assets/Dashboard.png)

### Case drawer — AI reasoning, exposed
Click any case → the drawer shows the diagnosis + confidence, the reason the agent picked *this* action, the real Razorpay Payment Link it generated, and the full recovery timeline.

![Case drawer](assets/CaseDrawer.png)

### Recent agent activity
Every audit-log row, sorted newest-first — detection, link creation, recovery — all clickable back into the case drawer.

![Activity feed](assets/ActivityFeed.png)

## Live demo — end-to-end with Razorpay Test Mode

**1. A real Razorpay Test Mode payment fails**

![Payment failed](assets/PaymentFailed.png)

**2. The agent diagnoses the failure and generates a real Payment Link**

![Recovery payment link](assets/PaymentLink.png)

**3. The customer pays the recovery link — case closes as `recovered`**

![Payment success](assets/PaymentSuccess.png)

## Architecture

```
┌───────────────────────┐
│  Razorpay Test Mode   │
│  (payment.failed,     │
│   payment_link.paid)  │
└──────────┬────────────┘
           │  webhook (HMAC-SHA256 verified)
           ▼
┌───────────────────────┐
│  FastAPI              │
│  /webhooks/razorpay   │
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Event processor      │
│  + feature builder    │
│  (customer history,   │
│   error fields, amt)  │
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Agent (stub_llm)     │──► AgentDecision {diagnosis, confidence,
│  → Structured JSON    │    recommended_action, reason, message}
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Policy engine        │──► PolicyResult {approved, checks, reason}
│  (max attempts, amt,  │
│   allowlist, stopped) │
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Executor             │──► Razorpay Payment Link (real, Test Mode)
│  retry / link / notify│
│  / escalate           │
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Case store + audit   │  (SQLite via SQLAlchemy)
│  RecoveryCase,        │
│  RecoveryAction,      │
│  AuditLog             │
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│  Dashboard (/dashboard)│
│  + /analytics/summary  │
│  + /recovery/cases     │
└───────────────────────┘

── Parallel evaluation path ────────────────────────────
Synthetic batch (10k) ─► Baseline (always retry) ─┐
                     └─► RecoverAI (same stub_llm) ─┴─► Metrics
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the component-by-component breakdown.

## Track 3 checklist

| Requirement                              | Where it lives                                          |
| ---------------------------------------- | ------------------------------------------------------- |
| Detect revenue at risk                   | `app/routes/webhooks.py` → `open_case_for_payment`      |
| Diagnose the failure                     | `app/agent/stub_llm.py` (structured-error → diagnosis)  |
| Choose a bounded intervention            | `AgentDecision.recommended_action` (5-value enum)       |
| Guardrails / stop rules                  | `app/services/policy.py` (attempts, amt, allowlist)     |
| Execute the action                       | `app/services/executor.py` → Razorpay Payment Link      |
| Observe outcome, close the loop          | `payment_link.paid` webhook → `mark_case_recovered_by_link` |
| Measure recovered revenue                | `/analytics/summary` and the dashboard hero tile        |
| Escalate/stop when attempts exhausted    | `run_recovery_cycle` → `case.status = "escalated"`      |
| Full audit trail                         | `AuditLog` rows, viewable per-case                      |
| Webhook signature verification           | `_verify_signature` (HMAC-SHA256, enforced in prod)     |

## Results

Benchmarked on 10,000 synthetic failed-payment cases (see `scripts/simulator.py` and [`docs/BENCHMARK.md`](docs/BENCHMARK.md)):

![Simulator output](assets/METRICS.png)

| Metric               | Baseline (always retry) | RecoverAI     |
| -------------------- | ----------------------: | ------------: |
| Cases                |                  10,000 |        10,000 |
| Revenue at risk      |             ₹81,85,252 | ₹81,85,252   |
| Cases recovered      |                   3,317 |         7,749 |
| Revenue recovered    |             ₹27,54,230 | ₹63,32,124   |
| Recovery rate        |                   33.7% |         77.4% |
| Avg actions / case   |                    1.67 |          1.57 |
| Unnecessary actions  |                   7,637 |         4,018 |
| Escalated            |                   6,683 |         2,115 |
| **RecoverAI lift**   |                         | **+43.7 pp**  |

*These numbers are from the synthetic simulator — see [`docs/BENCHMARK.md`](docs/BENCHMARK.md) for how the ground-truth model works and why the delta is what it is.*

The live Razorpay Test Mode path has been exercised end-to-end: a real `payment.failed` webhook opened a case (`bank_declined`, 70% confidence), the agent generated a real Payment Link (`plink_TX83ZRimGLk58f` → `https://rzp.io/rzp/dW8tIvG`), the customer paid it in Test Mode, the `payment_link.paid` webhook fired, and the case flipped to `recovered` with `recovered_amount: 10.0`.

## Setup

Requires Python 3.10–3.13. On 3.13 you also need `pip install "setuptools<81"` because the Razorpay SDK still imports `pkg_resources`.

```bash
git clone <this repo>
cd Razor-Pay
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS:    source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: paste your Razorpay Test Mode key_id, key_secret, and webhook secret
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/dashboard**.

### Wire Razorpay Test Mode

1. Dashboard → toggle **Test Mode** on → Settings → API Keys → **Generate Test Key**. Paste into `.env`.
2. Expose the local server: `ngrok http 8000` (or Cloudflare Tunnel).
3. Dashboard → Settings → **Webhooks → Add**:
   - URL: `https://<your-tunnel>/webhooks/razorpay`
   - Secret: any strong string; paste the same string into `.env` as `RAZORPAY_WEBHOOK_SECRET`.
   - Active events: `payment.failed`, `payment.captured`, `payment_link.paid`.
4. Restart uvicorn so it picks up the new secret.
5. Create a test Payment Link from the dashboard, pay it with the fail card `4000 0000 0000 0002`. Watch the case appear on the RecoverAI dashboard.

### Run the benchmark

```bash
python scripts/simulator.py --n 10000 --out benchmark_results.json
```

## Repo layout

```
app/
  main.py              FastAPI entrypoint
  config.py            env-driven settings (pydantic-settings)
  db.py                SQLAlchemy engine + session
  models/entities.py   Customer, Payment, PaymentEvent, RecoveryCase,
                       RecoveryAction, AuditLog
  agent/
    schema.py          AgentContext / AgentDecision (pydantic, 5-value action enum)
    stub_llm.py        deterministic diagnosis + action selection
    router.py          stub → real LLM switch (env: LLM_MODE)
  services/
    policy.py          attempts, amount ceiling, action allowlist, stopped-guard
    executor.py        real Razorpay Payment Link creation + simulated retry/notify
    razorpay_client.py thin lazy wrapper around the razorpay SDK
    cases.py           open case, run_recovery_cycle, mark_case_recovered_by_link
  routes/
    webhooks.py        /webhooks/razorpay (HMAC-verified)
    analytics.py       /analytics/summary
    cases.py           /recovery/cases[/{id}]
    dashboard.py       /dashboard (single-file HTML)
  static/
    dashboard.html     the operations console
scripts/
  simulator.py                     10k-case benchmark, baseline vs RecoverAI
  simulate_failed_webhook.py       smoke test: fake webhook against local server
tests/
  test_smoke.py
docs/
  ARCHITECTURE.md
  BENCHMARK.md
  VIDEO_SCRIPT.md
```

## Failure handling & bounded autonomy

- **Attempt cap** — 3 per case, enforced in `policy.py`. Beyond that, the case is marked `escalated` and no further automated action is taken.
- **Amount ceiling** — actions above ₹50,000 are blocked (policy default; move to env if needed).
- **Action allowlist** — the LLM cannot invent a new action; `AgentDecision.recommended_action` is a 5-value Literal, and the policy engine re-validates against a hard-coded set.
- **Risk-declined cases go straight to escalate** — no retrying suspected fraud.
- **Webhook signature** — HMAC-SHA256 verified when `RAZORPAY_WEBHOOK_SECRET` is real; requests with a bad signature return 400.
- **`.env` is gitignored** — no credentials in the repo.
- **Payment Link is idempotent from the customer's perspective** — creating a fresh link never charges twice, so a duplicate webhook delivery cannot cause a double-charge.

## Not built (on purpose)

Left out because the 70-hour clock is real and the story is stronger without them:
- Voice/WhatsApp channels
- A separate ML retry model (rule engine + LLM is already the intervention selector)
- A "chatbot" UI — this is an ops console, not a conversation
- Subscription-specific recovery (Razorpay has native retry behavior there; would be additive, not core)

## License

MIT.
