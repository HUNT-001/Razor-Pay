import logging

from app.agent import stub_llm
from app.agent.schema import AgentContext, AgentDecision
from app.config import settings

log = logging.getLogger(__name__)


def get_decision(ctx: AgentContext) -> AgentDecision:
    mode = settings.llm_mode
    try:
        if mode == "anthropic" and settings.anthropic_api_key:
            from app.agent import claude_llm
            return claude_llm.decide(ctx)
        if mode == "groq" and settings.groq_api_key:
            from app.agent import groq_llm
            return groq_llm.decide(ctx)
    except Exception as e:
        log.warning("%s LLM call failed, falling back to stub: %s", mode, e)
    return stub_llm.decide(ctx)
