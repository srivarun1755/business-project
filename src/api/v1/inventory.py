"""Inventory API endpoints."""
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from src.api.deps import get_db, get_inventory_service
from src.models.inventory import InventoryItem, InventoryTransaction
from src.models.product import Product
from src.services.inventory import InventoryService

router = APIRouter()


class InventoryItemResponse(BaseModel):
    """Inventory item response."""
    id: str
    product_id: str
    quantity: Decimal
    reserved_quantity: Decimal
    reorder_level: Decimal
    unit: str
    
    class Config:
        from_attributes = True
    
    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity


class StockUpdateRequest(BaseModel):
    """Stock update request."""
    quantity: Decimal = Field(..., gt=0)
    notes: Optional[str] = None


class StockAdjustmentRequest(BaseModel):
    """Stock adjustment request."""
    new_quantity: Decimal = Field(..., ge=0)
    reason: str


class InventoryTransactionResponse(BaseModel):
    """Inventory transaction response."""
    id: str
    transaction_type: str
    quantity: Decimal
    balance_after: Decimal
    reference_type: Optional[str]
    notes: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[InventoryItemResponse])
async def list_inventory(
    low_stock_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """List all inventory items."""
    if low_stock_only:
        items = await inventory.get_low_stock_items()
    else:
        query = select(InventoryItem)
        result = await db.execute(query)
        items = result.scalars().all()
    
    return [InventoryItemResponse.model_validate(item) for item in items]


@router.get("/{product_id}", response_model=InventoryItemResponse)
async def get_inventory(
    product_id: str,
    inventory: InventoryService = Depends(get_inventory_service),
):
    """Get inventory for a specific product."""
    item = await inventory.get_stock_level(product_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found"
        )
    return InventoryItemResponse.model_validate(item)


@router.post("/{product_id}/add", response_model=InventoryItemResponse)
async def add_stock(
    product_id: str,
    data: StockUpdateRequest,
    inventory: InventoryService = Depends(get_inventory_service),
):
    """Add stock to inventory."""
    try:
        item = await inventory.add_stock(
            product_id=product_id,
            quantity=data.quantity,
            notes=data.notes
        )
        return InventoryItemResponse.model_validate(item)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{product_id}/adjust", response_model=InventoryItemResponse)
async def adjust_stock(
    product_id: str,
    data: StockAdjustmentRequest,
    inventory: InventoryService = Depends(get_inventory_service),
):
    """
    Adjust stock to a specific quantity.
    
    Used for stock corrections after physical count.
    """
    try:
        item = await inventory.adjust_stock(
            product_id=product_id,
            new_quantity=data.new_quantity,
            reason=data.reason
        )
        return InventoryItemResponse.model_validate(item)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{product_id}/transactions", response_model=List[InventoryTransactionResponse])
async def get_transactions(
    product_id: str,
    limit: int = Query(50, ge=1, le=200),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """Get transaction history for a product."""
    transactions = await inventory.get_transaction_history(
        product_id=product_id,
        limit=limit
    )
    return [
        InventoryTransactionResponse(
            id=t.id,
            transaction_type=t.transaction_type.value,
            quantity=t.quantity,
            balance_after=t.balance_after,
            reference_type=t.reference_type,
            notes=t.notes,
            created_at=t.created_at.isoformat()
        )
        for t in transactions
    ]


@router.get("/{product_id}/availability")
async def check_availability(
    product_id: str,
    quantity: Decimal = Query(..., gt=0),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """Check if a quantity is available."""
    available = await inventory.check_availability(product_id, quantity)
    current = await inventory.get_available_quantity(product_id)
    
    return {
        "product_id": product_id,
        "requested": quantity,
        "available": current,
        "can_fulfill": available
    }


@router.get("/alerts/low-stock")
async def get_low_stock_alerts(
    inventory: InventoryService = Depends(get_inventory_service),
    db: AsyncSession = Depends(get_db),
):
    """Get all products below reorder level."""
    items = await inventory.get_low_stock_items()
    
    alerts = []
    for item in items:
        product = await db.get(Product, item.product_id)
        alerts.append({
            "product_id": item.product_id,
            "product_name": product.name if product else "Unknown",
            "current_stock": item.quantity,
            "reorder_level": item.reorder_level,
            "deficit": item.reorder_level - item.quantity,
            "unit": item.unit
        })
    
    return {"alerts": alerts, "count": len(alerts)}
