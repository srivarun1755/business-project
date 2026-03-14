"""
Payment Tracking Service.

Handles payment recording and reminder scheduling with:
- Payment recording and reconciliation
- Automatic reminder scheduling
- Overdue payment tracking
- All calculations are deterministic (no AI)
"""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime, date, timedelta
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.payment import Payment, PaymentReminder, PaymentMethod, PaymentStatus, ReminderStatus
from src.models.invoice import Invoice, InvoiceStatus
from src.models.customer import Customer
from src.models.order import Order
from src.services.credit_ledger import CreditLedgerService
from src.core.config import settings


class PaymentTrackingService:
    """
    Payment tracking and reminder service.
    
    Features:
    - Record payments against invoices
    - Automatic payment reconciliation
    - Schedule payment reminders
    - Track overdue payments
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.credit_ledger = CreditLedgerService(db_session)
    
    async def record_payment(
        self,
        customer_id: str,
        amount: Decimal,
        payment_method: PaymentMethod,
        payment_date: date,
        invoice_id: Optional[str] = None,
        transaction_reference: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Payment:
        """
        Record a payment from a customer.
        
        If invoice_id is provided, payment is linked to that invoice.
        Otherwise, it's a general payment that can be applied later.
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")
        
        # Create payment record
        payment = Payment(
            customer_id=customer_id,
            invoice_id=invoice_id,
            amount=amount,
            payment_method=payment_method,
            payment_date=payment_date,
            status=PaymentStatus.COMPLETED,
            transaction_reference=transaction_reference,
            notes=notes,
        )
        
        self.db.add(payment)
        await self.db.flush()
        
        # Update credit ledger
        await self.credit_ledger.record_debit(
            customer_id=customer_id,
            amount=amount,
            reference_type="payment",
            reference_id=payment.id,
            description=f"Payment received via {payment_method.value}"
        )
        
        # Update invoice status if linked
        if invoice_id:
            await self._update_invoice_payment_status(invoice_id, amount)
        
        # Update order paid amount if invoice exists
        if invoice_id:
            invoice = await self.db.get(Invoice, invoice_id)
            if invoice:
                order = await self.db.get(Order, invoice.order_id)
                if order:
                    order.paid_amount = order.paid_amount + amount
                    await self.db.flush()
        
        return payment
    
    async def _update_invoice_payment_status(
        self,
        invoice_id: str,
        payment_amount: Decimal
    ) -> None:
        """
        Update invoice status based on payments.
        
        Deterministic status calculation.
        """
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            return
        
        # Calculate total payments for this invoice
        query = select(Payment).where(
            Payment.invoice_id == invoice_id,
            Payment.status == PaymentStatus.COMPLETED
        )
        result = await self.db.execute(query)
        payments = result.scalars().all()
        
        total_paid = sum(p.amount for p in payments)
        
        if total_paid >= invoice.total_amount:
            invoice.status = InvoiceStatus.PAID
        elif total_paid > 0:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        
        await self.db.flush()
    
    async def schedule_reminders(
        self,
        invoice: Invoice
    ) -> List[PaymentReminder]:
        """
        Schedule payment reminders for an invoice.
        
        Uses configured reminder days (e.g., 7, 14, 30 days after due date).
        """
        reminder_days = settings.get_payment_reminder_days()
        reminders = []
        
        for days in reminder_days:
            reminder_date = invoice.due_date + timedelta(days=days)
            
            reminder = PaymentReminder(
                customer_id=invoice.order.customer_id if hasattr(invoice, 'order') else None,
                invoice_id=invoice.id,
                reminder_date=reminder_date,
                amount_due=invoice.total_amount,
                days_overdue=days,
                status=ReminderStatus.SCHEDULED,
            )
            
            # Get customer_id from order if not set
            if not reminder.customer_id:
                order = await self.db.get(Order, invoice.order_id)
                if order:
                    reminder.customer_id = order.customer_id
            
            self.db.add(reminder)
            reminders.append(reminder)
        
        await self.db.flush()
        return reminders
    
    async def get_due_reminders(
        self,
        as_of_date: Optional[date] = None
    ) -> List[PaymentReminder]:
        """
        Get all reminders due for sending.
        """
        if as_of_date is None:
            as_of_date = date.today()
        
        query = select(PaymentReminder).where(
            PaymentReminder.reminder_date <= as_of_date,
            PaymentReminder.status == ReminderStatus.SCHEDULED
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def mark_reminder_sent(
        self,
        reminder_id: str,
        message: str,
        delivery_status: Optional[str] = None
    ) -> PaymentReminder:
        """
        Mark a reminder as sent.
        """
        reminder = await self.db.get(PaymentReminder, reminder_id)
        if not reminder:
            raise ValueError(f"Reminder {reminder_id} not found")
        
        reminder.status = ReminderStatus.SENT
        reminder.message = message
        reminder.sent_at = datetime.utcnow()
        reminder.delivery_status = delivery_status
        
        await self.db.flush()
        return reminder
    
    async def get_overdue_invoices_with_customers(self) -> List[dict]:
        """
        Get overdue invoices with customer details.
        
        Returns list of dicts with invoice and customer info.
        """
        today = date.today()
        
        query = (
            select(Invoice, Customer)
            .join(Order, Invoice.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .where(
                Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID]),
                Invoice.due_date < today
            )
            .order_by(Invoice.due_date)
        )
        
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        overdue_list = []
        for invoice, customer in rows:
            days_overdue = (today - invoice.due_date).days
            
            # Calculate paid amount
            payments_query = select(Payment).where(
                Payment.invoice_id == invoice.id,
                Payment.status == PaymentStatus.COMPLETED
            )
            payments_result = await self.db.execute(payments_query)
            total_paid = sum(p.amount for p in payments_result.scalars().all())
            
            overdue_list.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "customer_id": customer.id,
                "customer_name": customer.name,
                "customer_phone": customer.phone,
                "total_amount": invoice.total_amount,
                "paid_amount": total_paid,
                "outstanding": invoice.total_amount - total_paid,
                "due_date": invoice.due_date,
                "days_overdue": days_overdue,
            })
        
        return overdue_list
    
    async def get_payment_history(
        self,
        customer_id: Optional[str] = None,
        invoice_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Payment]:
        """
        Get payment history.
        """
        query = select(Payment).order_by(Payment.payment_date.desc())
        
        if customer_id:
            query = query.where(Payment.customer_id == customer_id)
        if invoice_id:
            query = query.where(Payment.invoice_id == invoice_id)
        
        query = query.limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_payment_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> dict:
        """
        Get payment summary for a period.
        """
        from sqlalchemy import func
        
        query = select(
            func.count(Payment.id),
            func.sum(Payment.amount),
            Payment.payment_method
        ).where(
            Payment.status == PaymentStatus.COMPLETED
        ).group_by(Payment.payment_method)
        
        if start_date:
            query = query.where(Payment.payment_date >= start_date)
        if end_date:
            query = query.where(Payment.payment_date <= end_date)
        
        result = await self.db.execute(query)
        rows = result.fetchall()
        
        summary = {
            "total_payments": 0,
            "total_amount": Decimal("0"),
            "by_method": {}
        }
        
        for count, amount, method in rows:
            summary["total_payments"] += count
            summary["total_amount"] += amount or Decimal("0")
            summary["by_method"][method.value] = {
                "count": count,
                "amount": amount or Decimal("0")
            }
        
        return summary
    
    async def apply_payment_to_oldest_invoices(
        self,
        customer_id: str,
        amount: Decimal,
        payment_method: PaymentMethod,
        payment_date: date
    ) -> List[Payment]:
        """
        Apply a payment to the oldest unpaid invoices.
        
        FIFO allocation for payments.
        """
        # Get unpaid invoices for customer, oldest first
        query = (
            select(Invoice)
            .join(Order, Invoice.order_id == Order.id)
            .where(
                Order.customer_id == customer_id,
                Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID])
            )
            .order_by(Invoice.invoice_date)
        )
        
        result = await self.db.execute(query)
        invoices = list(result.scalars().all())
        
        payments = []
        remaining = amount
        
        for invoice in invoices:
            if remaining <= 0:
                break
            
            # Calculate outstanding for this invoice
            payments_query = select(Payment).where(
                Payment.invoice_id == invoice.id,
                Payment.status == PaymentStatus.COMPLETED
            )
            payments_result = await self.db.execute(payments_query)
            total_paid = sum(p.amount for p in payments_result.scalars().all())
            
            outstanding = invoice.total_amount - total_paid
            
            if outstanding <= 0:
                continue
            
            # Apply payment
            payment_amount = min(remaining, outstanding)
            
            payment = await self.record_payment(
                customer_id=customer_id,
                amount=payment_amount,
                payment_method=payment_method,
                payment_date=payment_date,
                invoice_id=invoice.id,
            )
            
            payments.append(payment)
            remaining -= payment_amount
        
        return payments
