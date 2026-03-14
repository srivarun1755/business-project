"""
Credit ledger models for tracking customer credit.
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Numeric, ForeignKey, Index, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin


class TransactionType(str, Enum):
    """Credit transaction types."""
    CREDIT = "credit"  # Amount owed by customer (order)
    DEBIT = "debit"    # Amount paid by customer (payment)
    ADJUSTMENT = "adjustment"  # Manual adjustment
    REFUND = "refund"  # Refund to customer


class CreditLedgerEntry(Base, TimestampMixin):
    """
    Credit ledger entry for double-entry bookkeeping.
    Immutable records for audit trail.
    All calculations are deterministic.
    """
    
    __tablename__ = "credit_ledger_entries"
    
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
    
    # Transaction type
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType),
        nullable=False,
    )
    
    # Amount (always positive, type determines direction)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    # Running balance after this transaction
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    # Reference (order_id, payment_id, etc.)
    reference_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    reference_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        nullable=True,
    )
    
    # Description
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="credit_entries",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_credit_customer", "customer_id"),
        Index("idx_credit_type", "transaction_type"),
        Index("idx_credit_reference", "reference_type", "reference_id"),
        Index("idx_credit_date", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<CreditLedgerEntry {self.transaction_type} amount={self.amount}>"
