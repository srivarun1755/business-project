"""Payments router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.services.credit_ledger_service import CreditLedgerService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["Payments"])


class PaymentCreate(BaseModel):
    tenant_id: str
    customer_id: str
    invoice_id: Optional[str] = None
    amount: float = Field(..., gt=0)
    method: PaymentMethod = PaymentMethod.CASH
    reference_id: Optional[str] = None
    notes: Optional[str] = None


class PaymentResponse(BaseModel):
    id: str
    tenant_id: str
    customer_id: str
    invoice_id: Optional[str] = None
    amount: float
    method: str
    status: str
    reference_id: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[PaymentResponse])
async def list_payments(
    tenant_id: str = Query(...),
    customer_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Payment).where(Payment.tenant_id == tenant_id)
    if customer_id:
        query = query.where(Payment.customer_id == customer_id)
    query = query.order_by(Payment.payment_date.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=PaymentResponse, status_code=201)
async def record_payment(
    body: PaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Record a payment and apply FIFO invoice settlement.
    Updates customer credit balance automatically.
    """
    payment = Payment(
        tenant_id=body.tenant_id,
        customer_id=body.customer_id,
        invoice_id=body.invoice_id,
        amount=body.amount,
        method=body.method,
        status=PaymentStatus.COMPLETED,
        reference_id=body.reference_id,
        notes=body.notes,
    )
    db.add(payment)
    await db.flush()

    # Apply FIFO settlement and update ledger
    credit_svc = CreditLedgerService(db)
    await credit_svc.record_payment(
        body.tenant_id,
        body.customer_id,
        payment.id,
        body.amount,
    )

    return payment
