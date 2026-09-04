"""Deterministic guardrails. The LLM proposes; policy disposes."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.agent.schema import AgentDecision
from app.models.entities import RecoveryCase

MAX_ATTEMPTS = 3
MAX_AMOUNT = 50_000.0  # INR
COOLDOWN_SECONDS = 60  # min gap between actions on the same case
ALLOWED_ACTIONS = {"retry", "delayed_retry", "payment_link", "notify", "escalate"}


@dataclass
class PolicyResult:
    approved: bool
    reason: str
    checks: dict


def evaluate(decision: AgentDecision, case: RecoveryCase, amount: float) -> PolicyResult:
    cooldown_ok = True
    if case.last_action_at is not None:
        cooldown_ok = (datetime.utcnow() - case.last_action_at) >= timedelta(seconds=COOLDOWN_SECONDS)
    checks = {
        "attempts_under_limit":   case.attempts < MAX_ATTEMPTS,
        "amount_under_threshold": amount <= MAX_AMOUNT,
        "action_in_allowlist":    decision.recommended_action in ALLOWED_ACTIONS,
        "not_already_recovered":  case.status != "recovered",
        "cooldown_satisfied":     cooldown_ok,
    }
    approved = all(checks.values())
    reason = "all checks passed" if approved else \
             "; ".join(k for k, v in checks.items() if not v)
    return PolicyResult(approved=approved, reason=reason, checks=checks)
