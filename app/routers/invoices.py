"""Invoices router."""

import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.invoice import Invoice, InvoiceItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invoices", tags=["Invoices"])


class InvoiceResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_number: str
    order_id: str
    customer_id: str
    status: str
    subtotal: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_tax: float
    total_amount: float
    amount_paid: float
    amount_due: float
    pdf_url: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[InvoiceResponse])
async def list_invoices(
    tenant_id: str = Query(...),
    customer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if customer_id:
        query = query.where(Invoice.customer_id == customer_id)
    if status:
        query = query.where(Invoice.status == status)
    query = query.order_by(Invoice.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.tenant_id == tenant_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: str,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Download invoice as PDF."""
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.tenant_id == tenant_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate PDF on demand
    from app.core.pdf_generator import (
        generate_invoice_pdf,
        InvoiceData,
        InvoiceLineItem,
    )
    from decimal import Decimal
    from datetime import date

    # Fetch items
    items_result = await db.execute(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
    )
    items_db = items_result.scalars().all()

    line_items = [
        InvoiceLineItem(
            product_name=i.product_name,
            hsn_code=i.hsn_code,
            quantity=i.quantity,
            unit=i.unit,
            unit_price=Decimal(str(i.unit_price)),
            subtotal=Decimal(str(i.subtotal)),
            cgst_rate=Decimal(str(i.cgst_rate)),
            sgst_rate=Decimal(str(i.sgst_rate)),
            igst_rate=Decimal(str(i.igst_rate)),
            cgst_amount=Decimal(str(i.cgst_amount)),
            sgst_amount=Decimal(str(i.sgst_amount)),
            igst_amount=Decimal(str(i.igst_amount)),
            total_price=Decimal(str(i.total_price)),
        )
        for i in items_db
    ]

    from app.models.customer import Customer
    cust_result = await db.execute(
        select(Customer).where(Customer.id == invoice.customer_id)
    )
    customer = cust_result.scalar_one_or_none()

    inv_data = InvoiceData(
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        seller_name="Your Business",
        seller_address="",
        seller_gstin=invoice.seller_gstin or "",
        seller_state=invoice.place_of_supply or "",
        buyer_name=customer.name if customer else "Customer",
        buyer_address=customer.address if customer else "",
        buyer_gstin=invoice.buyer_gstin,
        buyer_state=customer.state_code if customer else "",
        items=line_items,
        subtotal=Decimal(str(invoice.subtotal)),
        cgst_amount=Decimal(str(invoice.cgst_amount)),
        sgst_amount=Decimal(str(invoice.sgst_amount)),
        igst_amount=Decimal(str(invoice.igst_amount)),
        total_tax=Decimal(str(invoice.total_tax)),
        total_amount=Decimal(str(invoice.total_amount)),
        amount_paid=Decimal(str(invoice.amount_paid)),
        amount_due=Decimal(str(invoice.amount_due)),
        is_inter_state=invoice.igst_amount > 0,
    )

    pdf_bytes = generate_invoice_pdf(inv_data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{invoice.invoice_number}.pdf"'
        },
    )
