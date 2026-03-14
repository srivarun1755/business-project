"""
Product and ProductAlias models for inventory management.
"""
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4
from sqlalchemy import String, Numeric, Boolean, Integer, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin, SoftDeleteMixin


class ProductCategory(Base, TimestampMixin):
    """Product category for organizing products."""
    
    __tablename__ = "product_categories"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("18.00"),
        nullable=False,
    )
    
    # Relationships
    products: Mapped[List["Product"]] = relationship(
        "Product",
        back_populates="category",
        lazy="dynamic",
    )


class Product(Base, TimestampMixin, SoftDeleteMixin):
    """
    Canonical product entity.
    Each product has a unique canonical name for normalization.
    """
    
    __tablename__ = "products"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Product Information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    sku: Mapped[Optional[str]] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Category
    category_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("product_categories.id"),
        nullable=True,
    )
    
    # Pricing
    base_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    unit: Mapped[str] = mapped_column(
        String(50),
        default="piece",
        nullable=False,
    )
    
    # GST
    hsn_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("18.00"),
        nullable=False,
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Relationships
    category: Mapped[Optional["ProductCategory"]] = relationship(
        "ProductCategory",
        back_populates="products",
    )
    aliases: Mapped[List["ProductAlias"]] = relationship(
        "ProductAlias",
        back_populates="product",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    inventory_items: Mapped[List["InventoryItem"]] = relationship(
        "InventoryItem",
        back_populates="product",
        lazy="dynamic",
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_product_canonical_active", "canonical_name", "is_active"),
        Index("idx_product_category", "category_id"),
    )
    
    def __repr__(self) -> str:
        return f"<Product {self.canonical_name}>"


class ProductAlias(Base, TimestampMixin):
    """
    Product alias for fuzzy matching.
    Maps various spellings/names to canonical products.
    Used for O(1) exact match lookups before fuzzy matching.
    """
    
    __tablename__ = "product_aliases"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Alias text (normalized to lowercase)
    alias: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    
    # Link to canonical product
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Match confidence (1.0 = exact match, <1.0 = fuzzy)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        default=Decimal("1.00"),
        nullable=False,
    )
    
    # Source of alias (manual, learned, csv_import)
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual",
        nullable=False,
    )
    
    # Usage count for popularity ranking
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    
    # Relationships
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="aliases",
    )
    
    # Unique constraint: one alias per product
    __table_args__ = (
        Index("idx_alias_lookup", "alias"),
        Index("idx_alias_product", "product_id"),
    )
    
    def __repr__(self) -> str:
        return f"<ProductAlias {self.alias} -> {self.product_id}>"
