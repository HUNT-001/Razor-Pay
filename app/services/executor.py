"""Recovery-action executor. Real Razorpay for payment_link; simulated otherwise."""
import logging
import random
import time as _time

from app.agent.schema import AgentDecision
from app.services import razorpay_client

log = logging.getLogger(__name__)

# retry/delayed_retry/notify are simulated: Razorpay has no "recharge failed payment"
# API, so a real retry == a fresh Payment Link (which is a separate action).
_SIM_SUCCESS_PROB = {"retry": 0.55, "delayed_retry": 0.65, "notify": 0.4}


def execute(decision: AgentDecision, amount: float,
            customer_email: str | None = None,
            customer_contact: str | None = None,
            case_id: int | None = None,
            case_attempt: int = 1) -> dict:
    action = decision.recommended_action

    if action == "payment_link":
        try:
            resp = razorpay_client.create_payment_link(
                amount_inr=amount,
                description=f"RecoverAI recovery: {decision.diagnosis}",
                customer_email=customer_email,
                customer_contact=customer_contact,
                reference_id=f"recoverai_c{case_id}_{int(__import__('time').time())}" if case_id else None,
            )
            return {"action": action, "result": "pending", "recovered_amount": 0.0,
                    "external_ref": resp.get("id"), "short_url": resp.get("short_url")}
        except Exception as e:
            log.exception("payment_link creation failed")
            return {"action": action, "result": "failed", "recovered_amount": 0.0,
                    "external_ref": None, "error": str(e)}

    if action == "escalate":
        return {"action": action, "result": "escalated",
                "recovered_amount": 0.0, "external_ref": None}

    prob = _SIM_SUCCESS_PROB.get(action, 0.3)
    success = random.random() < prob
    return {
        "action": action,
        "result": "success" if success else "failed",
        "recovered_amount": amount if success else 0.0,
        "external_ref": f"sim_{action}_{random.randint(1000, 9999)}",
    }
