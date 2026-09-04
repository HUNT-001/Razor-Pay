from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.db import get_db
from app.models.entities import RecoveryCase, RecoveryAction, AuditLog

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _serialize_case(c: RecoveryCase, actions=None, logs=None) -> dict:
    out = {
        "id": c.id, "payment_id": c.payment_id, "status": c.status,
        "attempts": c.attempts, "revenue_at_risk": c.revenue_at_risk,
        "recovered_amount": c.recovered_amount,
    }
    if actions is not None:
        out["actions"] = [
            {"type": a.action_type, "diagnosis": a.diagnosis, "confidence": a.confidence,
             "reason": a.reason, "policy": a.policy_decision, "result": a.result,
             "external_ref": a.external_ref}
            for a in actions
        ]
    if logs is not None:
        out["audit_log"] = [
            {"event": l.event, "payload": l.payload, "at": l.created_at.isoformat()}
            for l in logs
        ]
    if actions is not None:
        p = c.payment
        out["payment"] = {"id": p.id, "amount": p.amount,
                          "failure_reason": p.failure_reason, "method": p.method}
    return out


@router.get("/cases")
def list_cases(
    db: Session = Depends(get_db),
    status: str | None = None,
    limit: int = 100,
    expand: bool = Query(False, description="include actions + audit_log per case"),
):
    q = db.query(RecoveryCase)
    if status:
        q = q.filter(RecoveryCase.status == status)
    q = q.order_by(RecoveryCase.updated_at.desc()).limit(limit)

    if not expand:
        return [_serialize_case(c) for c in q.all()]

    cases = q.options(joinedload(RecoveryCase.payment)).all()
    case_ids = [c.id for c in cases]
    actions_by_case: dict[int, list[RecoveryAction]] = {i: [] for i in case_ids}
    logs_by_case: dict[int, list[AuditLog]] = {i: [] for i in case_ids}
    for a in db.query(RecoveryAction).filter(RecoveryAction.case_id.in_(case_ids)).order_by(RecoveryAction.id):
        actions_by_case[a.case_id].append(a)
    for l in db.query(AuditLog).filter(AuditLog.case_id.in_(case_ids)).order_by(AuditLog.id):
        logs_by_case[l.case_id].append(l)
    return [_serialize_case(c, actions_by_case[c.id], logs_by_case[c.id]) for c in cases]


@router.get("/cases/{case_id}")
def case_detail(case_id: int, db: Session = Depends(get_db)):
    c = db.query(RecoveryCase).get(case_id)
    if not c:
        raise HTTPException(404)
    actions = db.query(RecoveryAction).filter_by(case_id=case_id).order_by(RecoveryAction.id).all()
    logs = db.query(AuditLog).filter_by(case_id=case_id).order_by(AuditLog.id).all()
    data = _serialize_case(c, actions, logs)
    return {"case": {k: data[k] for k in ("id", "status", "attempts", "revenue_at_risk", "recovered_amount")},
            "payment": data["payment"], "actions": data["actions"], "audit_log": data["audit_log"]}
