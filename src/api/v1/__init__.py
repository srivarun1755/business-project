"""API v1 routes initialization."""
from src.api.v1 import whatsapp, orders, inventory, invoices, customers, payments

__all__ = [
    "whatsapp",
    "orders",
    "inventory",
    "invoices",
    "customers",
    "payments",
]
