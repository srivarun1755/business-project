from app.routers.webhook import router as webhook_router
from app.routers.orders import router as orders_router
from app.routers.customers import router as customers_router
from app.routers.products import router as products_router
from app.routers.invoices import router as invoices_router
from app.routers.payments import router as payments_router
from app.routers.inventory import router as inventory_router
from app.routers.reference_photos import router as reference_photos_router

__all__ = [
    "webhook_router",
    "orders_router",
    "customers_router",
    "products_router",
    "invoices_router",
    "payments_router",
    "inventory_router",
    "reference_photos_router",
]
