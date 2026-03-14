"""Orders API endpoints."""
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_inventory_service, get_canonicalization_service
from src.models.order import Order, OrderItem, OrderStatus, OrderSource
from src.models.customer import Customer
from src.models.product import Product
from src.schemas.order import (
    OrderCreate, OrderUpdate, OrderResponse, OrderListResponse,
    OrderCreateFromMessage, OrderSummary
)
from src.services.inventory import InventoryService
from src.services.canonicalization import ProductCanonicalizationService

router = APIRouter()


@router.get("/", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[OrderStatus] = None,
    customer_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List orders with pagination and filters."""
    query = select(Order).order_by(Order.created_at.desc())
    
    if status:
        query = query.where(Order.status == status)
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    
    # Count total
    count_query = select(func.count(Order.id))
    if status:
        count_query = count_query.where(Order.status == status)
    if customer_id:
        count_query = count_query.where(Order.customer_id == customer_id)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    orders = result.scalars().all()
    
    return OrderListResponse(
        items=[OrderResponse.model_validate(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get order by ID."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return OrderResponse.model_validate(order)


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """
    Create a new order.
    
    All pricing calculations are deterministic.
    """
    # Verify customer exists
    customer = await db.get(Customer, order_data.customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    # Generate order number
    from datetime import datetime
    today = datetime.now()
    prefix = today.strftime("ORD%Y%m%d")
    count_query = select(func.count(Order.id)).where(
        Order.order_number.like(f"{prefix}%")
    )
    count_result = await db.execute(count_query)
    count = count_result.scalar() or 0
    order_number = f"{prefix}{count + 1:04d}"
    
    # Create order
    order = Order(
        order_number=order_number,
        customer_id=order_data.customer_id,
        status=OrderStatus.PENDING,
        source=order_data.source,
        notes=order_data.notes,
        idempotency_key=order_data.idempotency_key,
    )
    db.add(order)
    await db.flush()
    
    # Create order items
    for item_data in order_data.items:
        product = await db.get(Product, item_data.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {item_data.product_id} not found"
            )
        
        # Check inventory
        available = await inventory.check_availability(
            item_data.product_id,
            item_data.quantity
        )
        if not available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for {product.name}"
            )
        
        order_item = OrderItem(
            order_id=order.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
            unit=item_data.unit,
            unit_price=item_data.unit_price,
            gst_rate=product.gst_rate,
            hsn_code=product.hsn_code,
            total_price=Decimal("0"),
            tax_amount=Decimal("0"),
        )
        
        # Deterministic calculation
        order_item.calculate_totals()
        
        db.add(order_item)
        
        # Reserve stock
        await inventory.reserve_stock(
            item_data.product_id,
            item_data.quantity,
            order.id
        )
    
    await db.flush()
    await db.refresh(order)
    
    # Calculate order totals
    order.calculate_totals()
    
    await db.flush()
    await db.refresh(order)
    
    return OrderResponse.model_validate(order)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: str,
    order_data: OrderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update order status or details."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order_data.status:
        order.status = order_data.status
    if order_data.notes is not None:
        order.notes = order_data.notes
    if order_data.discount_amount is not None:
        order.discount_amount = order_data.discount_amount
        order.calculate_totals()
    
    await db.flush()
    await db.refresh(order)
    
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/confirm", response_model=OrderResponse)
async def confirm_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """
    Confirm an order.
    
    Changes status from PENDING to CONFIRMED.
    Deducts stock from inventory.
    """
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm order with status {order.status}"
        )
    
    # Deduct stock for each item
    for item in order.items:
        await inventory.deduct_stock(
            item.product_id,
            item.quantity,
            order.id
        )
    
    order.status = OrderStatus.CONFIRMED
    await db.flush()
    await db.refresh(order)
    
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    inventory: InventoryService = Depends(get_inventory_service),
):
    """
    Cancel an order.
    
    Releases reserved stock back to inventory.
    """
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    if order.status in [OrderStatus.DELIVERED, OrderStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel order with status {order.status}"
        )
    
    # Release reserved stock
    for item in order.items:
        await inventory.release_reservation(
            item.product_id,
            item.quantity,
            order.id
        )
    
    order.status = OrderStatus.CANCELLED
    await db.flush()
    await db.refresh(order)
    
    return OrderResponse.model_validate(order)


@router.get("/summary/stats", response_model=OrderSummary)
async def get_order_summary(
    db: AsyncSession = Depends(get_db),
):
    """Get order statistics summary."""
    # Total orders
    total_query = select(func.count(Order.id))
    total_result = await db.execute(total_query)
    total_orders = total_result.scalar() or 0
    
    # Pending orders
    pending_query = select(func.count(Order.id)).where(
        Order.status == OrderStatus.PENDING
    )
    pending_result = await db.execute(pending_query)
    pending_orders = pending_result.scalar() or 0
    
    # Total revenue (completed orders)
    revenue_query = select(func.sum(Order.total_amount)).where(
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED])
    )
    revenue_result = await db.execute(revenue_query)
    total_revenue = revenue_result.scalar() or Decimal("0")
    
    # Total outstanding
    outstanding_query = select(
        func.sum(Order.total_amount - Order.paid_amount)
    ).where(
        Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.DELIVERED]),
        Order.paid_amount < Order.total_amount
    )
    outstanding_result = await db.execute(outstanding_query)
    total_outstanding = outstanding_result.scalar() or Decimal("0")
    
    return OrderSummary(
        total_orders=total_orders,
        pending_orders=pending_orders,
        total_revenue=total_revenue,
        total_outstanding=total_outstanding,
    )
