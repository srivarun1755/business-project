"""WhatsApp webhook endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from fastapi.responses import PlainTextResponse

from src.core.config import settings
from src.api.deps import get_webhook_service
from src.services.whatsapp_webhook import WhatsAppWebhookService

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    WhatsApp webhook verification endpoint.
    
    Called by WhatsApp to verify webhook URL.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(content=hub_challenge)
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification failed"
    )


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    webhook_service: WhatsAppWebhookService = Depends(get_webhook_service),
):
    """
    WhatsApp webhook receiver endpoint.
    
    Receives and processes incoming WhatsApp messages:
    - Text messages -> Order parsing
    - Voice notes -> Transcription + Order parsing
    
    Implements idempotent processing using message IDs.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    result = await webhook_service.process_webhook(payload)
    
    # Always return 200 to acknowledge receipt
    return {"status": "received", **result}


@router.post("/webhook/test")
async def test_webhook(
    message: str,
    phone: str = "9999999999",
    webhook_service: WhatsAppWebhookService = Depends(get_webhook_service),
):
    """
    Test endpoint for simulating WhatsApp messages.
    
    For development/testing only.
    """
    import hashlib
    from datetime import datetime
    
    # Create simulated webhook payload
    message_id = hashlib.md5(f"{phone}{message}{datetime.now()}".encode()).hexdigest()
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "test_entry",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": settings.whatsapp_phone_number_id,
                        "display_phone_number": "15551234567"
                    },
                    "contacts": [{
                        "profile": {"name": "Test User"},
                        "wa_id": phone
                    }],
                    "messages": [{
                        "id": message_id,
                        "from": phone,
                        "timestamp": str(int(datetime.now().timestamp())),
                        "type": "text",
                        "text": {"body": message}
                    }]
                }
            }]
        }]
    }
    
    result = await webhook_service.process_webhook(payload)
    return result
