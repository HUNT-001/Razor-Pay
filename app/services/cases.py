from datetime import datetime

from sqlalchemy.orm import Session

from app.agent.router import get_decision
from app.agent.schema import AgentContext
from app.models.entities import (AuditLog, Payment, RecoveryAction, RecoveryCase)
from app.services.escalation import notify as notify_escalation
from app.services.executor import execute
from app.services.policy import evaluate


def open_case_for_payment(db: Session, payment: Payment) -> RecoveryCase:
    existing = db.query(RecoveryCase).filter_by(payment_id=payment.id).first()
    if existing:
        return existing
    case = RecoveryCase(payment_id=payment.id, revenue_at_risk=payment.amount, status="open")
    db.add(case)
    db.add(AuditLog(event="case.opened",
                    payload={"payment_id": payment.id, "amount": payment.amount}))
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
        error_code=payment.error_code,
        error_source=payment.error_source,
        error_step=payment.error_step,
        error_reason_code=payment.error_reason_code,
        attempt_number=case.attempts + 1,
        customer_success_rate=success_rate,
        customer_previous_failures=customer.failure_count if customer else 0,
        customer_previous_successes=customer.success_count if customer else 0,
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
    db.flush()

    if not policy.approved:
        action.result = "blocked"
        case.status = "stopped"
        db.add(AuditLog(event="policy.rejected", case_id=case.id, payload=policy.checks))
        db.commit(); db.refresh(action)
        return action

    outcome = execute(
        decision, payment.amount,
        customer_email=customer.email if customer else None,
        customer_contact=customer.phone if customer else None,
        case_id=case.id,
        case_attempt=case.attempts,
    )
    action.result = outcome["result"]
    action.external_ref = outcome.get("external_ref")

    if outcome["result"] == "success":
        case.status = "recovered"
        case.recovered_amount = outcome.get("recovered_amount", payment.amount)
    elif outcome["result"] == "pending":
        case.status = "recovering"  # awaits payment_link.paid webhook
    elif outcome["result"] == "escalated" or case.attempts >= 3:
        case.status = "escalated"
        notify_escalation(case.id, payment.amount, decision.diagnosis,
                          case.attempts, decision.reason)

    db.add(AuditLog(event="action.executed", case_id=case.id, payload={
        "action": outcome["action"],
        "result": outcome["result"],
        "recovered_amount": outcome.get("recovered_amount", 0.0),
        "diagnosis": decision.diagnosis,
        "confidence": decision.confidence,
        "external_ref": outcome.get("external_ref"),
        "short_url": outcome.get("short_url"),
        "error": outcome.get("error"),
    }))
    case.updated_at = datetime.utcnow()
    case.last_action_at = datetime.utcnow()
    db.commit(); db.refresh(action)
    return action


def mark_case_recovered_by_link(db: Session, payment_link_id: str,
                                paid_amount_inr: float) -> RecoveryCase | None:
    action = (db.query(RecoveryAction)
              .filter_by(external_ref=payment_link_id, action_type="payment_link")
              .order_by(RecoveryAction.id.desc()).first())
    if not action:
        return None
    case = db.query(RecoveryCase).get(action.case_id)
    if not case:
        return None
    action.result = "success"
    case.status = "recovered"
    case.recovered_amount = paid_amount_inr
    case.updated_at = datetime.utcnow()
    db.add(AuditLog(event="payment_link.paid", case_id=case.id,
                    payload={"payment_link_id": payment_link_id, "amount": paid_amount_inr}))
    db.commit(); db.refresh(case)
    return case


def mark_case_stopped_by_link(db: Session, payment_link_id: str) -> RecoveryCase | None:
    """Called when Razorpay reports payment_link.expired / .cancelled."""
    action = (db.query(RecoveryAction)
              .filter_by(external_ref=payment_link_id, action_type="payment_link")
              .order_by(RecoveryAction.id.desc()).first())
    if not action:
        return None
    case = db.query(RecoveryCase).get(action.case_id)
    if not case or case.status == "recovered":
        return case
    action.result = "expired"
    case.status = "stopped"
    case.updated_at = datetime.utcnow()
    db.add(AuditLog(event="payment_link.expired", case_id=case.id,
                    payload={"payment_link_id": payment_link_id}))
    db.commit(); db.refresh(case)
    return case


def close_open_case_on_direct_capture(db: Session, payment: Payment) -> RecoveryCase | None:
    """Customer paid the ORIGINAL payment directly (e.g. via a manual retry)
    without using our recovery link. Any open case for that payment closes."""
    case = db.query(RecoveryCase).filter_by(payment_id=payment.id).first()
    if not case or case.status == "recovered":
        return case
    case.status = "recovered"
    case.recovered_amount = payment.amount
    case.updated_at = datetime.utcnow()
    db.add(AuditLog(event="payment.captured_direct", case_id=case.id,
                    payload={"payment_id": payment.id, "amount": payment.amount}))
    db.commit(); db.refresh(case)
    return case
