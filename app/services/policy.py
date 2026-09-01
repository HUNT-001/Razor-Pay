"""Deterministic policy engine. The LLM proposes; policy disposes."""
from dataclasses import dataclass
from app.agent.schema import AgentDecision
from app.models.entities import RecoveryCase

MAX_ATTEMPTS = 3
MAX_AMOUNT = 50_000.0  # INR
COOLDOWN_MIN = 15


@dataclass
class PolicyResult:
    approved: bool
    reason: str
    checks: dict


def evaluate(decision: AgentDecision, case: RecoveryCase, amount: float) -> PolicyResult:
    checks = {
        "attempts_under_limit": case.attempts < MAX_ATTEMPTS,
        "amount_under_threshold": amount <= MAX_AMOUNT,
        "action_in_allowlist": decision.recommended_action in {
            "retry", "delayed_retry", "payment_link", "notify", "escalate"
        },
        "not_already_recovered": case.status != "recovered",
    }
    approved = all(checks.values())
    reason = "all checks passed" if approved else (
        "; ".join(k for k, v in checks.items() if not v)
    )
    return PolicyResult(approved=approved, reason=reason, checks=checks)
