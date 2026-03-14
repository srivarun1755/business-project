"""API router initialization."""
from fastapi import APIRouter
from src.api.v1 import whatsapp, orders, inventory, invoices, customers, payments

api_router = APIRouter()

api_router.include_router(
    whatsapp.router,
    prefix="/whatsapp",
    tags=["WhatsApp"]
)
api_router.include_router(
    orders.router,
    prefix="/orders",
    tags=["Orders"]
)
api_router.include_router(
    inventory.router,
    prefix="/inventory",
    tags=["Inventory"]
)
api_router.include_router(
    invoices.router,
    prefix="/invoices",
    tags=["Invoices"]
)
api_router.include_router(
    customers.router,
    prefix="/customers",
    tags=["Customers"]
)
api_router.include_router(
    payments.router,
    prefix="/payments",
    tags=["Payments"]
)
