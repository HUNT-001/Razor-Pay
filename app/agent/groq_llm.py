"""Groq adapter (Llama 3.3 70B). Forced tool-use → AgentDecision."""
import json
import logging

from groq import Groq

from app.agent.schema import AgentContext, AgentDecision
from app.config import settings

log = logging.getLogger(__name__)

_client: Groq | None = None

SYSTEM = (
    "You are RecoverAI, an autonomous payment-recovery agent for a Razorpay merchant. "
    "For every failed payment you receive structured error fields and customer history. "
    "You must diagnose the failure and choose ONE bounded recovery action from the "
    "allowed set. A deterministic policy engine re-validates your choice, so pick the "
    "action that maximises probability of recovery given the diagnosis. Keep the reason "
    "concise (two short sentences)."
)

TOOL = {
    "type": "function",
    "function": {
        "name": "return_decision",
        "description": "Return the recovery decision for this failed payment.",
        "parameters": {
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
    },
}


def _client_() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def _payload(ctx: AgentContext) -> str:
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
    resp = _client_().chat.completions.create(
        model=settings.groq_model,
        temperature=0.2,
        max_tokens=512,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _payload(ctx)},
        ],
        tools=[TOOL],
        tool_choice={"type": "function", "function": {"name": "return_decision"}},
    )
    calls = resp.choices[0].message.tool_calls or []
    for call in calls:
        if call.function.name == "return_decision":
            return AgentDecision(**json.loads(call.function.arguments))
    raise RuntimeError("Groq returned no tool_call")
