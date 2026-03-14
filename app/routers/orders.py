"""Orders router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import Order, OrderStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["Orders"])


class OrderResponse(BaseModel):
    id: str
    tenant_id: str
    customer_id: str
    status: str
    total_amount: float
    raw_text: Optional[str] = None
    whatsapp_message_id: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    tenant_id: str = Query(...),
    customer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List orders for a tenant."""
    query = select(Order).where(Order.tenant_id == tenant_id)
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    if status:
        try:
            query = query.where(Order.status == OrderStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    query = query.limit(limit).order_by(Order.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get order by ID."""
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
