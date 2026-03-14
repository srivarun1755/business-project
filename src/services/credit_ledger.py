"""
Credit Ledger Service.

Handles customer credit tracking with:
- Double-entry bookkeeping principles
- Atomic balance updates
- Immutable transaction log
- All calculations are deterministic (no AI)
"""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime, date
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.credit import CreditLedgerEntry, TransactionType
from src.models.customer import Customer
from src.models.invoice import Invoice


class CreditLedgerError(Exception):
    """Base exception for credit ledger errors."""
    pass


class InsufficientCreditError(CreditLedgerError):
    """Raised when credit limit exceeded."""
    pass


class CreditLedgerService:
    """
    Credit ledger management service.
    
    Implements double-entry bookkeeping principles:
    - Every credit (increase in customer debt) has a corresponding debit
    - All entries are immutable for audit purposes
    - Running balance is maintained for efficiency
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def get_customer_balance(self, customer_id: str) -> Decimal:
        """
        Get current credit balance for a customer.
        
        Returns the amount owed by the customer.
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            return Decimal("0")
        return customer.credit_balance
    
    async def get_available_credit(self, customer_id: str) -> Decimal:
        """
        Get available credit for a customer.
        
        Available = Credit Limit - Current Balance
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            return Decimal("0")
        return customer.available_credit
    
    async def can_extend_credit(
        self,
        customer_id: str,
        amount: Decimal
    ) -> bool:
        """
        Check if credit can be extended for an order.
        
        Deterministic check against credit limit.
        """
        available = await self.get_available_credit(customer_id)
        return available >= amount
    
    async def record_credit(
        self,
        customer_id: str,
        amount: Decimal,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None
    ) -> CreditLedgerEntry:
        """
        Record a credit transaction (customer owes more).
        
        Used when:
        - Order is placed on credit
        - Invoice is issued
        
        Atomically updates customer balance and creates ledger entry.
        """
        if amount <= 0:
            raise CreditLedgerError("Credit amount must be positive")
        
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            raise CreditLedgerError(f"Customer {customer_id} not found")
        
        # Check credit limit
        if customer.credit_balance + amount > customer.credit_limit:
            raise InsufficientCreditError(
                f"Credit limit exceeded. Available: {customer.available_credit}, "
                f"Requested: {amount}"
            )
        
        # Update customer balance
        new_balance = customer.credit_balance + amount
        customer.credit_balance = new_balance
        
        # Create ledger entry
        entry = CreditLedgerEntry(
            customer_id=customer_id,
            transaction_type=TransactionType.CREDIT,
            amount=amount,
            balance_after=new_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description or f"Credit for {reference_type} {reference_id}",
        )
        
        self.db.add(entry)
        await self.db.flush()
        
        return entry
    
    async def record_debit(
        self,
        customer_id: str,
        amount: Decimal,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None
    ) -> CreditLedgerEntry:
        """
        Record a debit transaction (customer owes less).
        
        Used when:
        - Payment is received
        
        Atomically updates customer balance and creates ledger entry.
        """
        if amount <= 0:
            raise CreditLedgerError("Debit amount must be positive")
        
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            raise CreditLedgerError(f"Customer {customer_id} not found")
        
        # Update customer balance (can go negative if overpaid)
        new_balance = customer.credit_balance - amount
        customer.credit_balance = new_balance
        
        # Create ledger entry
        entry = CreditLedgerEntry(
            customer_id=customer_id,
            transaction_type=TransactionType.DEBIT,
            amount=amount,
            balance_after=new_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description or f"Payment for {reference_type} {reference_id}",
        )
        
        self.db.add(entry)
        await self.db.flush()
        
        return entry
    
    async def record_adjustment(
        self,
        customer_id: str,
        amount: Decimal,
        is_credit: bool,
        reason: str,
        notes: Optional[str] = None
    ) -> CreditLedgerEntry:
        """
        Record a manual adjustment.
        
        Used for:
        - Corrections
        - Write-offs
        - Goodwill adjustments
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            raise CreditLedgerError(f"Customer {customer_id} not found")
        
        if is_credit:
            new_balance = customer.credit_balance + abs(amount)
        else:
            new_balance = customer.credit_balance - abs(amount)
        
        customer.credit_balance = new_balance
        
        entry = CreditLedgerEntry(
            customer_id=customer_id,
            transaction_type=TransactionType.ADJUSTMENT,
            amount=abs(amount) if is_credit else -abs(amount),
            balance_after=new_balance,
            reference_type="adjustment",
            reference_id=None,
            description=reason,
            notes=notes,
        )
        
        self.db.add(entry)
        await self.db.flush()
        
        return entry
    
    async def record_refund(
        self,
        customer_id: str,
        amount: Decimal,
        order_id: str,
        description: Optional[str] = None
    ) -> CreditLedgerEntry:
        """
        Record a refund (reduces customer debt).
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            raise CreditLedgerError(f"Customer {customer_id} not found")
        
        new_balance = customer.credit_balance - amount
        customer.credit_balance = new_balance
        
        entry = CreditLedgerEntry(
            customer_id=customer_id,
            transaction_type=TransactionType.REFUND,
            amount=amount,
            balance_after=new_balance,
            reference_type="order",
            reference_id=order_id,
            description=description or f"Refund for order {order_id}",
        )
        
        self.db.add(entry)
        await self.db.flush()
        
        return entry
    
    async def get_ledger_history(
        self,
        customer_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[CreditLedgerEntry]:
        """
        Get credit ledger history for a customer.
        
        Returns entries in reverse chronological order.
        """
        query = (
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.customer_id == customer_id)
            .order_by(CreditLedgerEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_customers_with_outstanding(
        self,
        min_balance: Decimal = Decimal("0")
    ) -> List[Customer]:
        """
        Get all customers with outstanding balance.
        """
        query = (
            select(Customer)
            .where(Customer.credit_balance > min_balance)
            .order_by(Customer.credit_balance.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_total_outstanding(self) -> Decimal:
        """
        Get total outstanding amount across all customers.
        
        Deterministic aggregation.
        """
        query = select(func.sum(Customer.credit_balance))
        result = await self.db.execute(query)
        return result.scalar() or Decimal("0")
    
    async def get_customer_credit_summary(self, customer_id: str) -> dict:
        """
        Get detailed credit summary for a customer.
        """
        customer = await self.db.get(Customer, customer_id)
        if not customer:
            return {}
        
        # Get totals from ledger
        credit_query = select(func.sum(CreditLedgerEntry.amount)).where(
            CreditLedgerEntry.customer_id == customer_id,
            CreditLedgerEntry.transaction_type == TransactionType.CREDIT
        )
        credit_result = await self.db.execute(credit_query)
        total_credit = credit_result.scalar() or Decimal("0")
        
        debit_query = select(func.sum(CreditLedgerEntry.amount)).where(
            CreditLedgerEntry.customer_id == customer_id,
            CreditLedgerEntry.transaction_type == TransactionType.DEBIT
        )
        debit_result = await self.db.execute(debit_query)
        total_debit = debit_result.scalar() or Decimal("0")
        
        return {
            "customer_id": customer_id,
            "customer_name": customer.name,
            "credit_limit": customer.credit_limit,
            "current_balance": customer.credit_balance,
            "available_credit": customer.available_credit,
            "total_invoiced": total_credit,
            "total_paid": total_debit,
            "utilization_percent": (
                (customer.credit_balance / customer.credit_limit * 100)
                if customer.credit_limit > 0 else Decimal("0")
            ),
        }
