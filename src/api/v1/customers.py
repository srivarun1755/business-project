"""Customers API endpoints."""
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_credit_ledger_service
from src.models.customer import Customer
from src.schemas.customer import (
    CustomerCreate, CustomerUpdate, CustomerResponse, CustomerListResponse
)
from src.services.credit_ledger import CreditLedgerService

router = APIRouter()


@router.get("/", response_model=CustomerListResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """List customers with pagination."""
    query = select(Customer).order_by(Customer.name)
    
    if active_only:
        query = query.where(Customer.is_active == True)
    
    # Count total
    count_query = select(func.count(Customer.id))
    if active_only:
        count_query = count_query.where(Customer.is_active == True)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    customers = result.scalars().all()
    
    return CustomerListResponse(
        items=[CustomerResponse.model_validate(c) for c in customers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get customer by ID."""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    return CustomerResponse.model_validate(customer)


@router.get("/phone/{phone}", response_model=CustomerResponse)
async def get_customer_by_phone(
    phone: str,
    db: AsyncSession = Depends(get_db),
):
    """Get customer by phone number."""
    # Normalize phone
    if phone.startswith("+91"):
        phone = phone[3:]
    elif phone.startswith("91") and len(phone) > 10:
        phone = phone[2:]
    
    query = select(Customer).where(Customer.phone == phone)
    result = await db.execute(query)
    customer = result.scalar_one_or_none()
    
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    return CustomerResponse.model_validate(customer)


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new customer."""
    # Check for duplicate phone
    query = select(Customer).where(Customer.phone == data.phone)
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer with this phone number already exists"
        )
    
    customer = Customer(
        **data.model_dump()
    )
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    
    return CustomerResponse.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update customer details."""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    
    await db.flush()
    await db.refresh(customer)
    
    return CustomerResponse.model_validate(customer)


@router.get("/{customer_id}/credit")
async def get_customer_credit(
    customer_id: str,
    credit_service: CreditLedgerService = Depends(get_credit_ledger_service),
):
    """Get customer credit summary."""
    summary = await credit_service.get_customer_credit_summary(customer_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    return summary


@router.get("/{customer_id}/credit/history")
async def get_credit_history(
    customer_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credit_service: CreditLedgerService = Depends(get_credit_ledger_service),
):
    """Get customer credit ledger history."""
    entries = await credit_service.get_ledger_history(
        customer_id=customer_id,
        limit=limit,
        offset=offset
    )
    
    return {
        "entries": [
            {
                "id": e.id,
                "type": e.transaction_type.value,
                "amount": e.amount,
                "balance_after": e.balance_after,
                "description": e.description,
                "created_at": e.created_at.isoformat()
            }
            for e in entries
        ],
        "count": len(entries)
    }


@router.get("/outstanding/list")
async def get_customers_with_outstanding(
    min_balance: Decimal = Query(Decimal("0")),
    credit_service: CreditLedgerService = Depends(get_credit_ledger_service),
):
    """Get all customers with outstanding balance."""
    customers = await credit_service.get_customers_with_outstanding(min_balance)
    
    return {
        "customers": [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "credit_balance": c.credit_balance,
                "credit_limit": c.credit_limit,
                "available_credit": c.available_credit
            }
            for c in customers
        ],
        "total_outstanding": sum(c.credit_balance for c in customers)
    }
