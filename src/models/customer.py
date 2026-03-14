"""
Customer model for storing customer information.
"""
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4
from sqlalchemy import String, Numeric, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin, SoftDeleteMixin


class Customer(Base, TimestampMixin, SoftDeleteMixin):
    """Customer entity representing buyers/retailers."""
    
    __tablename__ = "customers"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Contact Information
    phone: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    whatsapp_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Business Information
    business_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pincode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    
    # Credit Settings
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("50000.00"),
        nullable=False,
    )
    credit_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    orders: Mapped[List["Order"]] = relationship(
        "Order", 
        back_populates="customer",
        lazy="dynamic",
    )
    credit_entries: Mapped[List["CreditLedgerEntry"]] = relationship(
        "CreditLedgerEntry",
        back_populates="customer",
        lazy="dynamic",
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="customer",
        lazy="dynamic",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_customer_phone_active", "phone", "is_active"),
        Index("idx_customer_gstin", "gstin"),
    )
    
    def __repr__(self) -> str:
        return f"<Customer {self.name} ({self.phone})>"
    
    @property
    def available_credit(self) -> Decimal:
        """Calculate available credit limit."""
        return self.credit_limit - self.credit_balance
    
    def can_place_order(self, order_amount: Decimal) -> bool:
        """Check if customer can place order based on credit limit."""
        return self.available_credit >= order_amount
