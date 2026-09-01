from typing import Literal, Optional
from pydantic import BaseModel, Field

ActionType = Literal["retry", "delayed_retry", "payment_link", "notify", "escalate"]


class AgentContext(BaseModel):
    amount: float
    failure_reason: Optional[str] = None
    attempt_number: int = 1
    customer_success_rate: float = 0.5
    customer_previous_failures: int = 0
    time_since_failure_min: int = 0
    payment_method: Optional[str] = None


class AgentDecision(BaseModel):
    diagnosis: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: ActionType
    reason: str
    customer_message: Optional[str] = None
