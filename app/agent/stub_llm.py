"""Deterministic stub 'LLM' — returns structured decisions so the pipeline
works end-to-end before a real model is wired in."""
from app.agent.schema import AgentContext, AgentDecision


def decide(ctx: AgentContext) -> AgentDecision:
    reason = (ctx.failure_reason or "").lower()

    if "timeout" in reason or "gateway" in reason or "network" in reason:
        return AgentDecision(
            diagnosis="transient_issuer_or_network_failure",
            confidence=0.85,
            recommended_action="retry" if ctx.attempt_number == 1 else "delayed_retry",
            reason="Failure signature matches transient issuer/network issue; customer history supports quick retry.",
            customer_message="We hit a temporary hiccup with your payment — retrying now.",
        )
    if "insufficient" in reason or "balance" in reason:
        return AgentDecision(
            diagnosis="insufficient_funds",
            confidence=0.9,
            recommended_action="delayed_retry" if ctx.attempt_number < 2 else "payment_link",
            reason="Liquidity issue — a delayed retry or a payment link gives the customer time to add funds.",
            customer_message="Your payment didn't go through. We'll try again shortly, or you can use the link we sent.",
        )
    if ctx.attempt_number >= 3:
        return AgentDecision(
            diagnosis="repeated_failure",
            confidence=0.7,
            recommended_action="escalate",
            reason="Multiple attempts exhausted; further automated retries are unlikely to succeed.",
        )
    if reason == "" or "abandon" in reason:
        return AgentDecision(
            diagnosis="checkout_abandoned",
            confidence=0.6,
            recommended_action="notify",
            reason="Purchase intent without a completed payment — a reminder is the lightest-touch action.",
            customer_message="Looks like you didn't finish your order — we saved your cart.",
        )
    return AgentDecision(
        diagnosis="unknown_failure",
        confidence=0.5,
        recommended_action="payment_link",
        reason="No strong signal — offer a fresh payment link.",
    )
