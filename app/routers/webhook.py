"""
WhatsApp Webhook Router
=======================
Handles WhatsApp Business API webhook verification and event delivery.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.webhook_service import WebhookService

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Webhook"])


async def get_redis() -> Redis:
    from app.main import get_redis_client
    return await get_redis_client()


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    WhatsApp webhook verification endpoint.
    Meta sends a GET request with a challenge token to verify the endpoint.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/whatsapp")
async def receive_webhook(
    request: Request,
    tenant_id: str = Query(..., description="Tenant identifier"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Receive and process incoming WhatsApp messages.

    Implements idempotent processing — duplicate webhook deliveries
    are safely ignored using a Redis-backed message ID set.
    """
    # Verify webhook signature (optional but recommended)
    body = await request.body()
    _verify_signature(request, body)

    payload = await request.json()
    svc = WebhookService(db, redis)
    result = await svc.handle_event(payload, tenant_id)
    return result


def _verify_signature(request: Request, body: bytes) -> None:
    """Verify X-Hub-Signature-256 header if app secret is configured."""
    app_secret = settings.secret_key
    if not app_secret:
        if settings.debug:
            return  # Skip verification only when DEBUG mode is explicitly enabled
        raise HTTPException(
            status_code=403,
            detail="Webhook secret not configured; set SECRET_KEY in environment",
        )

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing or invalid webhook signature")

    expected = hmac.new(
        app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
