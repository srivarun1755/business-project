"""Product schemas."""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ProductAliasBase(BaseModel):
    """Base product alias schema."""
    alias: str = Field(..., min_length=1, max_length=255)
    confidence: Decimal = Field(default=Decimal("1.00"), ge=0, le=1)
    source: str = Field(default="manual", max_length=50)


class ProductAliasCreate(ProductAliasBase):
    """Schema for creating a product alias."""
    pass


class ProductAliasResponse(ProductAliasBase):
    """Product alias response schema."""
    id: str
    product_id: str
    usage_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class ProductCategoryBase(BaseModel):
    """Base product category schema."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    hsn_code: Optional[str] = Field(None, max_length=8)
    gst_rate: Decimal = Field(default=Decimal("18.00"), ge=0, le=100)


class ProductCategoryCreate(ProductCategoryBase):
    """Schema for creating a category."""
    pass


class ProductCategoryResponse(ProductCategoryBase):
    """Product category response schema."""
    id: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    """Base product schema."""
    name: str = Field(..., min_length=1, max_length=255)
    canonical_name: str = Field(..., min_length=1, max_length=255)
    sku: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    base_price: Decimal = Field(..., ge=0)
    unit: str = Field(default="piece", max_length=50)
    hsn_code: Optional[str] = Field(None, max_length=8)
    gst_rate: Decimal = Field(default=Decimal("18.00"), ge=0, le=100)


class ProductCreate(ProductBase):
    """Schema for creating a product."""
    category_id: Optional[str] = None
    aliases: Optional[List[str]] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    """Schema for updating a product."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    base_price: Optional[Decimal] = Field(None, ge=0)
    unit: Optional[str] = Field(None, max_length=50)
    hsn_code: Optional[str] = Field(None, max_length=8)
    gst_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    category_id: Optional[str] = None
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """Product response schema."""
    id: str
    category_id: Optional[str]
    is_active: bool
    aliases: List[ProductAliasResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """Product list response."""
    items: List[ProductResponse]
    total: int
    page: int
    page_size: int


# Canonicalization schemas
class ProductMatchResult(BaseModel):
    """Result of product canonicalization."""
    product_id: str
    canonical_name: str
    matched_alias: str
    confidence: float = Field(ge=0, le=1)
    match_type: str  # exact, fuzzy, ai


class ProductMatchRequest(BaseModel):
    """Request for product matching."""
    query: str = Field(..., min_length=1, max_length=255)
    
    
class BulkAliasUpload(BaseModel):
    """Bulk alias upload request."""
    aliases: List[dict]  # List of {alias: str, product_canonical_name: str}
