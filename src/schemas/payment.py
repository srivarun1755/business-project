"""Payment schemas."""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from src.models.payment import PaymentMethod, PaymentStatus, ReminderStatus


class PaymentCreate(BaseModel):
    """Schema for creating a payment."""
    customer_id: str
    invoice_id: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    payment_date: date
    transaction_reference: Optional[str] = None
    notes: Optional[str] = None


class PaymentResponse(BaseModel):
    """Payment response schema."""
    id: str
    customer_id: str
    invoice_id: Optional[str]
    amount: Decimal
    payment_method: PaymentMethod
    status: PaymentStatus
    transaction_reference: Optional[str]
    payment_date: date
    notes: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class PaymentListResponse(BaseModel):
    """Payment list response."""
    items: List[PaymentResponse]
    total: int
    page: int
    page_size: int


class PaymentReminderResponse(BaseModel):
    """Payment reminder response schema."""
    id: str
    customer_id: str
    invoice_id: str
    reminder_date: date
    amount_due: Decimal
    days_overdue: int
    status: ReminderStatus
    message: Optional[str]
    sent_at: Optional[datetime]
    delivery_status: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class CreditLedgerEntryResponse(BaseModel):
    """Credit ledger entry response."""
    id: str
    customer_id: str
    transaction_type: str
    amount: Decimal
    balance_after: Decimal
    reference_type: Optional[str]
    reference_id: Optional[str]
    description: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class CustomerCreditSummary(BaseModel):
    """Customer credit summary."""
    customer_id: str
    customer_name: str
    credit_limit: Decimal
    credit_balance: Decimal
    available_credit: Decimal
    total_invoiced: Decimal
    total_paid: Decimal
    overdue_amount: Decimal
