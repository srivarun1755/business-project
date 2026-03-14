"""
Payment models for tracking payments and reminders.
"""
from decimal import Decimal
from datetime import datetime, date
from typing import Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Numeric, Date, Boolean, ForeignKey, Index, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin


class PaymentMethod(str, Enum):
    """Payment methods."""
    CASH = "cash"
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CARD = "card"
    OTHER = "other"


class PaymentStatus(str, Enum):
    """Payment status."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class ReminderStatus(str, Enum):
    """Reminder status."""
    SCHEDULED = "scheduled"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


class Payment(Base, TimestampMixin):
    """
    Payment entity for tracking customer payments.
    """
    
    __tablename__ = "payments"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Customer
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customers.id"),
        nullable=False,
    )
    
    # Invoice (optional, can be general payment)
    invoice_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("invoices.id"),
        nullable=True,
    )
    
    # Payment details
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod),
        default=PaymentMethod.CASH,
        nullable=False,
    )
    
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus),
        default=PaymentStatus.COMPLETED,
        nullable=False,
    )
    
    # Transaction reference
    transaction_reference: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Payment date
    payment_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="payments",
    )
    invoice: Mapped[Optional["Invoice"]] = relationship("Invoice")
    
    # Indexes
    __table_args__ = (
        Index("idx_payment_customer", "customer_id"),
        Index("idx_payment_invoice", "invoice_id"),
        Index("idx_payment_date", "payment_date"),
        Index("idx_payment_status", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<Payment {self.id} amount={self.amount}>"


class PaymentReminder(Base, TimestampMixin):
    """
    Payment reminder scheduling and tracking.
    """
    
    __tablename__ = "payment_reminders"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Customer
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customers.id"),
        nullable=False,
    )
    
    # Invoice
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("invoices.id"),
        nullable=False,
    )
    
    # Reminder details
    reminder_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    
    amount_due: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    days_overdue: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )
    
    # Status
    status: Mapped[ReminderStatus] = mapped_column(
        SQLEnum(ReminderStatus),
        default=ReminderStatus.SCHEDULED,
        nullable=False,
    )
    
    # Message sent
    message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Sent timestamp
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    # Delivery status from WhatsApp
    delivery_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship("Customer")
    invoice: Mapped["Invoice"] = relationship("Invoice")
    
    # Indexes
    __table_args__ = (
        Index("idx_reminder_customer", "customer_id"),
        Index("idx_reminder_invoice", "invoice_id"),
        Index("idx_reminder_date_status", "reminder_date", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<PaymentReminder {self.id} date={self.reminder_date}>"
