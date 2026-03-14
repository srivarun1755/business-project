"""Products & aliases router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.product import Product, ProductAlias
from app.core.canonicalization import get_engine, invalidate_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Products"])


class ProductCreate(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    unit: str = Field(default="piece", max_length=50)
    hsn_code: Optional[str] = Field(None, max_length=10)
    default_price: Optional[float] = Field(None, ge=0)


class AliasCreate(BaseModel):
    alias: str = Field(..., min_length=1, max_length=255)


class ProductResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    unit: str
    hsn_code: Optional[str] = None
    default_price: Optional[float] = None
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id, Product.is_active == True)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/", response_model=ProductResponse, status_code=201)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    product = Product(**body.model_dump())
    db.add(product)
    await db.flush()

    # Auto-add the product name as an alias
    alias = ProductAlias(
        tenant_id=body.tenant_id,
        product_id=product.id,
        alias=body.name.lower(),
    )
    db.add(alias)
    await db.flush()

    # Invalidate canonicalization cache
    invalidate_engine(body.tenant_id)
    return product


@router.post("/{product_id}/aliases", status_code=201)
async def add_alias(
    product_id: str,
    body: AliasCreate,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Add an alias for a product (e.g., 'basmati', 'basmati rice', 'basmati 25kg')."""
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    alias = ProductAlias(
        tenant_id=tenant_id,
        product_id=product_id,
        alias=body.alias.lower(),
    )
    db.add(alias)
    await db.flush()

    # Update in-memory engine
    engine = get_engine(tenant_id)
    engine.add_alias(body.alias, product_id, product.name)

    return {"status": "created", "alias": body.alias}
