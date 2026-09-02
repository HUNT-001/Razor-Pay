"""Action executor.

- `payment_link`: real Razorpay Test Mode Payment Link creation. The action
  outcome is 'pending' until the customer pays and Razorpay fires the
  `payment_link.paid` webhook, which flips the case to 'recovered'.
- `retry` / `delayed_retry` / `notify`: simulated. Razorpay does not expose
  a "re-charge the same failed payment" API in Test Mode; a real retry
  means asking the customer to pay again (which is what a Payment Link
  does). We keep these branches simulated so the agent can still choose
  among them and the metrics reflect the decision mix.
- `escalate`: no-op; the case is marked `escalated` upstream.
"""
import random
import logging
from app.agent.schema import AgentDecision
from app.services import razorpay_client

log = logging.getLogger(__name__)


def execute(decision: AgentDecision, amount: float,
            customer_email: str | None = None,
            customer_contact: str | None = None,
            case_id: int | None = None) -> dict:
    action = decision.recommended_action

    if action == "payment_link":
        try:
            resp = razorpay_client.create_payment_link(
                amount_inr=amount,
                description=f"RecoverAI recovery: {decision.diagnosis}",
                customer_email=customer_email,
                customer_contact=customer_contact,
                reference_id=f"recoverai_case_{case_id}" if case_id else None,
            )
            return {
                "action": action,
                "result": "pending",   # awaiting customer payment
                "recovered_amount": 0.0,
                "external_ref": resp.get("id"),
                "short_url": resp.get("short_url"),
            }
        except Exception as e:
            log.exception("payment_link creation failed")
            return {
                "action": action,
                "result": "failed",
                "recovered_amount": 0.0,
                "external_ref": None,
                "error": str(e),
            }

    if action == "escalate":
        return {"action": action, "result": "escalated",
                "recovered_amount": 0.0, "external_ref": None}

    # Simulated actions (retry / delayed_retry / notify)
    success_prob = {
        "retry": 0.55,
        "delayed_retry": 0.65,
        "notify": 0.4,
    }.get(action, 0.3)
    success = random.random() < success_prob
    return {
        "action": action,
        "result": "success" if success else "failed",
        "recovered_amount": amount if success else 0.0,
        "external_ref": f"sim_{action}_{random.randint(1000, 9999)}",
    }
