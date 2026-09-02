from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text,
)
from sqlalchemy.orm import relationship
from app.db import Base


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, index=True)
    email = Column(String)
    phone = Column(String)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    razorpay_payment_id = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    amount = Column(Float, nullable=False)  # in INR (rupees)
    currency = Column(String, default="INR")
    status = Column(String)  # created | authorized | captured | failed | refunded
    method = Column(String)
    failure_reason = Column(String)
    error_code = Column(String)
    error_source = Column(String)
    error_step = Column(String)
    error_reason_code = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    event_type = Column(String)  # payment.failed | payment.captured | ...
    raw = Column(JSON)
    received_at = Column(DateTime, default=datetime.utcnow)


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), unique=True)
    revenue_at_risk = Column(Float)
    status = Column(String, default="open")  # open | recovering | recovered | escalated | stopped
    attempts = Column(Integer, default=0)
    recovered_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payment = relationship("Payment")
    actions = relationship("RecoveryAction", back_populates="case")


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"))
    action_type = Column(String)  # retry | delayed_retry | payment_link | notify | escalate
    diagnosis = Column(String)
    confidence = Column(Float)
    reason = Column(Text)
    policy_decision = Column(String)  # approved | rejected
    external_ref = Column(String)  # e.g. payment_link id
    result = Column(String)  # pending | success | failed
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("RecoveryCase", back_populates="actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=True)
    event = Column(String)
    payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
