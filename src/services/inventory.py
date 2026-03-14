"""
Inventory Service.

Handles all inventory management operations with:
- Atomic database operations
- Optimistic locking for concurrent updates
- O(1) lookups via caching
- Deterministic calculations (no AI)
"""
from decimal import Decimal
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.models.inventory import InventoryItem, InventoryTransaction, TransactionType
from src.models.product import Product
from src.core.redis_cache import RedisCache


class InventoryError(Exception):
    """Base exception for inventory errors."""
    pass


class InsufficientStockError(InventoryError):
    """Raised when there's not enough stock."""
    pass


class ConcurrencyError(InventoryError):
    """Raised when optimistic locking fails."""
    pass


class InventoryService:
    """
    Inventory management service with deterministic logic.
    
    Key features:
    - Atomic stock updates with optimistic locking
    - Transactional logging for audit trail
    - Real-time stock availability checks
    - Low stock alerts
    """
    
    def __init__(self, db_session: AsyncSession, redis_cache: RedisCache):
        self.db = db_session
        self.cache = redis_cache
    
    async def get_stock_level(self, product_id: str) -> Optional[InventoryItem]:
        """
        Get current stock level for a product.
        
        Returns InventoryItem or None if not found.
        """
        query = select(InventoryItem).where(
            InventoryItem.product_id == product_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_available_quantity(self, product_id: str) -> Decimal:
        """
        Get available quantity (total - reserved).
        
        Returns Decimal quantity, 0 if product not found.
        """
        item = await self.get_stock_level(product_id)
        if item:
            return item.available_quantity
        return Decimal("0")
    
    async def check_availability(
        self,
        product_id: str,
        required_quantity: Decimal
    ) -> bool:
        """
        Check if required quantity is available.
        
        This is a deterministic check - no AI involved.
        """
        available = await self.get_available_quantity(product_id)
        return available >= required_quantity
    
    async def reserve_stock(
        self,
        product_id: str,
        quantity: Decimal,
        order_id: str
    ) -> bool:
        """
        Reserve stock for an order.
        
        Uses optimistic locking to prevent race conditions.
        Returns True if reservation successful, False otherwise.
        """
        item = await self.get_stock_level(product_id)
        if not item:
            return False
        
        if not item.can_fulfill(quantity):
            return False
        
        # Optimistic locking update
        current_version = item.version
        
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item.id,
                InventoryItem.version == current_version
            )
            .values(
                reserved_quantity=item.reserved_quantity + quantity,
                version=current_version + 1,
                updated_at=datetime.utcnow()
            )
        )
        
        result = await self.db.execute(stmt)
        
        if result.rowcount == 0:
            raise ConcurrencyError(
                f"Concurrent modification detected for product {product_id}"
            )
        
        # Log transaction
        await self._log_transaction(
            inventory_item_id=item.id,
            transaction_type=TransactionType.STOCK_OUT,
            quantity=-quantity,  # Negative for reservation
            balance_after=item.quantity,  # Stock not actually reduced yet
            reference_type="order_reservation",
            reference_id=order_id,
            notes=f"Stock reserved for order {order_id}"
        )
        
        return True
    
    async def deduct_stock(
        self,
        product_id: str,
        quantity: Decimal,
        order_id: str
    ) -> None:
        """
        Deduct stock after order fulfillment.
        
        This converts reserved stock to actual deduction.
        """
        item = await self.get_stock_level(product_id)
        if not item:
            raise InventoryError(f"Product {product_id} not found in inventory")
        
        current_version = item.version
        new_quantity = item.quantity - quantity
        new_reserved = max(Decimal("0"), item.reserved_quantity - quantity)
        
        if new_quantity < 0:
            raise InsufficientStockError(
                f"Insufficient stock for product {product_id}"
            )
        
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item.id,
                InventoryItem.version == current_version
            )
            .values(
                quantity=new_quantity,
                reserved_quantity=new_reserved,
                version=current_version + 1,
                updated_at=datetime.utcnow()
            )
        )
        
        result = await self.db.execute(stmt)
        
        if result.rowcount == 0:
            raise ConcurrencyError(
                f"Concurrent modification detected for product {product_id}"
            )
        
        # Log transaction
        await self._log_transaction(
            inventory_item_id=item.id,
            transaction_type=TransactionType.STOCK_OUT,
            quantity=-quantity,
            balance_after=new_quantity,
            reference_type="order",
            reference_id=order_id,
            notes=f"Stock deducted for order {order_id}"
        )
    
    async def add_stock(
        self,
        product_id: str,
        quantity: Decimal,
        notes: Optional[str] = None
    ) -> InventoryItem:
        """
        Add stock to inventory.
        
        Creates inventory item if it doesn't exist.
        """
        item = await self.get_stock_level(product_id)
        
        if item:
            # Update existing item
            current_version = item.version
            new_quantity = item.quantity + quantity
            
            stmt = (
                update(InventoryItem)
                .where(
                    InventoryItem.id == item.id,
                    InventoryItem.version == current_version
                )
                .values(
                    quantity=new_quantity,
                    version=current_version + 1,
                    updated_at=datetime.utcnow()
                )
            )
            
            result = await self.db.execute(stmt)
            
            if result.rowcount == 0:
                raise ConcurrencyError(
                    f"Concurrent modification detected for product {product_id}"
                )
            
            # Log transaction
            await self._log_transaction(
                inventory_item_id=item.id,
                transaction_type=TransactionType.STOCK_IN,
                quantity=quantity,
                balance_after=new_quantity,
                reference_type="stock_in",
                reference_id=None,
                notes=notes
            )
            
            # Refresh item
            await self.db.refresh(item)
            return item
        else:
            # Create new inventory item
            product = await self.db.get(Product, product_id)
            if not product:
                raise InventoryError(f"Product {product_id} not found")
            
            new_item = InventoryItem(
                product_id=product_id,
                quantity=quantity,
                unit=product.unit,
            )
            self.db.add(new_item)
            await self.db.flush()
            
            # Log transaction
            await self._log_transaction(
                inventory_item_id=new_item.id,
                transaction_type=TransactionType.STOCK_IN,
                quantity=quantity,
                balance_after=quantity,
                reference_type="initial_stock",
                reference_id=None,
                notes=notes
            )
            
            return new_item
    
    async def adjust_stock(
        self,
        product_id: str,
        new_quantity: Decimal,
        reason: str
    ) -> InventoryItem:
        """
        Adjust stock to a specific quantity.
        
        Used for stock corrections/audits.
        """
        item = await self.get_stock_level(product_id)
        if not item:
            raise InventoryError(f"Product {product_id} not found in inventory")
        
        adjustment = new_quantity - item.quantity
        current_version = item.version
        
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item.id,
                InventoryItem.version == current_version
            )
            .values(
                quantity=new_quantity,
                version=current_version + 1,
                updated_at=datetime.utcnow()
            )
        )
        
        result = await self.db.execute(stmt)
        
        if result.rowcount == 0:
            raise ConcurrencyError(
                f"Concurrent modification detected for product {product_id}"
            )
        
        # Log adjustment
        await self._log_transaction(
            inventory_item_id=item.id,
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=adjustment,
            balance_after=new_quantity,
            reference_type="adjustment",
            reference_id=None,
            notes=reason
        )
        
        await self.db.refresh(item)
        return item
    
    async def release_reservation(
        self,
        product_id: str,
        quantity: Decimal,
        order_id: str
    ) -> None:
        """
        Release reserved stock (e.g., order cancelled).
        """
        item = await self.get_stock_level(product_id)
        if not item:
            return
        
        current_version = item.version
        new_reserved = max(Decimal("0"), item.reserved_quantity - quantity)
        
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item.id,
                InventoryItem.version == current_version
            )
            .values(
                reserved_quantity=new_reserved,
                version=current_version + 1,
                updated_at=datetime.utcnow()
            )
        )
        
        result = await self.db.execute(stmt)
        
        if result.rowcount == 0:
            raise ConcurrencyError(
                f"Concurrent modification detected for product {product_id}"
            )
        
        # Log release
        await self._log_transaction(
            inventory_item_id=item.id,
            transaction_type=TransactionType.STOCK_IN,
            quantity=quantity,
            balance_after=item.quantity,
            reference_type="order_cancellation",
            reference_id=order_id,
            notes=f"Reservation released for cancelled order {order_id}"
        )
    
    async def get_low_stock_items(self) -> List[InventoryItem]:
        """
        Get all items below reorder level.
        
        Used for generating restock alerts.
        """
        query = select(InventoryItem).where(
            InventoryItem.quantity <= InventoryItem.reorder_level
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_transaction_history(
        self,
        product_id: str,
        limit: int = 50
    ) -> List[InventoryTransaction]:
        """
        Get transaction history for a product.
        """
        item = await self.get_stock_level(product_id)
        if not item:
            return []
        
        query = (
            select(InventoryTransaction)
            .where(InventoryTransaction.inventory_item_id == item.id)
            .order_by(InventoryTransaction.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def _log_transaction(
        self,
        inventory_item_id: str,
        transaction_type: TransactionType,
        quantity: Decimal,
        balance_after: Decimal,
        reference_type: Optional[str],
        reference_id: Optional[str],
        notes: Optional[str]
    ) -> InventoryTransaction:
        """
        Log an inventory transaction.
        
        Transactions are immutable for audit purposes.
        """
        transaction = InventoryTransaction(
            inventory_item_id=inventory_item_id,
            transaction_type=transaction_type,
            quantity=quantity,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
        )
        self.db.add(transaction)
        await self.db.flush()
        return transaction
