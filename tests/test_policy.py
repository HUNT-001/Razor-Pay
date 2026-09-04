from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agent.schema import AgentDecision
from app.services.policy import (
    ALLOWED_ACTIONS, COOLDOWN_SECONDS, MAX_AMOUNT, MAX_ATTEMPTS, evaluate,
)


def _case(**kw):
    defaults = {"status": "recovering", "attempts": 0, "last_action_at": None}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _decision(action="retry"):
    return AgentDecision(diagnosis="x", confidence=0.5,
                         recommended_action=action, reason="r")


def test_approves_first_attempt():
    r = evaluate(_decision("retry"), _case(), 1000)
    assert r.approved


def test_blocks_at_attempt_cap():
    r = evaluate(_decision("retry"), _case(attempts=MAX_ATTEMPTS), 1000)
    assert not r.approved and not r.checks["attempts_under_limit"]


def test_blocks_over_amount_ceiling():
    r = evaluate(_decision("retry"), _case(), MAX_AMOUNT + 1)
    assert not r.approved and not r.checks["amount_under_threshold"]


def test_blocks_already_recovered():
    r = evaluate(_decision("retry"), _case(status="recovered"), 1000)
    assert not r.approved and not r.checks["not_already_recovered"]


def test_blocks_within_cooldown():
    just_now = datetime.utcnow() - timedelta(seconds=COOLDOWN_SECONDS - 5)
    r = evaluate(_decision("retry"), _case(last_action_at=just_now), 1000)
    assert not r.approved and not r.checks["cooldown_satisfied"]


def test_allows_after_cooldown():
    long_ago = datetime.utcnow() - timedelta(seconds=COOLDOWN_SECONDS + 5)
    r = evaluate(_decision("retry"), _case(last_action_at=long_ago), 1000)
    assert r.approved


def test_all_allowed_actions_pass_allowlist():
    for a in ALLOWED_ACTIONS:
        assert evaluate(_decision(a), _case(), 1000).checks["action_in_allowlist"]
