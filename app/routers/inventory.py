"""Inventory router."""

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Inventory
from app.models.product import Product
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inventory", tags=["Inventory"])


class StockResponse(BaseModel):
    product_id: str
    product_name: Optional[str] = None
    quantity: int
    low_stock_threshold: int

    class Config:
        from_attributes = True


class StockAdjust(BaseModel):
    tenant_id: str
    product_id: str
    quantity: int = Field(..., ge=0)
    operation: str = Field("set", pattern="^(set|add|deduct)$")


@router.get("/{product_id}", response_model=StockResponse)
async def get_stock(
    product_id: str,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Inventory).where(
            Inventory.product_id == product_id,
            Inventory.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Inventory record not found")

    prod_result = await db.execute(select(Product).where(Product.id == product_id))
    product = prod_result.scalar_one_or_none()

    return StockResponse(
        product_id=row.product_id,
        product_name=product.name if product else None,
        quantity=row.quantity,
        low_stock_threshold=row.low_stock_threshold,
    )


@router.post("/adjust", status_code=200)
async def adjust_stock(
    body: StockAdjust,
    db: AsyncSession = Depends(get_db),
):
    """Adjust stock level for a product."""
    svc = InventoryService(db)
    if body.operation == "set":
        result = await svc.set_stock(body.tenant_id, body.product_id, body.quantity)
    elif body.operation == "add":
        result = await svc.add_stock(body.tenant_id, body.product_id, body.quantity)
    elif body.operation == "deduct":
        result = await svc.deduct_stock(body.tenant_id, body.product_id, body.quantity)
    else:
        raise HTTPException(status_code=400, detail="Invalid operation")

    if not result.success:
        raise HTTPException(status_code=422, detail=result.message)

    return {
        "product_id": result.product_id,
        "quantity_before": result.quantity_before,
        "quantity_after": result.quantity_after,
        "low_stock": result.low_stock,
        "message": result.message,
    }


@router.post("/upload")
async def bulk_upload_inventory(
    tenant_id: str = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk inventory upload from CSV file.

    Expected CSV columns: product_name, quantity
    Optional: hsn_code, unit, default_price
    """
    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    svc = InventoryService(db)
    results = []

    for row in reader:
        product_name = row.get("product_name", "").strip()
        if not product_name:
            continue

        quantity_str = row.get("quantity", "0").strip()
        try:
            quantity = int(quantity_str)
        except ValueError:
            logger.warning("Invalid quantity '%s' for product '%s'", quantity_str, product_name)
            continue

        # Find or create product
        prod_result = await db.execute(
            select(Product).where(
                Product.name == product_name,
                Product.tenant_id == tenant_id,
            )
        )
        product = prod_result.scalar_one_or_none()

        if product is None:
            product = Product(
                tenant_id=tenant_id,
                name=product_name,
                unit=row.get("unit", "piece").strip(),
                hsn_code=row.get("hsn_code", "").strip() or None,
                default_price=float(row.get("default_price", 0) or 0) or None,
            )
            db.add(product)
            await db.flush()

        stock_result = await svc.set_stock(tenant_id, product.id, quantity)
        results.append({
            "product": product_name,
            "product_id": product.id,
            "quantity": quantity,
            "success": stock_result.success,
        })

    return {"uploaded": len(results), "results": results}
