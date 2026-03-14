"""Invoices API endpoints."""
from typing import Optional, List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_invoice_service
from src.models.invoice import Invoice, InvoiceStatus
from src.models.order import Order
from src.schemas.invoice import (
    InvoiceCreate, InvoiceUpdate, InvoiceResponse, InvoiceListResponse
)
from src.services.invoice import InvoiceService

router = APIRouter()


@router.get("/", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[InvoiceStatus] = None,
    db: AsyncSession = Depends(get_db),
):
    """List invoices with pagination."""
    query = select(Invoice).order_by(Invoice.invoice_date.desc())
    
    if status:
        query = query.where(Invoice.status == status)
    
    # Count total
    count_query = select(func.count(Invoice.id))
    if status:
        count_query = count_query.where(Invoice.status == status)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    invoices = result.scalars().all()
    
    return InvoiceListResponse(
        items=[InvoiceResponse.model_validate(i) for i in invoices],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get invoice by ID."""
    invoice = await db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    return InvoiceResponse.model_validate(invoice)


@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    data: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    invoice_service: InvoiceService = Depends(get_invoice_service),
):
    """
    Create a new invoice from an order.
    
    All tax calculations are deterministic (GST compliant).
    """
    # Get order
    order = await db.get(Order, data.order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    # Check if invoice already exists
    existing = await invoice_service.get_invoice_by_order(data.order_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice already exists for this order"
        )
    
    # Calculate due days from dates
    if data.due_date:
        due_days = (data.due_date - date.today()).days
    else:
        due_days = 30
    
    invoice = await invoice_service.create_invoice(
        order=order,
        due_days=due_days,
        notes=data.notes,
        terms=data.terms,
    )
    
    return InvoiceResponse.model_validate(invoice)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: str,
    data: InvoiceUpdate,
    invoice_service: InvoiceService = Depends(get_invoice_service),
):
    """Update invoice status or details."""
    try:
        if data.status:
            invoice = await invoice_service.update_invoice_status(
                invoice_id, data.status
            )
        else:
            invoice = await invoice_service.get_invoice(invoice_id)
            if not invoice:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invoice not found"
                )
        
        if data.notes is not None:
            invoice.notes = data.notes
        if data.terms is not None:
            invoice.terms = data.terms
        
        return InvoiceResponse.model_validate(invoice)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: str,
    invoice_service: InvoiceService = Depends(get_invoice_service),
):
    """
    Generate and download invoice PDF.
    """
    invoice = await invoice_service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    pdf_bytes = invoice_service.generate_pdf(invoice)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={invoice.invoice_number}.pdf"
        }
    )


@router.get("/overdue/list")
async def get_overdue_invoices(
    invoice_service: InvoiceService = Depends(get_invoice_service),
):
    """Get all overdue invoices."""
    invoices = await invoice_service.get_overdue_invoices()
    
    return {
        "overdue_invoices": [
            {
                "invoice_id": i.id,
                "invoice_number": i.invoice_number,
                "customer_name": i.customer_name,
                "total_amount": i.total_amount,
                "due_date": i.due_date.isoformat(),
                "days_overdue": (date.today() - i.due_date).days
            }
            for i in invoices
        ],
        "count": len(invoices)
    }


@router.get("/{invoice_id}/tax-breakdown")
async def get_tax_breakdown(
    invoice_id: str,
    invoice_service: InvoiceService = Depends(get_invoice_service),
):
    """Get detailed tax breakdown for an invoice."""
    invoice = await invoice_service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    breakdown = await invoice_service.calculate_tax_breakdown(
        items=invoice.items,
        is_inter_state=invoice.is_inter_state
    )
    
    return {
        "invoice_number": invoice.invoice_number,
        "is_inter_state": invoice.is_inter_state,
        "breakdown": breakdown
    }
