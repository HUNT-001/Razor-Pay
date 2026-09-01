"""Action executor. In stub mode, actions are simulated; a Razorpay client
is wired here in Phase 1/7."""
import random
from app.agent.schema import AgentDecision


def execute(decision: AgentDecision, amount: float) -> dict:
    action = decision.recommended_action
    # Simple success model — will be replaced with Razorpay API calls.
    success_prob = {
        "retry": 0.55,
        "delayed_retry": 0.65,
        "payment_link": 0.7,
        "notify": 0.4,
        "escalate": 0.0,
    }.get(action, 0.3)
    success = random.random() < success_prob
    return {
        "action": action,
        "result": "success" if success else "failed",
        "recovered_amount": amount if success else 0.0,
        "external_ref": f"stub_{action}_{random.randint(1000, 9999)}",
    }
