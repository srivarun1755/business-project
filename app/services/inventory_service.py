"""
Inventory Service
=================
Atomic inventory management using PostgreSQL row-level locking.

All stock operations are wrapped in database transactions with
SELECT ... FOR UPDATE to prevent race conditions at scale.

Complexity: O(1) per operation (indexed product_id lookup).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory

logger = logging.getLogger(__name__)


@dataclass
class StockResult:
    success: bool
    product_id: str
    quantity_before: int
    quantity_after: int
    message: str
    low_stock: bool = False


class InventoryService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_stock(self, tenant_id: str, product_id: str) -> int | None:
        """Return current stock level, or None if product not found."""
        result = await self._db.execute(
            select(Inventory).where(
                Inventory.tenant_id == tenant_id,
                Inventory.product_id == product_id,
            )
        )
        row = result.scalar_one_or_none()
        return row.quantity if row else None

    async def deduct_stock(
        self, tenant_id: str, product_id: str, quantity: int
    ) -> StockResult:
        """
        Atomically deduct stock using row-level lock (SELECT FOR UPDATE).
        Returns StockResult indicating success or failure.

        Complexity: O(1) — indexed lookup + row-level lock.
        """
        # SELECT FOR UPDATE — acquires row-level lock
        result = await self._db.execute(
            select(Inventory)
            .where(
                Inventory.tenant_id == tenant_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()

        if row is None:
            return StockResult(
                success=False,
                product_id=product_id,
                quantity_before=0,
                quantity_after=0,
                message="Product not found in inventory",
            )

        quantity_before = row.quantity

        # Validate stock
        if row.quantity < quantity:
            return StockResult(
                success=False,
                product_id=product_id,
                quantity_before=quantity_before,
                quantity_after=quantity_before,
                message=f"Insufficient stock: available={row.quantity}, requested={quantity}",
            )

        # Deduct quantity
        new_quantity = row.quantity - quantity
        row.quantity = new_quantity

        low_stock = new_quantity <= row.low_stock_threshold

        if low_stock:
            logger.warning(
                "Low stock alert: tenant=%s product=%s quantity=%d threshold=%d",
                tenant_id, product_id, new_quantity, row.low_stock_threshold,
            )

        return StockResult(
            success=True,
            product_id=product_id,
            quantity_before=quantity_before,
            quantity_after=new_quantity,
            message="Stock deducted successfully",
            low_stock=low_stock,
        )

    async def add_stock(
        self, tenant_id: str, product_id: str, quantity: int
    ) -> StockResult:
        """Add stock (e.g., from inventory upload)."""
        result = await self._db.execute(
            select(Inventory)
            .where(
                Inventory.tenant_id == tenant_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()

        if row is None:
            # Create inventory record
            row = Inventory(
                tenant_id=tenant_id,
                product_id=product_id,
                quantity=quantity,
            )
            self._db.add(row)
            return StockResult(
                success=True,
                product_id=product_id,
                quantity_before=0,
                quantity_after=quantity,
                message="Inventory record created",
            )

        quantity_before = row.quantity
        row.quantity += quantity

        return StockResult(
            success=True,
            product_id=product_id,
            quantity_before=quantity_before,
            quantity_after=row.quantity,
            message="Stock added successfully",
        )

    async def set_stock(
        self, tenant_id: str, product_id: str, quantity: int
    ) -> StockResult:
        """Set stock to an absolute value (e.g., from CSV upload)."""
        result = await self._db.execute(
            select(Inventory)
            .where(
                Inventory.tenant_id == tenant_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = Inventory(
                tenant_id=tenant_id,
                product_id=product_id,
                quantity=quantity,
            )
            self._db.add(row)
            return StockResult(
                success=True,
                product_id=product_id,
                quantity_before=0,
                quantity_after=quantity,
                message="Inventory record created",
            )

        quantity_before = row.quantity
        row.quantity = quantity

        return StockResult(
            success=True,
            product_id=product_id,
            quantity_before=quantity_before,
            quantity_after=quantity,
            message="Stock updated",
        )
