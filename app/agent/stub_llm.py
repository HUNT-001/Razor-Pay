"""Deterministic 'LLM' stub. Uses Razorpay's structured error fields
(error_source / error_reason / error_step / error_code) plus customer
history to produce a real per-case decision — no more 'unknown_failure'
for everything."""
from app.agent.schema import AgentContext, AgentDecision

# Reason-code map — most common Razorpay codes we care about
INSUFFICIENT_FUNDS_CODES = {
    "insufficient_funds", "BAD_REQUEST_INSUFFICIENT_FUNDS",
}
INVALID_INSTRUMENT_CODES = {
    "invalid_card_number", "invalid_expiry", "invalid_cvv",
    "invalid_account_number", "invalid_vpa",
    "card_expired", "payment_method_disabled",
}
FRAUD_CODES = {"payment_fraud", "risk_check_failed"}
AUTH_FAIL_CODES = {"payment_failed", "authentication_failed",
                   "otp_incorrect", "otp_expired", "otp_attempts_exceeded",
                   "3ds_authentication_failed"}


def _diagnose(ctx: AgentContext) -> tuple[str, str]:
    """Return (diagnosis_slug, human_reason)."""
    src = (ctx.error_source or "").lower()
    step = (ctx.error_step or "").lower()
    code = (ctx.error_code or "").upper()
    rcode = (ctx.error_reason_code or "").lower()
    reason_text = (ctx.failure_reason or "").lower()

    if rcode in INSUFFICIENT_FUNDS_CODES or "insufficient" in reason_text:
        return "insufficient_funds", "Liquidity issue on the customer side."
    if rcode in INVALID_INSTRUMENT_CODES or "invalid" in reason_text or "expired" in reason_text:
        return "invalid_instrument", "Payment instrument itself is invalid or expired."
    if rcode in FRAUD_CODES or src == "risk":
        return "risk_declined", "Declined for fraud / risk reasons."
    if code == "GATEWAY_ERROR" or src == "gateway" or "timeout" in reason_text:
        return "transient_gateway_failure", "Upstream gateway/bank issue — typically transient."
    if src == "bank" and step == "payment_authorization":
        return "bank_declined", "Issuer bank declined the authorization."
    if rcode in AUTH_FAIL_CODES or step == "payment_authentication":
        return "authentication_failed", "Customer failed the auth step (OTP / 3DS)."
    if src == "customer":
        return "customer_action_required", "Customer-side error — likely needs a fresh attempt."
    return "unknown_failure", "No strong structured signal."


def decide(ctx: AgentContext) -> AgentDecision:
    diag, why = _diagnose(ctx)

    # Attempt caps override everything except payment_link (which is idempotent from
    # the customer's perspective — a fresh link doesn't cost anything).
    if ctx.attempt_number >= 3 and diag != "invalid_instrument":
        return AgentDecision(
            diagnosis=diag,
            confidence=0.75,
            recommended_action="escalate",
            reason=f"{why} Attempts exhausted ({ctx.attempt_number}); handing off.",
        )

    if diag == "transient_gateway_failure":
        return AgentDecision(
            diagnosis=diag, confidence=0.9,
            recommended_action="retry" if ctx.attempt_number == 1 else "delayed_retry",
            reason=f"{why} High success history ({ctx.customer_success_rate:.0%}) supports a quick retry.",
            customer_message="We hit a temporary issue with your payment — trying again now.",
        )

    if diag == "insufficient_funds":
        return AgentDecision(
            diagnosis=diag, confidence=0.9,
            recommended_action="delayed_retry" if ctx.attempt_number == 1 else "payment_link",
            reason=f"{why} Delayed retry / payment link lets the customer top up first.",
            customer_message="Payment didn't go through — try again in a bit or use the link we sent.",
        )

    if diag == "invalid_instrument":
        return AgentDecision(
            diagnosis=diag, confidence=0.95,
            recommended_action="payment_link",
            reason=f"{why} Retrying the same instrument will fail identically — need a fresh payment method.",
            customer_message="Please use a different card/UPI — here's a fresh payment link.",
        )

    if diag == "risk_declined":
        return AgentDecision(
            diagnosis=diag, confidence=0.85,
            recommended_action="escalate",
            reason=f"{why} Automated recovery is unsafe; hand off to review.",
        )

    if diag == "bank_declined":
        return AgentDecision(
            diagnosis=diag, confidence=0.7,
            recommended_action="payment_link" if ctx.customer_success_rate < 0.5 else "delayed_retry",
            reason=f"{why} Customer success rate {ctx.customer_success_rate:.0%} steers the choice.",
        )

    if diag == "authentication_failed":
        return AgentDecision(
            diagnosis=diag, confidence=0.8,
            recommended_action="payment_link",
            reason=f"{why} Fresh link gives them a clean auth attempt.",
        )

    if diag == "customer_action_required":
        return AgentDecision(
            diagnosis=diag, confidence=0.6,
            recommended_action="payment_link",
            reason=why,
        )

    # unknown_failure fallback
    return AgentDecision(
        diagnosis=diag, confidence=0.5,
        recommended_action="payment_link",
        reason=f"{why} Offering a fresh link is the safest catch-all.",
    )
