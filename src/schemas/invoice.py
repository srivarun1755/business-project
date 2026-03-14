"""Invoice schemas."""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from src.models.invoice import InvoiceStatus


class InvoiceItemResponse(BaseModel):
    """Invoice item response schema."""
    id: str
    description: str
    hsn_code: Optional[str]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    
    class Config:
        from_attributes = True


class InvoiceCreate(BaseModel):
    """Schema for creating an invoice."""
    order_id: str
    due_date: date
    notes: Optional[str] = None
    terms: Optional[str] = None


class InvoiceResponse(BaseModel):
    """Invoice response schema."""
    id: str
    invoice_number: str
    order_id: str
    customer_name: str
    customer_gstin: Optional[str]
    customer_address: Optional[str]
    customer_state: Optional[str]
    seller_name: str
    seller_gstin: str
    invoice_date: date
    due_date: date
    status: InvoiceStatus
    subtotal: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    amount_in_words: Optional[str]
    pdf_url: Optional[str]
    items: List[InvoiceItemResponse]
    notes: Optional[str]
    terms: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True
    
    @property
    def total_tax(self) -> Decimal:
        """Total GST amount."""
        return self.cgst_amount + self.sgst_amount + self.igst_amount


class InvoiceListResponse(BaseModel):
    """Invoice list response."""
    items: List[InvoiceResponse]
    total: int
    page: int
    page_size: int


class InvoiceUpdate(BaseModel):
    """Schema for updating an invoice."""
    status: Optional[InvoiceStatus] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
