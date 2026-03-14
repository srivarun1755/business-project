"""Payments API endpoints."""
from typing import Optional, List
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_payment_service, get_notification_service
from src.models.payment import Payment, PaymentReminder, PaymentMethod, PaymentStatus
from src.schemas.payment import (
    PaymentCreate, PaymentResponse, PaymentListResponse,
    PaymentReminderResponse
)
from src.services.payment_tracking import PaymentTrackingService
from src.services.notification import NotificationService

router = APIRouter()


@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    customer_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List payments with pagination."""
    query = select(Payment).order_by(Payment.payment_date.desc())
    
    if customer_id:
        query = query.where(Payment.customer_id == customer_id)
    
    # Count total
    count_query = select(func.count(Payment.id))
    if customer_id:
        count_query = count_query.where(Payment.customer_id == customer_id)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    payments = result.scalars().all()
    
    return PaymentListResponse(
        items=[PaymentResponse.model_validate(p) for p in payments],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get payment by ID."""
    payment = await db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )
    return PaymentResponse.model_validate(payment)


@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    data: PaymentCreate,
    payment_service: PaymentTrackingService = Depends(get_payment_service),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """
    Record a new payment.
    
    Automatically updates credit balance and invoice status.
    """
    try:
        payment = await payment_service.record_payment(
            customer_id=data.customer_id,
            amount=data.amount,
            payment_method=data.payment_method,
            payment_date=data.payment_date,
            invoice_id=data.invoice_id,
            transaction_reference=data.transaction_reference,
            notes=data.notes,
        )
        
        return PaymentResponse.model_validate(payment)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/auto-allocate")
async def auto_allocate_payment(
    customer_id: str,
    amount: Decimal,
    payment_method: PaymentMethod = PaymentMethod.CASH,
    payment_date: date = None,
    payment_service: PaymentTrackingService = Depends(get_payment_service),
):
    """
    Automatically allocate payment to oldest unpaid invoices.
    
    Uses FIFO allocation.
    """
    if payment_date is None:
        payment_date = date.today()
    
    payments = await payment_service.apply_payment_to_oldest_invoices(
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        payment_date=payment_date,
    )
    
    return {
        "payments": [PaymentResponse.model_validate(p) for p in payments],
        "total_allocated": sum(p.amount for p in payments),
        "invoices_paid": len(payments)
    }


@router.get("/summary/report")
async def get_payment_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    payment_service: PaymentTrackingService = Depends(get_payment_service),
):
    """Get payment summary for a period."""
    summary = await payment_service.get_payment_summary(
        start_date=start_date,
        end_date=end_date
    )
    return summary


@router.get("/reminders/due")
async def get_due_reminders(
    payment_service: PaymentTrackingService = Depends(get_payment_service),
):
    """Get all payment reminders due for sending."""
    reminders = await payment_service.get_due_reminders()
    
    return {
        "reminders": [
            PaymentReminderResponse.model_validate(r) for r in reminders
        ],
        "count": len(reminders)
    }


@router.post("/reminders/send-batch")
async def send_reminder_batch(
    payment_service: PaymentTrackingService = Depends(get_payment_service),
    notification_service: NotificationService = Depends(get_notification_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Send all due payment reminders via WhatsApp.
    """
    from src.models.customer import Customer
    from src.models.invoice import Invoice
    
    reminders = await payment_service.get_due_reminders()
    results = []
    
    for reminder in reminders:
        customer = await db.get(Customer, reminder.customer_id)
        invoice = await db.get(Invoice, reminder.invoice_id)
        
        if customer and invoice:
            # Send notification
            result = await notification_service.send_payment_reminder(
                phone=customer.phone,
                customer_name=customer.name,
                invoice_number=invoice.invoice_number,
                amount_due=str(reminder.amount_due),
                due_date=invoice.due_date.isoformat(),
                days_overdue=reminder.days_overdue
            )
            
            # Mark as sent
            if result.success:
                await payment_service.mark_reminder_sent(
                    reminder_id=reminder.id,
                    message=f"Payment reminder for {invoice.invoice_number}",
                    delivery_status="sent"
                )
            
            results.append({
                "reminder_id": reminder.id,
                "customer_name": customer.name,
                "success": result.success,
                "error": result.error
            })
    
    return {
        "sent": len([r for r in results if r["success"]]),
        "failed": len([r for r in results if not r["success"]]),
        "results": results
    }


@router.get("/overdue/report")
async def get_overdue_report(
    payment_service: PaymentTrackingService = Depends(get_payment_service),
):
    """Get detailed overdue payments report."""
    overdue = await payment_service.get_overdue_invoices_with_customers()
    
    total_overdue = sum(item["outstanding"] for item in overdue)
    
    return {
        "overdue_invoices": overdue,
        "count": len(overdue),
        "total_overdue": total_overdue
    }
