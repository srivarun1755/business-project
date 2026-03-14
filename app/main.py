"""
Main FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.config import get_settings
from app.routers import (
    webhook_router,
    orders_router,
    customers_router,
    products_router,
    invoices_router,
    payments_router,
    inventory_router,
)

settings = get_settings()
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


async def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting WhatsApp Order Automation Platform")
    redis = await get_redis_client()
    await redis.ping()
    logger.info("Redis connected")
    yield
    # Shutdown
    if _redis_client:
        await _redis_client.aclose()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Production-grade backend for WhatsApp-based order automation "
        "for Indian SMEs (kirana stores, wholesalers, distributors)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(webhook_router)
app.include_router(orders_router)
app.include_router(customers_router)
app.include_router(products_router)
app.include_router(invoices_router)
app.include_router(payments_router)
app.include_router(inventory_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": settings.app_name}
