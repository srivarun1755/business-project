"""
Order models for order management.
"""
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Numeric, Integer, ForeignKey, Index, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin, SoftDeleteMixin


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class OrderSource(str, Enum):
    """Order source channel."""
    WHATSAPP_TEXT = "whatsapp_text"
    WHATSAPP_VOICE = "whatsapp_voice"
    API = "api"
    MANUAL = "manual"


class Order(Base, TimestampMixin, SoftDeleteMixin):
    """
    Order entity representing a customer order.
    """
    
    __tablename__ = "orders"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Order number (human readable)
    order_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Customer
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customers.id"),
        nullable=False,
    )
    
    # Status
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    
    # Source
    source: Mapped[OrderSource] = mapped_column(
        SQLEnum(OrderSource),
        default=OrderSource.WHATSAPP_TEXT,
        nullable=False,
    )
    
    # Original message for audit
    raw_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Parsed JSON from AI
    parsed_data: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Amounts (deterministic calculations)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    
    # Payment status
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    
    # Idempotency key for webhook processing
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="orders",
    )
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    invoice: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        back_populates="order",
        uselist=False,
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_order_customer", "customer_id"),
        Index("idx_order_status", "status"),
        Index("idx_order_created", "created_at"),
        Index("idx_order_idempotency", "idempotency_key"),
    )
    
    @property
    def balance_due(self) -> Decimal:
        """Calculate remaining balance."""
        return self.total_amount - self.paid_amount
    
    @property
    def is_fully_paid(self) -> bool:
        """Check if order is fully paid."""
        return self.paid_amount >= self.total_amount
    
    def calculate_totals(self) -> None:
        """
        Deterministic calculation of order totals.
        Called after items are added/modified.
        """
        self.subtotal = sum(
            item.total_price for item in self.items
        ) if self.items else Decimal("0.00")
        
        self.tax_amount = sum(
            item.tax_amount for item in self.items
        ) if self.items else Decimal("0.00")
        
        self.total_amount = self.subtotal + self.tax_amount - self.discount_amount
    
    def __repr__(self) -> str:
        return f"<Order {self.order_number} status={self.status}>"


class OrderItem(Base, TimestampMixin):
    """Order line item."""
    
    __tablename__ = "order_items"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Order
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Product
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("products.id"),
        nullable=False,
    )
    
    # Original product name from order (for reference)
    original_product_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Quantity and unit
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
    )
    unit: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # Pricing (snapshot at order time)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    # Tax
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("18.00"),
        nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    
    # HSN Code for GST
    hsn_code: Mapped[Optional[str]] = mapped_column(
        String(8),
        nullable=True,
    )
    
    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
    )
    product: Mapped["Product"] = relationship("Product")
    
    # Indexes
    __table_args__ = (
        Index("idx_order_item_order", "order_id"),
        Index("idx_order_item_product", "product_id"),
    )
    
    def calculate_totals(self) -> None:
        """
        Deterministic calculation of item totals.
        """
        # Total price = quantity * unit_price
        self.total_price = Decimal(str(self.quantity)) * self.unit_price
        
        # Tax calculation (GST)
        self.tax_amount = (self.total_price * self.gst_rate) / Decimal("100")
    
    def __repr__(self) -> str:
        return f"<OrderItem {self.product_id} qty={self.quantity}>"
