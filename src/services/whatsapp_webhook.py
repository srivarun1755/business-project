"""
WhatsApp Webhook Service.

Handles incoming WhatsApp webhooks with:
- Idempotent processing (using idempotency keys)
- Message routing (text, voice, media)
- Atomic database operations
"""
import json
import hashlib
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.webhook import WebhookEvent, WebhookSource, WebhookStatus
from src.models.customer import Customer
from src.models.order import Order, OrderItem, OrderStatus, OrderSource
from src.models.product import Product
from src.schemas.whatsapp import WhatsAppWebhookPayload, WhatsAppMessage
from src.services.voice_processing import VoiceProcessingService
from src.services.order_parsing import OrderParsingService
from src.services.canonicalization import ProductCanonicalizationService
from src.services.inventory import InventoryService
from src.core.redis_cache import RedisCache


class WebhookProcessingError(Exception):
    """Error during webhook processing."""
    pass


class WhatsAppWebhookService:
    """
    WhatsApp webhook handler with idempotent processing.
    
    Features:
    - Idempotent message processing using message IDs
    - Text order processing
    - Voice note processing
    - Customer creation/lookup
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        redis_cache: RedisCache,
        voice_service: VoiceProcessingService,
        order_parser: OrderParsingService,
    ):
        self.db = db_session
        self.cache = redis_cache
        self.voice_service = voice_service
        self.order_parser = order_parser
        self._canonicalization: Optional[ProductCanonicalizationService] = None
        self._inventory: Optional[InventoryService] = None
    
    @property
    def canonicalization(self) -> ProductCanonicalizationService:
        """Lazy initialization of canonicalization service."""
        if self._canonicalization is None:
            self._canonicalization = ProductCanonicalizationService(
                self.db, self.cache
            )
        return self._canonicalization
    
    @property
    def inventory(self) -> InventoryService:
        """Lazy initialization of inventory service."""
        if self._inventory is None:
            self._inventory = InventoryService(self.db, self.cache)
        return self._inventory
    
    def _generate_idempotency_key(self, message: WhatsAppMessage) -> str:
        """
        Generate idempotency key from message.
        
        Uses message ID + timestamp for uniqueness.
        """
        key_data = f"{message.id}:{message.timestamp}"
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    async def is_duplicate(self, idempotency_key: str) -> bool:
        """
        Check if this webhook has been processed.
        
        Uses Redis for O(1) lookup.
        """
        return not await self.cache.check_idempotency(idempotency_key)
    
    async def log_webhook(
        self,
        payload: dict,
        source: WebhookSource,
        event_type: str,
        idempotency_key: str
    ) -> WebhookEvent:
        """
        Log webhook event for audit and replay.
        """
        event = WebhookEvent(
            idempotency_key=idempotency_key,
            source=source,
            event_type=event_type,
            payload=json.dumps(payload),
            status=WebhookStatus.RECEIVED,
        )
        self.db.add(event)
        await self.db.flush()
        return event
    
    async def process_webhook(
        self,
        payload: dict
    ) -> dict:
        """
        Main webhook processing entry point.
        
        Routes messages to appropriate handlers:
        - Text messages -> Order parsing
        - Voice notes -> Transcription + Order parsing
        
        Returns processing result.
        """
        try:
            webhook = WhatsAppWebhookPayload(**payload)
        except Exception as e:
            return {
                "success": False,
                "error": f"Invalid webhook payload: {str(e)}"
            }
        
        messages = webhook.get_messages()
        results = []
        
        for message in messages:
            # Generate idempotency key
            idempotency_key = self._generate_idempotency_key(message)
            
            # Check for duplicate
            if await self.is_duplicate(idempotency_key):
                results.append({
                    "message_id": message.id,
                    "status": "duplicate",
                    "skipped": True
                })
                continue
            
            # Log webhook
            await self.log_webhook(
                payload=payload,
                source=WebhookSource.WHATSAPP,
                event_type=message.type,
                idempotency_key=idempotency_key
            )
            
            # Process based on type
            if message.type == "text":
                result = await self._process_text_message(message, idempotency_key)
            elif message.type == "audio":
                result = await self._process_voice_message(message, idempotency_key)
            else:
                result = {
                    "message_id": message.id,
                    "status": "unsupported",
                    "type": message.type
                }
            
            results.append(result)
        
        return {
            "success": True,
            "processed": len(results),
            "results": results
        }
    
    async def _process_text_message(
        self,
        message: WhatsAppMessage,
        idempotency_key: str
    ) -> dict:
        """
        Process a text message order.
        
        Steps:
        1. Get or create customer
        2. Parse order using AI
        3. Canonicalize products
        4. Create order with deterministic pricing
        """
        phone = message.from_
        text = message.text.get("body", "") if message.text else ""
        
        if not text:
            return {
                "message_id": message.id,
                "status": "error",
                "error": "Empty message"
            }
        
        # Get or create customer
        customer = await self._get_or_create_customer(phone)
        
        # Parse order using AI
        parsing_result = await self.order_parser.parse_order_text(text)
        
        if not parsing_result.success:
            return {
                "message_id": message.id,
                "status": "parsing_failed",
                "errors": parsing_result.errors
            }
        
        # Create order
        try:
            order = await self._create_order(
                customer=customer,
                parsed_order=parsing_result.parsed_order,
                raw_message=text,
                source=OrderSource.WHATSAPP_TEXT,
                idempotency_key=idempotency_key
            )
            
            return {
                "message_id": message.id,
                "status": "success",
                "order_id": order.id,
                "order_number": order.order_number
            }
        except Exception as e:
            return {
                "message_id": message.id,
                "status": "error",
                "error": str(e)
            }
    
    async def _process_voice_message(
        self,
        message: WhatsAppMessage,
        idempotency_key: str
    ) -> dict:
        """
        Process a voice note order.
        
        Steps:
        1. Download and transcribe audio
        2. Parse transcribed text
        3. Create order
        """
        phone = message.from_
        audio_info = message.audio
        
        if not audio_info:
            return {
                "message_id": message.id,
                "status": "error",
                "error": "No audio info"
            }
        
        audio_id = audio_info.get("id")
        
        try:
            # Transcribe using Sarvam AI
            transcription = await self.voice_service.process_voice_note(audio_id)
            
            if not transcription.transcript:
                return {
                    "message_id": message.id,
                    "status": "transcription_failed",
                    "error": "Empty transcript"
                }
            
            # Get or create customer
            customer = await self._get_or_create_customer(phone)
            
            # Parse order
            parsing_result = await self.order_parser.parse_order_text(
                transcription.transcript
            )
            
            if not parsing_result.success:
                return {
                    "message_id": message.id,
                    "status": "parsing_failed",
                    "transcript": transcription.transcript,
                    "errors": parsing_result.errors
                }
            
            # Create order
            order = await self._create_order(
                customer=customer,
                parsed_order=parsing_result.parsed_order,
                raw_message=transcription.transcript,
                source=OrderSource.WHATSAPP_VOICE,
                idempotency_key=idempotency_key
            )
            
            return {
                "message_id": message.id,
                "status": "success",
                "order_id": order.id,
                "order_number": order.order_number,
                "transcript": transcription.transcript
            }
            
        except Exception as e:
            return {
                "message_id": message.id,
                "status": "error",
                "error": str(e)
            }
    
    async def _get_or_create_customer(self, phone: str) -> Customer:
        """
        Get existing customer or create new one.
        
        Uses phone number as unique identifier.
        """
        from sqlalchemy import select
        
        # Normalize phone number
        if phone.startswith("+91"):
            phone = phone[3:]
        elif phone.startswith("91") and len(phone) > 10:
            phone = phone[2:]
        
        # Check cache first
        cached = await self.cache.get_cached_customer(phone)
        if cached:
            customer = await self.db.get(Customer, cached["id"])
            if customer:
                return customer
        
        # Check database
        query = select(Customer).where(Customer.phone == phone)
        result = await self.db.execute(query)
        customer = result.scalar_one_or_none()
        
        if customer:
            # Cache for future lookups
            await self.cache.cache_customer(phone, {
                "id": customer.id,
                "name": customer.name
            })
            return customer
        
        # Create new customer
        customer = Customer(
            phone=phone,
            name=f"Customer {phone[-4:]}",  # Default name using last 4 digits
        )
        self.db.add(customer)
        await self.db.flush()
        
        # Cache
        await self.cache.cache_customer(phone, {
            "id": customer.id,
            "name": customer.name
        })
        
        return customer
    
    async def _create_order(
        self,
        customer: Customer,
        parsed_order: dict,
        raw_message: str,
        source: OrderSource,
        idempotency_key: str
    ) -> Order:
        """
        Create order from parsed data.
        
        Uses deterministic logic for all calculations.
        """
        from decimal import Decimal
        import json
        
        # Generate order number
        order_number = await self._generate_order_number()
        
        # Create order
        order = Order(
            order_number=order_number,
            customer_id=customer.id,
            status=OrderStatus.PENDING,
            source=source,
            raw_message=raw_message,
            parsed_data=json.dumps(parsed_order),
            idempotency_key=idempotency_key,
        )
        self.db.add(order)
        await self.db.flush()
        
        # Initialize canonicalization service
        await self.canonicalization.initialize()
        
        # Process items
        for item in parsed_order.get("items", []):
            product_name = item.get("product", "")
            quantity = Decimal(str(item.get("quantity", 1)))
            unit = item.get("unit", "piece")
            
            # Canonicalize product name
            match_result = await self.canonicalization.match_product(product_name)
            
            if match_result:
                product = await self.db.get(Product, match_result.product_id)
                
                if product:
                    # Create order item with deterministic pricing
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        original_product_name=product_name,
                        quantity=quantity,
                        unit=self.canonicalization.normalize_unit(unit),
                        unit_price=product.base_price,
                        total_price=Decimal("0"),  # Will be calculated
                        gst_rate=product.gst_rate,
                        hsn_code=product.hsn_code,
                    )
                    
                    # Deterministic calculation
                    order_item.calculate_totals()
                    
                    self.db.add(order_item)
                    
                    # Learn this alias for future
                    if match_result.match_type == "fuzzy":
                        await self.canonicalization.learn_alias(
                            product_name, 
                            product.id
                        )
        
        await self.db.flush()
        
        # Refresh to get items
        await self.db.refresh(order)
        
        # Calculate order totals
        order.calculate_totals()
        
        await self.db.flush()
        
        return order
    
    async def _generate_order_number(self) -> str:
        """Generate unique order number."""
        from sqlalchemy import func, select
        
        today = datetime.now()
        prefix = today.strftime("ORD%Y%m%d")
        
        # Get count of orders today
        query = select(func.count(Order.id)).where(
            Order.order_number.like(f"{prefix}%")
        )
        result = await self.db.execute(query)
        count = result.scalar() or 0
        
        return f"{prefix}{count + 1:04d}"
