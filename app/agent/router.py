"""Agent router with LLM output sandbox.

The policy engine validates the action against a static allowlist.
The sandbox here validates the *combination* (diagnosis, action) — an LLM
could return a syntactically valid but semantically incoherent pair
(e.g. risk_declined → retry). We coerce or fall back to the stub.
"""
import logging

from app.agent import stub_llm
from app.agent.schema import AgentContext, AgentDecision
from app.config import settings

log = logging.getLogger(__name__)

# For each diagnosis: which actions are semantically coherent.
COHERENT = {
    "transient_gateway_failure": {"retry", "delayed_retry", "payment_link"},
    "insufficient_funds":        {"delayed_retry", "payment_link", "notify"},
    "invalid_instrument":        {"payment_link", "notify"},
    "authentication_failed":     {"payment_link", "retry", "delayed_retry"},
    "bank_declined":             {"payment_link", "delayed_retry", "escalate"},
    "risk_declined":             {"escalate"},   # never retry suspected fraud
    "customer_action_required":  {"payment_link", "notify"},
    "unknown_failure":           {"payment_link", "notify", "escalate"},
}


def _sandbox(dec: AgentDecision, ctx: AgentContext) -> AgentDecision:
    allowed = COHERENT.get(dec.diagnosis)
    if allowed is None or dec.recommended_action in allowed:
        return dec
    fallback = stub_llm.decide(ctx)
    log.warning("LLM produced incoherent (%s, %s); overriding with stub → %s",
                dec.diagnosis, dec.recommended_action, fallback.recommended_action)
    return dec.model_copy(update={
        "recommended_action": fallback.recommended_action,
        "reason": f"[sandbox override] {dec.reason} · Coerced to {fallback.recommended_action}.",
    })


def get_decision(ctx: AgentContext) -> AgentDecision:
    mode = settings.llm_mode
    try:
        if mode == "anthropic" and settings.anthropic_api_key:
            from app.agent import claude_llm
            return _sandbox(claude_llm.decide(ctx), ctx)
        if mode == "groq" and settings.groq_api_key:
            from app.agent import groq_llm
            return _sandbox(groq_llm.decide(ctx), ctx)
    except Exception as e:
        log.warning("%s LLM call failed, falling back to stub: %s", mode, e)
    return stub_llm.decide(ctx)
