"""
Inventory models for stock management.
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Numeric, Integer, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin


class TransactionType(str, Enum):
    """Inventory transaction types."""
    STOCK_IN = "stock_in"
    STOCK_OUT = "stock_out"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
    DAMAGE = "damage"
    TRANSFER = "transfer"


class InventoryItem(Base, TimestampMixin):
    """
    Inventory item tracking current stock levels.
    Uses optimistic locking for concurrent updates.
    """
    
    __tablename__ = "inventory_items"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Product link
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("products.id"),
        unique=True,
        nullable=False,
    )
    
    # Stock levels
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        default=Decimal("0.000"),
        nullable=False,
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        default=Decimal("0.000"),
        nullable=False,
    )
    
    # Thresholds
    reorder_level: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        default=Decimal("10.000"),
        nullable=False,
    )
    max_stock_level: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        default=Decimal("1000.000"),
        nullable=False,
    )
    
    # Unit
    unit: Mapped[str] = mapped_column(
        String(50),
        default="piece",
        nullable=False,
    )
    
    # Version for optimistic locking
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    
    # Relationships
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="inventory_items",
    )
    transactions: Mapped[list["InventoryTransaction"]] = relationship(
        "InventoryTransaction",
        back_populates="inventory_item",
        lazy="dynamic",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_inventory_product", "product_id"),
        Index("idx_inventory_low_stock", "quantity", "reorder_level"),
    )
    
    @property
    def available_quantity(self) -> Decimal:
        """Calculate available quantity (total - reserved)."""
        return self.quantity - self.reserved_quantity
    
    @property
    def needs_reorder(self) -> bool:
        """Check if stock needs reordering."""
        return self.available_quantity <= self.reorder_level
    
    def can_fulfill(self, requested_quantity: Decimal) -> bool:
        """Check if requested quantity can be fulfilled."""
        return self.available_quantity >= requested_quantity
    
    def __repr__(self) -> str:
        return f"<InventoryItem product_id={self.product_id} qty={self.quantity}>"


class InventoryTransaction(Base, TimestampMixin):
    """
    Inventory transaction log for audit trail.
    Immutable records of all stock movements.
    """
    
    __tablename__ = "inventory_transactions"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Link to inventory item
    inventory_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("inventory_items.id"),
        nullable=False,
    )
    
    # Transaction details
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
    )
    
    # Balance after transaction
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
    )
    
    # Reference (order_id, adjustment reason, etc.)
    reference_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    reference_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        nullable=True,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Relationships
    inventory_item: Mapped["InventoryItem"] = relationship(
        "InventoryItem",
        back_populates="transactions",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_transaction_item", "inventory_item_id"),
        Index("idx_transaction_type", "transaction_type"),
        Index("idx_transaction_reference", "reference_type", "reference_id"),
        Index("idx_transaction_date", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<InventoryTransaction {self.transaction_type} qty={self.quantity}>"
