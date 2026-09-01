from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.entities import RecoveryCase, RecoveryAction, AuditLog

router = APIRouter(prefix="/recovery", tags=["recovery"])


@router.get("/cases")
def list_cases(db: Session = Depends(get_db), status: str | None = None, limit: int = 50):
    q = db.query(RecoveryCase)
    if status:
        q = q.filter(RecoveryCase.status == status)
    rows = q.order_by(RecoveryCase.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": c.id, "payment_id": c.payment_id, "status": c.status,
            "attempts": c.attempts, "revenue_at_risk": c.revenue_at_risk,
            "recovered_amount": c.recovered_amount,
        } for c in rows
    ]


@router.get("/cases/{case_id}")
def case_detail(case_id: int, db: Session = Depends(get_db)):
    c = db.query(RecoveryCase).get(case_id)
    if not c:
        raise HTTPException(404)
    actions = db.query(RecoveryAction).filter_by(case_id=case_id).order_by(RecoveryAction.id).all()
    logs = db.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id).all()
    return {
        "case": {
            "id": c.id, "status": c.status, "attempts": c.attempts,
            "revenue_at_risk": c.revenue_at_risk, "recovered_amount": c.recovered_amount,
        },
        "payment": {
            "id": c.payment.id, "amount": c.payment.amount,
            "failure_reason": c.payment.failure_reason, "method": c.payment.method,
        },
        "actions": [
            {"type": a.action_type, "diagnosis": a.diagnosis, "confidence": a.confidence,
             "reason": a.reason, "policy": a.policy_decision, "result": a.result,
             "external_ref": a.external_ref}
            for a in actions
        ],
        "audit_log": [{"event": l.event, "payload": l.payload, "at": l.created_at.isoformat()} for l in logs],
    }
