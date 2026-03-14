"""
Invoice models for GST-compliant invoice generation.
"""
from decimal import Decimal
from datetime import datetime, date
from typing import List, Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Numeric, Date, ForeignKey, Index, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin


class InvoiceStatus(str, Enum):
    """Invoice status enumeration."""
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Invoice(Base, TimestampMixin):
    """
    GST-compliant invoice entity.
    All calculations are deterministic.
    """
    
    __tablename__ = "invoices"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Invoice number (GST format: STATE_CODE/YEAR/SERIAL)
    invoice_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Link to order
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id"),
        unique=True,
        nullable=False,
    )
    
    # Customer info (denormalized for invoice permanence)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    customer_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_state_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    
    # Seller info
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    seller_address: Mapped[str] = mapped_column(Text, nullable=False)
    seller_state: Mapped[str] = mapped_column(String(100), nullable=False)
    seller_state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    
    # Dates
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    
    # Status
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(InvoiceStatus),
        default=InvoiceStatus.DRAFT,
        nullable=False,
    )
    
    # Amounts (deterministic calculations)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    
    # GST components (CGST + SGST for intra-state, IGST for inter-state)
    cgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    sgst_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    igst_amount: Mapped[Decimal] = mapped_column(
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
    
    # Amount in words
    amount_in_words: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # PDF storage
    pdf_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="invoice",
    )
    items: Mapped[List["InvoiceItem"]] = relationship(
        "InvoiceItem",
        back_populates="invoice",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_invoice_order", "order_id"),
        Index("idx_invoice_date", "invoice_date"),
        Index("idx_invoice_status", "status"),
    )
    
    @property
    def is_inter_state(self) -> bool:
        """Check if this is an inter-state transaction."""
        return self.seller_state_code != self.customer_state_code
    
    @property
    def total_tax(self) -> Decimal:
        """Total GST amount."""
        if self.is_inter_state:
            return self.igst_amount
        return self.cgst_amount + self.sgst_amount
    
    def calculate_totals(self) -> None:
        """
        Deterministic calculation of invoice totals.
        GST rules:
        - Intra-state: CGST (9%) + SGST (9%) = 18%
        - Inter-state: IGST (18%)
        """
        # Calculate subtotal
        self.subtotal = sum(
            item.taxable_amount for item in self.items
        ) if self.items else Decimal("0.00")
        
        # Calculate GST based on transaction type
        total_tax = sum(
            item.tax_amount for item in self.items
        ) if self.items else Decimal("0.00")
        
        if self.is_inter_state:
            self.igst_amount = total_tax
            self.cgst_amount = Decimal("0.00")
            self.sgst_amount = Decimal("0.00")
        else:
            # Split equally between CGST and SGST
            half_tax = total_tax / Decimal("2")
            self.cgst_amount = half_tax.quantize(Decimal("0.01"))
            self.sgst_amount = (total_tax - self.cgst_amount).quantize(Decimal("0.01"))
            self.igst_amount = Decimal("0.00")
        
        # Total amount
        self.total_amount = self.subtotal + total_tax - self.discount_amount
    
    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number} total={self.total_amount}>"


class InvoiceItem(Base, TimestampMixin):
    """Invoice line item with GST details."""
    
    __tablename__ = "invoice_items"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Invoice
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Item details
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    
    # Quantity
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
    )
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Pricing
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    taxable_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    # GST
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
    
    # Total
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    
    # Relationships
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="items",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_invoice_item_invoice", "invoice_id"),
    )
    
    def calculate_totals(self) -> None:
        """Deterministic calculation of item totals."""
        self.taxable_amount = Decimal(str(self.quantity)) * self.unit_price
        self.tax_amount = (self.taxable_amount * self.gst_rate) / Decimal("100")
        self.total_amount = self.taxable_amount + self.tax_amount
    
    def __repr__(self) -> str:
        return f"<InvoiceItem {self.description} qty={self.quantity}>"
