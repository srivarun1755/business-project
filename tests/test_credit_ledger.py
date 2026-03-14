"""
Tests for the Credit Ledger Service.
All financial logic must be deterministic. No AI involved.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal

from app.services.credit_ledger_service import CreditLedgerService, CreditCheckResult
from app.models.credit_ledger import LedgerEntryType
from app.models.invoice import InvoiceStatus


def make_customer(
    *,
    id="cust-001",
    tenant_id="tenant-001",
    name="Test Customer",
    phone="9999999999",
    credit_limit=10000.0,
    current_balance=0.0,
):
    return SimpleNamespace(
        id=id,
        tenant_id=tenant_id,
        name=name,
        phone=phone,
        credit_limit=credit_limit,
        current_balance=current_balance,
    )


def make_invoice(
    *,
    id="inv-001",
    tenant_id="tenant-001",
    customer_id="cust-001",
    total_amount=1000.0,
    amount_due=1000.0,
    amount_paid=0.0,
    status=InvoiceStatus.ISSUED,
    created_at=None,
):
    from datetime import datetime, timezone, date
    return SimpleNamespace(
        id=id,
        tenant_id=tenant_id,
        customer_id=customer_id,
        invoice_number=f"INV-{id}",
        order_id="order-001",
        status=status,
        invoice_date=date.today(),
        subtotal=total_amount,
        total_amount=total_amount,
        amount_due=amount_due,
        amount_paid=amount_paid,
        cgst_amount=0.0,
        sgst_amount=0.0,
        igst_amount=0.0,
        total_tax=0.0,
        created_at=created_at or datetime.now(timezone.utc),
    )


def _make_scalar_result(value):
    """Return an execute-result mock whose scalar_one_or_none / scalar_one returns value."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalar_one = MagicMock(return_value=value)
    return r


def _make_scalars_result(values):
    """Return an execute-result mock whose .scalars() returns a list."""
    r = MagicMock()
    r.scalars = MagicMock(return_value=values)
    return r


def _make_db(*results):
    """Build a db mock with pre-configured execute side_effect and sync add()."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()  # session.add() is synchronous in SQLAlchemy
    return db


class TestCreditCheck:
    @pytest.mark.asyncio
    async def test_credit_allowed_within_limit(self):
        customer = make_customer(credit_limit=10000, current_balance=2000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.check_credit("tenant-001", "cust-001", 5000.0)

        assert result.allowed is True
        assert result.available_credit == 8000.0

    @pytest.mark.asyncio
    async def test_credit_blocked_over_limit(self):
        customer = make_customer(credit_limit=10000, current_balance=8000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.check_credit("tenant-001", "cust-001", 5000.0)

        assert result.allowed is False
        assert "Credit limit exceeded" in result.message

    @pytest.mark.asyncio
    async def test_credit_exactly_at_limit(self):
        """Order that exactly fills the credit limit should be allowed."""
        customer = make_customer(credit_limit=10000, current_balance=5000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.check_credit("tenant-001", "cust-001", 5000.0)

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_credit_customer_not_found(self):
        db = _make_db(_make_scalar_result(None))

        svc = CreditLedgerService(db)
        result = await svc.check_credit("tenant-001", "missing-cust", 1000.0)

        assert result.allowed is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_zero_balance_customer_allowed(self):
        customer = make_customer(credit_limit=50000, current_balance=0)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.check_credit("tenant-001", "cust-001", 25000.0)

        assert result.allowed is True


class TestRecordInvoiceCreated:
    @pytest.mark.asyncio
    async def test_increases_customer_balance(self):
        customer = make_customer(current_balance=1000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.record_invoice_created(
            "tenant-001", "cust-001", "inv-001", 2000.0
        )

        assert customer.current_balance == 3000.0
        assert result.amount == 2000.0
        assert result.balance_after == 3000.0
        assert result.entry_type == LedgerEntryType.INVOICE_CREATED
        db.add.assert_called_once()


class TestRecordPayment:
    @pytest.mark.asyncio
    async def test_payment_reduces_balance(self):
        customer = make_customer(current_balance=5000)
        invoice = make_invoice(total_amount=5000, amount_due=5000)

        db = _make_db(_make_scalar_result(customer), _make_scalars_result([invoice]))

        svc = CreditLedgerService(db)
        entries = await svc.record_payment(
            "tenant-001", "cust-001", "pay-001", 5000.0
        )

        assert customer.current_balance == 0.0
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.amount_due == 0.0
        assert len(entries) == 1
        assert entries[0].amount == -5000.0

    @pytest.mark.asyncio
    async def test_partial_payment_updates_invoice_status(self):
        customer = make_customer(current_balance=5000)
        invoice = make_invoice(total_amount=5000, amount_due=5000)

        db = _make_db(_make_scalar_result(customer), _make_scalars_result([invoice]))

        svc = CreditLedgerService(db)
        entries = await svc.record_payment(
            "tenant-001", "cust-001", "pay-001", 2000.0
        )

        assert invoice.status == InvoiceStatus.PARTIALLY_PAID
        assert invoice.amount_due == pytest.approx(3000.0)
        assert invoice.amount_paid == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_fifo_settlement_oldest_invoice_first(self):
        """Payment should settle the oldest invoice first (FIFO)."""
        from datetime import datetime, timezone, timedelta

        customer = make_customer(current_balance=8000)

        now = datetime.now(timezone.utc)
        old_invoice = make_invoice(
            id="inv-old",
            total_amount=3000,
            amount_due=3000,
            created_at=now - timedelta(days=10),
        )
        new_invoice = make_invoice(
            id="inv-new",
            total_amount=5000,
            amount_due=5000,
            created_at=now - timedelta(days=1),
        )

        db = _make_db(
            _make_scalar_result(customer),
            _make_scalars_result([old_invoice, new_invoice]),
        )

        svc = CreditLedgerService(db)
        await svc.record_payment(
            "tenant-001", "cust-001", "pay-001", 4000.0
        )

        # Old invoice (3000) fully paid, new invoice (5000) partially paid (1000 applied)
        assert old_invoice.status == InvoiceStatus.PAID
        assert old_invoice.amount_due == 0.0
        assert new_invoice.status == InvoiceStatus.PARTIALLY_PAID
        assert new_invoice.amount_due == pytest.approx(4000.0)  # 5000 - 1000


class TestAdjustCredit:
    @pytest.mark.asyncio
    async def test_positive_adjustment_increases_balance(self):
        customer = make_customer(current_balance=1000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.adjust_credit("tenant-001", "cust-001", 500.0, "adjustment")

        assert customer.current_balance == 1500.0
        assert result.amount == 500.0

    @pytest.mark.asyncio
    async def test_negative_adjustment_decreases_balance(self):
        customer = make_customer(current_balance=1000)
        db = _make_db(_make_scalar_result(customer))

        svc = CreditLedgerService(db)
        result = await svc.adjust_credit("tenant-001", "cust-001", -300.0, "credit note")

        assert customer.current_balance == 700.0
        assert result.amount == -300.0
