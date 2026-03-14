import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, func, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class LedgerEntryType(str, enum.Enum):
    INVOICE_CREATED = "invoice_created"
    PAYMENT_RECEIVED = "payment_received"
    CREDIT_ADJUSTMENT = "credit_adjustment"
    CREDIT_NOTE = "credit_note"


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=False, index=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        SAEnum(LedgerEntryType), nullable=False
    )
    reference_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Positive = amount owed by customer (debit), Negative = credit to customer
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="ledger_entries"
    )
