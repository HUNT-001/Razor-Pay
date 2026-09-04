"""Escalation destination. Slack webhook if configured, always a local log."""
import logging
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger("recoverai.escalation")
_LOG_PATH = Path("escalations.log")


def notify(case_id: int, amount: float, diagnosis: str, attempts: int, reason: str) -> None:
    line = (f"CASE #{case_id} ESCALATED · ₹{amount:,.2f} · "
            f"{diagnosis} · {attempts} attempts · {reason}")
    log.warning(line)
    try:
        _LOG_PATH.open("a", encoding="utf-8").write(line + "\n")
    except OSError:
        pass

    url = settings.escalation_webhook_url
    if not url:
        return
    try:
        payload = {
            "text": f":rotating_light: *RecoverAI escalation* · Case #{case_id}",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn",
                 "text": f"*Case #{case_id}* · *₹{amount:,.2f}* at risk"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Diagnosis*\n{diagnosis}"},
                    {"type": "mrkdwn", "text": f"*Attempts*\n{attempts}"},
                ]},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": reason}]},
            ],
        }
        httpx.post(url, json=payload, timeout=5.0)
    except Exception as e:
        log.warning("escalation webhook failed: %s", e)
