"""
Credit Ledger Service
=====================
Manages customer credit limits and outstanding balances.

Rules:
- Block order if: current_balance + invoice_amount > credit_limit
- Record double-entry ledger entries for audit trail
- FIFO invoice settlement for partial payments

Complexity: O(1) credit check, O(k) FIFO settlement (k = open invoices).
AI is never used for financial calculations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, asc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.credit_ledger import CreditLedger, LedgerEntryType
from app.models.invoice import Invoice, InvoiceStatus

logger = logging.getLogger(__name__)


@dataclass
class CreditCheckResult:
    allowed: bool
    customer_id: str
    credit_limit: float
    current_balance: float
    invoice_amount: float
    available_credit: float
    message: str


@dataclass
class LedgerEntry:
    customer_id: str
    entry_type: LedgerEntryType
    amount: float
    balance_after: float
    reference_id: Optional[str]
    notes: Optional[str]


class CreditLedgerService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check_credit(
        self, tenant_id: str, customer_id: str, invoice_amount: float
    ) -> CreditCheckResult:
        """
        O(1) credit limit check using indexed customer balance.

        Returns CreditCheckResult.allowed = False if the order would
        exceed the customer's credit limit.
        """
        result = await self._db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
        customer = result.scalar_one_or_none()

        if customer is None:
            return CreditCheckResult(
                allowed=False,
                customer_id=customer_id,
                credit_limit=0,
                current_balance=0,
                invoice_amount=invoice_amount,
                available_credit=0,
                message="Customer not found",
            )

        available_credit = customer.credit_limit - customer.current_balance
        would_exceed = (customer.current_balance + invoice_amount) > customer.credit_limit

        return CreditCheckResult(
            allowed=not would_exceed,
            customer_id=customer_id,
            credit_limit=customer.credit_limit,
            current_balance=customer.current_balance,
            invoice_amount=invoice_amount,
            available_credit=available_credit,
            message=(
                "Order approved"
                if not would_exceed
                else f"Credit limit exceeded: balance={customer.current_balance:.2f}, "
                     f"limit={customer.credit_limit:.2f}, "
                     f"invoice={invoice_amount:.2f}"
            ),
        )

    async def record_invoice_created(
        self,
        tenant_id: str,
        customer_id: str,
        invoice_id: str,
        amount: float,
    ) -> LedgerEntry:
        """
        Record an INVOICE_CREATED ledger entry and update customer balance.
        Positive amount = customer owes money.
        """
        result = await self._db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            ).with_for_update()
        )
        customer = result.scalar_one()
        customer.current_balance += amount

        entry = CreditLedger(
            tenant_id=tenant_id,
            customer_id=customer_id,
            entry_type=LedgerEntryType.INVOICE_CREATED,
            reference_id=invoice_id,
            amount=amount,
            balance_after=customer.current_balance,
            notes=f"Invoice {invoice_id} created",
        )
        self._db.add(entry)

        return LedgerEntry(
            customer_id=customer_id,
            entry_type=LedgerEntryType.INVOICE_CREATED,
            amount=amount,
            balance_after=customer.current_balance,
            reference_id=invoice_id,
            notes=entry.notes,
        )

    async def record_payment(
        self,
        tenant_id: str,
        customer_id: str,
        payment_id: str,
        amount: float,
    ) -> list[LedgerEntry]:
        """
        Apply payment using FIFO invoice settlement.

        Oldest open invoices are settled first.
        Complexity: O(k) where k = number of open invoices (typically small).
        """
        result = await self._db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            ).with_for_update()
        )
        customer = result.scalar_one()

        remaining = amount
        entries: list[LedgerEntry] = []

        # FIFO: fetch open invoices ordered by creation date (oldest first)
        invoices_result = await self._db.execute(
            select(Invoice)
            .where(
                Invoice.customer_id == customer_id,
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_([
                    InvoiceStatus.ISSUED,
                    InvoiceStatus.PARTIALLY_PAID,
                ]),
            )
            .order_by(asc(Invoice.created_at))
            .with_for_update()
        )
        open_invoices = list(invoices_result.scalars())

        for invoice in open_invoices:
            if remaining <= 0:
                break

            apply_amount = min(remaining, invoice.amount_due)
            invoice.amount_paid += apply_amount
            invoice.amount_due -= apply_amount
            remaining -= apply_amount

            if invoice.amount_due <= 0.01:  # Treat near-zero as fully paid
                invoice.amount_due = 0
                invoice.status = InvoiceStatus.PAID
            else:
                invoice.status = InvoiceStatus.PARTIALLY_PAID

        # Update customer balance (negative = reduce outstanding)
        settled_amount = amount - remaining
        customer.current_balance = max(0, customer.current_balance - settled_amount)

        entry = CreditLedger(
            tenant_id=tenant_id,
            customer_id=customer_id,
            entry_type=LedgerEntryType.PAYMENT_RECEIVED,
            reference_id=payment_id,
            amount=-settled_amount,
            balance_after=customer.current_balance,
            notes=f"Payment {payment_id} applied (FIFO)",
        )
        self._db.add(entry)

        entries.append(
            LedgerEntry(
                customer_id=customer_id,
                entry_type=LedgerEntryType.PAYMENT_RECEIVED,
                amount=-settled_amount,
                balance_after=customer.current_balance,
                reference_id=payment_id,
                notes=entry.notes,
            )
        )

        return entries

    async def adjust_credit(
        self,
        tenant_id: str,
        customer_id: str,
        amount: float,
        notes: str = "",
    ) -> LedgerEntry:
        """Manual credit adjustment (positive = increase balance, negative = decrease)."""
        result = await self._db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            ).with_for_update()
        )
        customer = result.scalar_one()
        customer.current_balance += amount

        entry = CreditLedger(
            tenant_id=tenant_id,
            customer_id=customer_id,
            entry_type=LedgerEntryType.CREDIT_ADJUSTMENT,
            amount=amount,
            balance_after=customer.current_balance,
            notes=notes or "Manual credit adjustment",
        )
        self._db.add(entry)

        return LedgerEntry(
            customer_id=customer_id,
            entry_type=LedgerEntryType.CREDIT_ADJUSTMENT,
            amount=amount,
            balance_after=customer.current_balance,
            reference_id=None,
            notes=entry.notes,
        )
