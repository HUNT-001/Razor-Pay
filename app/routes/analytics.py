from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.entities import RecoveryAction, RecoveryCase

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    at_risk = db.query(func.coalesce(func.sum(RecoveryCase.revenue_at_risk), 0.0)).scalar() or 0.0
    recovered = db.query(func.coalesce(func.sum(RecoveryCase.recovered_amount), 0.0)).scalar() or 0.0
    total_cases = db.query(func.count(RecoveryCase.id)).scalar() or 0
    recovered_cases = db.query(func.count(RecoveryCase.id)) \
        .filter(RecoveryCase.status == "recovered").scalar() or 0
    escalated = db.query(func.count(RecoveryCase.id)) \
        .filter(RecoveryCase.status == "escalated").scalar() or 0

    # Cost accounting
    action_counts = dict(
        db.query(RecoveryAction.action_type, func.count(RecoveryAction.id))
          .group_by(RecoveryAction.action_type).all()
    )
    link_actions = action_counts.get("payment_link", 0)
    sim_actions = sum(v for k, v in action_counts.items()
                      if k in {"retry", "delayed_retry", "notify"})
    total_actions = sum(action_counts.values())

    cost = (total_actions * settings.cost_per_llm_decision_inr
            + link_actions * settings.cost_per_payment_link_inr
            + sim_actions * settings.cost_per_simulated_action_inr)

    net = recovered - cost
    roi = (recovered / cost) if cost else 0.0
    cost_per_recovered_rupee = (cost / recovered) if recovered else 0.0

    return {
        "revenue_at_risk": at_risk,
        "revenue_recovered": recovered,
        "recovery_rate": (recovered / at_risk) if at_risk else 0.0,
        "cases_total": total_cases,
        "cases_recovered": recovered_cases,
        "cases_escalated": escalated,
        "total_actions": total_actions,
        "action_breakdown": action_counts,
        "cost_inr": round(cost, 2),
        "net_recovered_inr": round(net, 2),
        "roi_multiple": round(roi, 2),
        "cost_per_recovered_rupee": round(cost_per_recovered_rupee, 4),
    }
