"""Order schemas."""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from src.models.order import OrderStatus, OrderSource


class ParsedOrderItem(BaseModel):
    """Item parsed from natural language order."""
    product: str = Field(..., description="Product name/identifier")
    quantity: Decimal = Field(..., ge=0, description="Quantity ordered")
    unit: str = Field(default="piece", description="Unit of measurement")
    price: Optional[Decimal] = Field(None, ge=0, description="Unit price if specified")


class ParsedOrder(BaseModel):
    """Order parsed from natural language input."""
    customer: Optional[str] = Field(None, description="Customer name if mentioned")
    items: List[ParsedOrderItem] = Field(default_factory=list)
    total_price: Optional[Decimal] = Field(None, ge=0, description="Total if mentioned")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer": "Ramesh",
                "items": [
                    {"product": "basmati rice", "quantity": 2, "unit": "bora"}
                ],
                "total_price": 2800
            }
        }


class OrderItemCreate(BaseModel):
    """Schema for creating an order item."""
    product_id: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field(default="piece")
    unit_price: Decimal = Field(..., ge=0)


class OrderItemResponse(BaseModel):
    """Order item response schema."""
    id: str
    product_id: str
    original_product_name: Optional[str]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total_price: Decimal
    gst_rate: Decimal
    tax_amount: Decimal
    hsn_code: Optional[str]
    
    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    """Schema for creating an order."""
    customer_id: str
    items: List[OrderItemCreate]
    source: OrderSource = OrderSource.API
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class OrderCreateFromMessage(BaseModel):
    """Schema for creating order from WhatsApp message."""
    customer_phone: str
    message: str
    source: OrderSource = OrderSource.WHATSAPP_TEXT
    idempotency_key: Optional[str] = None


class OrderUpdate(BaseModel):
    """Schema for updating an order."""
    status: Optional[OrderStatus] = None
    notes: Optional[str] = None
    discount_amount: Optional[Decimal] = Field(None, ge=0)


class OrderResponse(BaseModel):
    """Order response schema."""
    id: str
    order_number: str
    customer_id: str
    status: OrderStatus
    source: OrderSource
    raw_message: Optional[str]
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    items: List[OrderItemResponse]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
    
    @property
    def balance_due(self) -> Decimal:
        return self.total_amount - self.paid_amount


class OrderListResponse(BaseModel):
    """Order list response."""
    items: List[OrderResponse]
    total: int
    page: int
    page_size: int


class OrderSummary(BaseModel):
    """Order summary for dashboards."""
    total_orders: int
    pending_orders: int
    total_revenue: Decimal
    total_outstanding: Decimal
