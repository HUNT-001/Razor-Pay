from app.agent.schema import AgentContext
from app.agent.stub_llm import decide


def _ctx(**kw):
    defaults = dict(amount=1000.0, attempt_number=1, customer_success_rate=0.5)
    defaults.update(kw)
    return AgentContext(**defaults)


def test_gateway_timeout_retries_first_then_delays():
    d1 = decide(_ctx(error_code="GATEWAY_ERROR", error_source="gateway",
                     error_reason_code="gateway_timeout", attempt_number=1))
    assert d1.diagnosis == "transient_gateway_failure"
    assert d1.recommended_action == "retry"
    d2 = decide(_ctx(error_code="GATEWAY_ERROR", error_source="gateway",
                     error_reason_code="gateway_timeout", attempt_number=2))
    assert d2.recommended_action == "delayed_retry"


def test_insufficient_funds_delayed_then_link():
    d1 = decide(_ctx(error_reason_code="insufficient_funds", attempt_number=1))
    assert d1.diagnosis == "insufficient_funds"
    assert d1.recommended_action == "delayed_retry"
    d2 = decide(_ctx(error_reason_code="insufficient_funds", attempt_number=2))
    assert d2.recommended_action == "payment_link"


def test_invalid_instrument_always_payment_link():
    d = decide(_ctx(error_reason_code="invalid_card_number"))
    assert d.diagnosis == "invalid_instrument"
    assert d.recommended_action == "payment_link"


def test_risk_declined_escalates():
    d = decide(_ctx(error_source="risk", error_reason_code="payment_fraud"))
    assert d.diagnosis == "risk_declined"
    assert d.recommended_action == "escalate"


def test_attempts_exhausted_escalates_except_invalid_instrument():
    d = decide(_ctx(error_reason_code="gateway_timeout", attempt_number=3))
    assert d.recommended_action == "escalate"
    # invalid_instrument keeps trying payment_link (only viable action)
    d2 = decide(_ctx(error_reason_code="invalid_card_number", attempt_number=3))
    assert d2.recommended_action == "payment_link"


def test_bank_declined_steers_on_customer_history():
    d_bad = decide(_ctx(error_source="bank", error_step="payment_authorization",
                        customer_success_rate=0.1))
    assert d_bad.recommended_action == "payment_link"
    d_good = decide(_ctx(error_source="bank", error_step="payment_authorization",
                         customer_success_rate=0.9))
    assert d_good.recommended_action == "delayed_retry"


def test_confidence_within_bounds():
    d = decide(_ctx(error_reason_code="gateway_timeout"))
    assert 0.0 <= d.confidence <= 1.0
