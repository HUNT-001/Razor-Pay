from app.agent.schema import AgentContext, AgentDecision
from app.config import settings
from app.agent import stub_llm


def get_decision(ctx: AgentContext) -> AgentDecision:
    if settings.llm_mode == "stub":
        return stub_llm.decide(ctx)
    # TODO: wire anthropic / openai in Phase 3
    return stub_llm.decide(ctx)
