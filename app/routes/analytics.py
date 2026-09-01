from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db import get_db
from app.models.entities import RecoveryCase, Payment

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    at_risk = db.query(func.coalesce(func.sum(RecoveryCase.revenue_at_risk), 0.0)).scalar() or 0.0
    recovered = db.query(func.coalesce(func.sum(RecoveryCase.recovered_amount), 0.0)).scalar() or 0.0
    total_cases = db.query(func.count(RecoveryCase.id)).scalar() or 0
    recovered_cases = db.query(func.count(RecoveryCase.id)).filter(RecoveryCase.status == "recovered").scalar() or 0
    return {
        "revenue_at_risk": at_risk,
        "revenue_recovered": recovered,
        "recovery_rate": (recovered / at_risk) if at_risk else 0.0,
        "cases_total": total_cases,
        "cases_recovered": recovered_cases,
    }
