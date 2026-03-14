"""
WhatsApp Order Automation Backend.

A production-grade backend system for converting unstructured WhatsApp messages
into structured business operations for Indian SMEs.

Architecture Principles:
1. AI only for parsing unstructured input (voice transcription, order extraction)
2. Deterministic code for all financial logic
3. Idempotent processing for external webhooks
4. Atomic database operations
5. O(1) data lookups via Redis caching
6. Horizontally scalable SaaS architecture
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time

from src.core.config import settings
from src.core.database import init_db, close_db
from src.core.redis_cache import redis_cache
from src.api import api_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting WhatsApp Order Automation Backend...")
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    
    # Connect to Redis
    try:
        await redis_cache.connect()
        logger.info("Redis connected")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    await close_db()
    await redis_cache.disconnect()
    
    logger.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="""
    ## WhatsApp Order Automation Backend
    
    A production-grade backend system for Indian SMEs (kirana stores, wholesalers, distributors)
    that converts unstructured WhatsApp messages into structured business operations.
    
    ### Features
    
    - **WhatsApp Integration**: Process text and voice note orders
    - **Product Canonicalization**: Fuzzy matching for product names in Hindi/Hinglish
    - **Inventory Management**: Real-time stock tracking with atomic operations
    - **GST Invoice Generation**: Compliant with Indian GST requirements
    - **Credit Ledger**: Track customer credit with double-entry bookkeeping
    - **Payment Tracking**: Automated reminders and overdue tracking
    
    ### Architecture Principles
    
    - AI is used ONLY for parsing unstructured input
    - All financial logic is deterministic
    - Idempotent webhook processing
    - O(1) lookups via Redis caching
    - Horizontally scalable design
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An error occurred"
        }
    )


# Include API routes
app.include_router(api_router, prefix=settings.api_v1_prefix)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.0.0"
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": settings.app_name,
        "version": "1.0.0",
        "documentation": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
