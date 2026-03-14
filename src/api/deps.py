"""API dependencies."""
from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.core.redis_cache import redis_cache, RedisCache
from src.services.canonicalization import ProductCanonicalizationService
from src.services.voice_processing import VoiceProcessingService, voice_processing_service
from src.services.order_parsing import OrderParsingService, order_parsing_service
from src.services.inventory import InventoryService
from src.services.invoice import InvoiceService
from src.services.credit_ledger import CreditLedgerService
from src.services.payment_tracking import PaymentTrackingService
from src.services.notification import NotificationService, notification_service
from src.services.whatsapp_webhook import WhatsAppWebhookService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async for session in get_db_session():
        yield session


async def get_redis() -> RedisCache:
    """Get Redis cache dependency."""
    return redis_cache


async def get_canonicalization_service(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_redis),
) -> ProductCanonicalizationService:
    """Get canonicalization service dependency."""
    service = ProductCanonicalizationService(db, cache)
    await service.initialize()
    return service


async def get_inventory_service(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_redis),
) -> InventoryService:
    """Get inventory service dependency."""
    return InventoryService(db, cache)


async def get_invoice_service(
    db: AsyncSession = Depends(get_db),
) -> InvoiceService:
    """Get invoice service dependency."""
    return InvoiceService(db)


async def get_credit_ledger_service(
    db: AsyncSession = Depends(get_db),
) -> CreditLedgerService:
    """Get credit ledger service dependency."""
    return CreditLedgerService(db)


async def get_payment_service(
    db: AsyncSession = Depends(get_db),
) -> PaymentTrackingService:
    """Get payment tracking service dependency."""
    return PaymentTrackingService(db)


async def get_notification_service() -> NotificationService:
    """Get notification service dependency."""
    return notification_service


async def get_webhook_service(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_redis),
) -> WhatsAppWebhookService:
    """Get WhatsApp webhook service dependency."""
    return WhatsAppWebhookService(
        db_session=db,
        redis_cache=cache,
        voice_service=voice_processing_service,
        order_parser=order_parsing_service,
    )
