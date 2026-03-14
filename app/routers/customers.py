"""Customers router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.credit_ledger import CreditLedger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["Customers"])


class CustomerCreate(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=10, max_length=20)
    gstin: Optional[str] = Field(None, max_length=15)
    state_code: Optional[str] = Field(None, max_length=2)
    address: Optional[str] = None
    credit_limit: float = Field(default=50000.0, ge=0)


class CustomerResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    phone: str
    gstin: Optional[str] = None
    state_code: Optional[str] = None
    address: Optional[str] = None
    credit_limit: float
    current_balance: float
    is_active: bool

    class Config:
        from_attributes = True


class LedgerEntryResponse(BaseModel):
    id: str
    entry_type: str
    amount: float
    balance_after: float
    reference_id: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[CustomerResponse])
async def list_customers(
    tenant_id: str = Query(...),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Customer)
        .where(Customer.tenant_id == tenant_id, Customer.is_active == True)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    body: CustomerCreate,
    db: AsyncSession = Depends(get_db),
):
    customer = Customer(**body.model_dump())
    db.add(customer)
    await db.flush()
    return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.get("/{customer_id}/ledger", response_model=list[LedgerEntryResponse])
async def get_customer_ledger(
    customer_id: str,
    tenant_id: str = Query(...),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get credit ledger entries for a customer (audit trail)."""
    result = await db.execute(
        select(CreditLedger)
        .where(
            CreditLedger.customer_id == customer_id,
            CreditLedger.tenant_id == tenant_id,
        )
        .order_by(CreditLedger.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
