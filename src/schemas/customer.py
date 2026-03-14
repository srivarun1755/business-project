"""Customer schemas."""
from decimal import Decimal
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re


class CustomerBase(BaseModel):
    """Base customer schema."""
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=10, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    business_name: Optional[str] = Field(None, max_length=255)
    gstin: Optional[str] = Field(None, max_length=15)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    pincode: Optional[str] = Field(None, max_length=10)
    
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate and normalize phone number."""
        # Remove spaces, dashes, and country code prefix
        cleaned = re.sub(r"[\s\-+]", "", v)
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = cleaned[2:]
        if not cleaned.isdigit() or len(cleaned) != 10:
            raise ValueError("Invalid phone number format")
        return cleaned
    
    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, v: Optional[str]) -> Optional[str]:
        """Validate GSTIN format."""
        if v is None:
            return None
        # GSTIN format: 2 digit state code + 10 char PAN + 1 entity code + Z + check digit
        gstin_pattern = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$"
        if not re.match(gstin_pattern, v.upper()):
            raise ValueError("Invalid GSTIN format")
        return v.upper()


class CustomerCreate(CustomerBase):
    """Schema for creating a customer."""
    credit_limit: Decimal = Field(default=Decimal("50000.00"), ge=0)


class CustomerUpdate(BaseModel):
    """Schema for updating a customer."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    business_name: Optional[str] = Field(None, max_length=255)
    gstin: Optional[str] = Field(None, max_length=15)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    pincode: Optional[str] = Field(None, max_length=10)
    credit_limit: Optional[Decimal] = Field(None, ge=0)
    is_active: Optional[bool] = None


class CustomerResponse(CustomerBase):
    """Customer response schema."""
    id: str
    credit_limit: Decimal
    credit_balance: Decimal
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
    
    @property
    def available_credit(self) -> Decimal:
        """Calculate available credit."""
        return self.credit_limit - self.credit_balance


class CustomerListResponse(BaseModel):
    """Customer list response."""
    items: list[CustomerResponse]
    total: int
    page: int
    page_size: int
