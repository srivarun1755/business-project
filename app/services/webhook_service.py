"""
Webhook Service
===============
Handles incoming WhatsApp webhook events with idempotency checks.

Orchestrates the complete order processing pipeline:
  1. Idempotency check (Redis)
  2. Voice transcription (Sarvam AI, if audio message)
  3. Order parsing (LLM)
  4. Product canonicalization (deterministic fuzzy matching)
  5. Inventory validation (atomic)
  6. Credit limit check
  7. GST + Invoice generation
  8. Customer notification
"""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.canonicalization import get_engine
from app.core.idempotency import IdempotencyService
from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import ProductAlias
from app.services.credit_ledger_service import CreditLedgerService
from app.services.inventory_service import InventoryService
from app.services.invoice_service import InvoiceService
from app.services.notification_service import NotificationService
from app.services.order_parsing_service import OrderParsingService
from app.services.voice_service import VoiceProcessingService

import httpx

settings = get_settings()
logger = logging.getLogger(__name__)


class WebhookService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self._db = db
        self._redis = redis
        self._idempotency = IdempotencyService(redis)
        self._voice = VoiceProcessingService()
        self._parser = OrderParsingService()
        self._notifier = NotificationService()

    async def handle_event(self, payload: dict[str, Any], tenant_id: str) -> dict:
        """
        Main entry point for WhatsApp webhook events.
        Returns a processing result dict.
        """
        try:
            messages = (
                payload.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("messages", [])
            )
        except (IndexError, KeyError, TypeError):
            return {"status": "ignored", "reason": "no_messages"}

        results = []
        for message in messages:
            result = await self._process_message(message, tenant_id)
            results.append(result)

        return {"status": "ok", "processed": len(results), "results": results}

    async def _process_message(self, message: dict, tenant_id: str) -> dict:
        """Process a single WhatsApp message."""
        message_id = message.get("id")
        if not message_id:
            return {"status": "skipped", "reason": "no_message_id"}

        # Step 1: Idempotency check (O(1))
        if await self._idempotency.is_duplicate(f"{tenant_id}:{message_id}"):
            return {"status": "duplicate", "message_id": message_id}

        msg_type = message.get("type")
        from_phone = message.get("from", "")

        # Step 2: Extract text
        text = await self._extract_text(message, msg_type)
        if not text:
            return {"status": "skipped", "reason": "unsupported_message_type", "type": msg_type}

        # Step 3: Parse order (AI)
        try:
            parsed_order = await self._parser.parse(text)
        except ValueError as exc:
            logger.warning("Order parse failed for message %s: %s", message_id, exc)
            await self._notifier.send_text(
                from_phone,
                "Sorry, I couldn't understand your order. Please try again with the product name and quantity.",
            )
            return {"status": "parse_error", "message_id": message_id, "error": str(exc)}

        # Step 4: Find or create customer
        customer = await self._get_or_create_customer(
            tenant_id, from_phone, parsed_order.customer
        )

        # Step 5: Canonicalize products and build order items
        order_items, unresolved = await self._canonicalize_items(
            tenant_id, parsed_order.items
        )

        if not order_items:
            return {
                "status": "unresolved_products",
                "message_id": message_id,
                "unresolved": unresolved,
            }

        # Step 6: Check inventory
        inventory_svc = InventoryService(self._db)
        inventory_errors = []
        for oi_data in order_items:
            result = await inventory_svc.deduct_stock(
                tenant_id, oi_data["product_id"], oi_data["quantity"]
            )
            if not result.success:
                inventory_errors.append(result.message)

        if inventory_errors:
            return {
                "status": "inventory_error",
                "message_id": message_id,
                "errors": inventory_errors,
            }

        # Step 7: Create order record
        total_amount = sum(oi["quantity"] * oi["unit_price"] for oi in order_items)
        order = Order(
            tenant_id=tenant_id,
            customer_id=customer.id,
            whatsapp_message_id=message_id,
            raw_text=text,
            status=OrderStatus.CONFIRMED,
            total_amount=total_amount,
        )
        self._db.add(order)
        await self._db.flush()

        for oi_data in order_items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=oi_data["product_id"],
                raw_product_name=oi_data.get("raw_name"),
                quantity=oi_data["quantity"],
                unit=oi_data.get("unit", "piece"),
                unit_price=oi_data["unit_price"],
                total_price=oi_data["quantity"] * oi_data["unit_price"],
            )
            self._db.add(order_item)

        await self._db.flush()

        # Step 8: Credit limit check
        credit_svc = CreditLedgerService(self._db)
        credit_check = await credit_svc.check_credit(
            tenant_id, customer.id, total_amount
        )
        if not credit_check.allowed:
            order.status = OrderStatus.CREDIT_HOLD
            await self._notifier.send_credit_hold_notification(
                from_phone,
                customer.name,
                credit_check.current_balance,
                credit_check.credit_limit,
            )
            return {
                "status": "credit_hold",
                "message_id": message_id,
                "order_id": order.id,
                "reason": credit_check.message,
            }

        # Step 9: Generate invoice
        invoice_svc = InvoiceService(self._db)
        # Reload order with items for invoice generation
        await self._db.refresh(order, attribute_names=["items"])
        invoice = await invoice_svc.create_invoice(
            tenant_id=tenant_id,
            order=order,
            seller_gstin=settings.seller_gstin or "27AAPFU0939F1ZV",
            seller_state_code=settings.seller_state_code,
        )

        # Step 10: Record credit ledger entry
        await credit_svc.record_invoice_created(
            tenant_id, customer.id, invoice.id, invoice.total_amount
        )

        # Step 11: Notify customer
        await self._notifier.send_order_confirmation(
            from_phone,
            customer.name,
            invoice.invoice_number,
            invoice.total_amount,
        )

        return {
            "status": "success",
            "message_id": message_id,
            "order_id": order.id,
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "total_amount": invoice.total_amount,
        }

    async def _extract_text(self, message: dict, msg_type: str) -> str | None:
        """Extract or transcribe message text."""
        if msg_type == "text":
            return message.get("text", {}).get("body", "").strip()

        if msg_type == "audio":
            audio_id = message.get("audio", {}).get("id")
            if audio_id and settings.whatsapp_token:
                audio_bytes = await self._download_media(audio_id)
                if audio_bytes:
                    result = await self._voice.transcribe(audio_bytes)
                    return result.text
        return None

    async def _download_media(self, media_id: str) -> bytes | None:
        """Download media from WhatsApp servers."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Get media URL
                resp = await client.get(
                    f"{settings.whatsapp_api_url}/{media_id}",
                    headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                )
                resp.raise_for_status()
                media_url = resp.json().get("url")

                # Download media bytes
                media_resp = await client.get(
                    media_url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                )
                media_resp.raise_for_status()
                return media_resp.content
        except Exception as exc:
            logger.error("Failed to download media %s: %s", media_id, exc)
            return None

    async def _get_or_create_customer(
        self, tenant_id: str, phone: str, name: str | None
    ) -> Customer:
        """Find existing customer by phone or create a new one."""
        result = await self._db.execute(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.phone == phone,
            )
        )
        customer = result.scalar_one_or_none()

        if customer is None:
            customer = Customer(
                tenant_id=tenant_id,
                name=name or phone,
                phone=phone,
                credit_limit=settings.default_credit_limit,
            )
            self._db.add(customer)
            await self._db.flush()

        return customer

    async def _canonicalize_items(
        self, tenant_id: str, parsed_items: list
    ) -> tuple[list[dict], list[str]]:
        """
        Resolve parsed item product names to canonical product IDs.
        Returns (resolved_items, unresolved_names).
        """
        # Load aliases for this tenant from DB into the engine
        engine = get_engine(tenant_id)
        if not engine._alias_map:
            # Lazy load aliases from DB
            alias_result = await self._db.execute(
                select(ProductAlias).where(ProductAlias.tenant_id == tenant_id)
            )
            aliases_db = alias_result.scalars().all()
            from app.models.product import Product as ProductModel
            alias_tuples = []
            product_price_map: dict[str, float] = {}
            for alias_row in aliases_db:
                prod_result = await self._db.execute(
                    select(ProductModel).where(ProductModel.id == alias_row.product_id)
                )
                prod = prod_result.scalar_one_or_none()
                if prod:
                    alias_tuples.append((alias_row.alias, prod.id, prod.name))
                    product_price_map[prod.id] = prod.default_price or 0.0
            engine.load_aliases(alias_tuples)
        else:
            # Build price map from already-loaded alias data if needed
            product_price_map = {}

        resolved = []
        unresolved = []

        for item in parsed_items:
            match = engine.resolve(item.product)
            if match:
                resolved.append({
                    "product_id": match.product_id,
                    "product_name": match.product_name,
                    "raw_name": item.product,
                    "quantity": int(item.quantity),
                    "unit": item.unit,
                    "unit_price": product_price_map.get(match.product_id, 0.0),
                    "match_method": match.match_method,
                })
            else:
                unresolved.append(item.product)

        return resolved, unresolved
