"""Claude adapter. Structured JSON via forced tool-use → AgentDecision."""
import json
import logging

from anthropic import Anthropic

from app.agent.schema import AgentContext, AgentDecision
from app.config import settings

log = logging.getLogger(__name__)

_client: Anthropic | None = None

SYSTEM = (
    "You are RecoverAI, an autonomous payment-recovery agent for a Razorpay merchant. "
    "For every failed payment you receive structured error fields and customer history. "
    "You must diagnose the failure and choose ONE bounded recovery action from the "
    "allowed set. A deterministic policy engine will re-validate your choice, so pick "
    "the action that maximises probability of recovery given the diagnosis. Keep the "
    "reason concise (two short sentences). Do not invent actions outside the enum."
)

TOOL = {
    "name": "return_decision",
    "description": "Return the recovery decision for this failed payment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "diagnosis": {
                "type": "string",
                "enum": ["transient_gateway_failure", "insufficient_funds",
                         "invalid_instrument", "authentication_failed",
                         "bank_declined", "risk_declined",
                         "customer_action_required", "unknown_failure"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "recommended_action": {
                "type": "string",
                "enum": ["retry", "delayed_retry", "payment_link", "notify", "escalate"],
            },
            "reason": {"type": "string"},
            "customer_message": {"type": "string"},
        },
        "required": ["diagnosis", "confidence", "recommended_action", "reason"],
    },
}


def _client_():
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _user_prompt(ctx: AgentContext) -> str:
    return json.dumps({
        "amount_inr": ctx.amount,
        "failure_reason": ctx.failure_reason,
        "error_code": ctx.error_code,
        "error_source": ctx.error_source,
        "error_step": ctx.error_step,
        "error_reason_code": ctx.error_reason_code,
        "attempt_number": ctx.attempt_number,
        "customer_success_rate": round(ctx.customer_success_rate, 3),
        "customer_previous_failures": ctx.customer_previous_failures,
        "customer_previous_successes": ctx.customer_previous_successes,
        "payment_method": ctx.payment_method,
    }, separators=(",", ":"))


def decide(ctx: AgentContext) -> AgentDecision:
    resp = _client_().messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "return_decision"},
        messages=[{"role": "user", "content": _user_prompt(ctx)}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "return_decision":
            return AgentDecision(**block.input)
    raise RuntimeError("Claude returned no tool_use block")
