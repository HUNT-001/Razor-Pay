from datetime import datetime
from sqlalchemy.orm import Session
from app.models.entities import (
    Payment, RecoveryCase, RecoveryAction, AuditLog, Customer,
)
from app.agent.schema import AgentContext
from app.agent.router import get_decision
from app.services.policy import evaluate
from app.services.executor import execute


def open_case_for_payment(db: Session, payment: Payment) -> RecoveryCase:
    existing = db.query(RecoveryCase).filter_by(payment_id=payment.id).first()
    if existing:
        return existing
    case = RecoveryCase(
        payment_id=payment.id,
        revenue_at_risk=payment.amount,
        status="open",
    )
    db.add(case)
    db.add(AuditLog(event="case.opened", payload={"payment_id": payment.id, "amount": payment.amount}))
    db.commit()
    db.refresh(case)
    return case


def run_recovery_cycle(db: Session, case: RecoveryCase) -> RecoveryAction:
    payment = case.payment
    customer = payment.customer
    total = (customer.success_count + customer.failure_count) if customer else 0
    success_rate = (customer.success_count / total) if total else 0.5

    ctx = AgentContext(
        amount=payment.amount,
        failure_reason=payment.failure_reason,
        attempt_number=case.attempts + 1,
        customer_success_rate=success_rate,
        customer_previous_failures=customer.failure_count if customer else 0,
        payment_method=payment.method,
    )
    decision = get_decision(ctx)
    policy = evaluate(decision, case, payment.amount)

    action = RecoveryAction(
        case_id=case.id,
        action_type=decision.recommended_action,
        diagnosis=decision.diagnosis,
        confidence=decision.confidence,
        reason=decision.reason,
        policy_decision="approved" if policy.approved else "rejected",
        result="pending",
    )
    db.add(action)
    case.attempts += 1
    case.status = "recovering"

    if not policy.approved:
        action.result = "blocked"
        case.status = "stopped"
        db.add(AuditLog(event="policy.rejected", case_id=case.id, payload=policy.checks))
        db.commit()
        db.refresh(action)
        return action

    outcome = execute(decision, payment.amount)
    action.result = outcome["result"]
    action.external_ref = outcome["external_ref"]

    if outcome["result"] == "success":
        case.status = "recovered"
        case.recovered_amount = outcome["recovered_amount"]
    elif case.attempts >= 3:
        case.status = "escalated"

    db.add(AuditLog(
        event="action.executed",
        case_id=case.id,
        payload={
            "action": outcome["action"],
            "result": outcome["result"],
            "recovered_amount": outcome["recovered_amount"],
            "diagnosis": decision.diagnosis,
            "confidence": decision.confidence,
        },
    ))
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(action)
    return action
