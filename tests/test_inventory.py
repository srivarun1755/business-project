"""
Tests for the Inventory Service.
Atomic stock operations must use row-level locking.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from app.services.inventory_service import InventoryService


def make_inventory(
    *,
    id="inv-row-001",
    tenant_id="tenant-001",
    product_id="prod-001",
    quantity=100,
    low_stock_threshold=10,
):
    return SimpleNamespace(
        id=id,
        tenant_id=tenant_id,
        product_id=product_id,
        quantity=quantity,
        low_stock_threshold=low_stock_threshold,
    )


def _mock_db_with_row(row):
    """Helper to return a db mock whose execute().scalar_one_or_none() returns row."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()  # session.add() is synchronous in SQLAlchemy
    return db


class TestDeductStock:
    @pytest.mark.asyncio
    async def test_successful_deduction(self):
        inventory_row = make_inventory(quantity=50)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-001", 10)

        assert result.success is True
        assert result.quantity_before == 50
        assert result.quantity_after == 40
        assert inventory_row.quantity == 40

    @pytest.mark.asyncio
    async def test_insufficient_stock_blocked(self):
        inventory_row = make_inventory(quantity=5)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-001", 10)

        assert result.success is False
        assert "Insufficient stock" in result.message
        assert inventory_row.quantity == 5  # unchanged

    @pytest.mark.asyncio
    async def test_exact_quantity_deduction(self):
        """Deducting exact available quantity should succeed."""
        inventory_row = make_inventory(quantity=10)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-001", 10)

        assert result.success is True
        assert result.quantity_after == 0

    @pytest.mark.asyncio
    async def test_product_not_found(self):
        db = _mock_db_with_row(None)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-missing", 5)

        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_low_stock_alert_triggered(self):
        """When stock falls to or below threshold, low_stock should be True."""
        inventory_row = make_inventory(quantity=15, low_stock_threshold=10)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-001", 6)

        # 15 - 6 = 9, which is ≤ threshold of 10
        assert result.success is True
        assert result.low_stock is True
        assert result.quantity_after == 9

    @pytest.mark.asyncio
    async def test_no_low_stock_above_threshold(self):
        """When stock remains above threshold, low_stock should be False."""
        inventory_row = make_inventory(quantity=50, low_stock_threshold=10)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.deduct_stock("tenant-001", "prod-001", 5)

        assert result.success is True
        assert result.low_stock is False
        assert result.quantity_after == 45


class TestAddStock:
    @pytest.mark.asyncio
    async def test_add_to_existing_inventory(self):
        inventory_row = make_inventory(quantity=50)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.add_stock("tenant-001", "prod-001", 25)

        assert result.success is True
        assert result.quantity_before == 50
        assert result.quantity_after == 75
        assert inventory_row.quantity == 75

    @pytest.mark.asyncio
    async def test_create_inventory_record_if_not_exists(self):
        db = _mock_db_with_row(None)

        svc = InventoryService(db)
        result = await svc.add_stock("tenant-001", "prod-new", 100)

        assert result.success is True
        assert result.quantity_before == 0
        assert result.quantity_after == 100
        db.add.assert_called_once()


class TestSetStock:
    @pytest.mark.asyncio
    async def test_set_replaces_quantity(self):
        inventory_row = make_inventory(quantity=100)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.set_stock("tenant-001", "prod-001", 250)

        assert result.success is True
        assert result.quantity_before == 100
        assert result.quantity_after == 250
        assert inventory_row.quantity == 250

    @pytest.mark.asyncio
    async def test_set_zero_stock(self):
        inventory_row = make_inventory(quantity=100)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        result = await svc.set_stock("tenant-001", "prod-001", 0)

        assert result.success is True
        assert result.quantity_after == 0


class TestGetStock:
    @pytest.mark.asyncio
    async def test_returns_current_quantity(self):
        inventory_row = make_inventory(quantity=42)
        db = _mock_db_with_row(inventory_row)

        svc = InventoryService(db)
        qty = await svc.get_stock("tenant-001", "prod-001")

        assert qty == 42

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self):
        db = _mock_db_with_row(None)

        svc = InventoryService(db)
        qty = await svc.get_stock("tenant-001", "prod-missing")

        assert qty is None
