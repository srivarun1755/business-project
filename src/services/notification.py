"""
Notification Service.

Handles sending notifications via:
- WhatsApp messages
- SMS (fallback)
- Email (optional)

This service does NOT use AI - message templates are predefined.
"""
import httpx
from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass

from src.core.config import settings


@dataclass
class NotificationResult:
    """Result of sending a notification."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    channel: str = "whatsapp"


class NotificationService:
    """
    Multi-channel notification service.
    
    Sends notifications via WhatsApp Business API.
    Uses predefined templates - no AI generation.
    """
    
    # Message templates (no AI - predefined)
    TEMPLATES = {
        "order_confirmed": """
🛒 *Order Confirmed*

Order #{order_number}
Customer: {customer_name}

Items:
{items_list}

Total: ₹{total_amount}

Thank you for your order!
""",
        
        "payment_reminder": """
⏰ *Payment Reminder*

Dear {customer_name},

Invoice: {invoice_number}
Amount Due: ₹{amount_due}
Due Date: {due_date}
Days Overdue: {days_overdue}

Please make payment at your earliest convenience.

Thank you!
""",
        
        "payment_received": """
✅ *Payment Received*

Dear {customer_name},

We have received your payment of ₹{amount}.

Invoice: {invoice_number}
Payment Method: {payment_method}

Thank you!
""",
        
        "invoice_generated": """
📄 *Invoice Generated*

Dear {customer_name},

Invoice: {invoice_number}
Amount: ₹{total_amount}
Due Date: {due_date}

Please find the invoice attached.

Thank you for your business!
""",
        
        "low_stock_alert": """
⚠️ *Low Stock Alert*

Product: {product_name}
Current Stock: {current_stock}
Reorder Level: {reorder_level}

Please restock soon!
""",
        
        "order_shipped": """
🚚 *Order Shipped*

Order #{order_number} has been shipped!

Estimated Delivery: {delivery_date}

Thank you!
""",
    }
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {settings.whatsapp_access_token}",
                    "Content-Type": "application/json",
                }
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _format_template(self, template_name: str, **kwargs) -> str:
        """
        Format a message template with provided values.
        
        Deterministic string formatting - no AI.
        """
        template = self.TEMPLATES.get(template_name, "")
        try:
            return template.format(**kwargs).strip()
        except KeyError as e:
            return f"Error formatting template: missing {e}"
    
    async def send_whatsapp_message(
        self,
        phone: str,
        message: str
    ) -> NotificationResult:
        """
        Send a WhatsApp text message.
        """
        try:
            client = await self._get_client()
            
            # Normalize phone number
            if not phone.startswith("+"):
                phone = f"+91{phone}"  # Default to India
            
            response = await client.post(
                f"{settings.whatsapp_api_url}/{settings.whatsapp_phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": phone,
                    "type": "text",
                    "text": {"body": message}
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                message_id = result.get("messages", [{}])[0].get("id")
                return NotificationResult(
                    success=True,
                    message_id=message_id,
                    channel="whatsapp"
                )
            else:
                return NotificationResult(
                    success=False,
                    error=f"API error: {response.status_code} - {response.text}",
                    channel="whatsapp"
                )
                
        except Exception as e:
            return NotificationResult(
                success=False,
                error=str(e),
                channel="whatsapp"
            )
    
    async def send_order_confirmation(
        self,
        phone: str,
        order_number: str,
        customer_name: str,
        items: List[dict],
        total_amount: str
    ) -> NotificationResult:
        """
        Send order confirmation message.
        """
        items_list = "\n".join([
            f"• {item['product']} x {item['quantity']} {item['unit']}"
            for item in items
        ])
        
        message = self._format_template(
            "order_confirmed",
            order_number=order_number,
            customer_name=customer_name,
            items_list=items_list,
            total_amount=total_amount
        )
        
        return await self.send_whatsapp_message(phone, message)
    
    async def send_payment_reminder(
        self,
        phone: str,
        customer_name: str,
        invoice_number: str,
        amount_due: str,
        due_date: str,
        days_overdue: int
    ) -> NotificationResult:
        """
        Send payment reminder message.
        """
        message = self._format_template(
            "payment_reminder",
            customer_name=customer_name,
            invoice_number=invoice_number,
            amount_due=amount_due,
            due_date=due_date,
            days_overdue=days_overdue
        )
        
        return await self.send_whatsapp_message(phone, message)
    
    async def send_payment_confirmation(
        self,
        phone: str,
        customer_name: str,
        amount: str,
        invoice_number: str,
        payment_method: str
    ) -> NotificationResult:
        """
        Send payment confirmation message.
        """
        message = self._format_template(
            "payment_received",
            customer_name=customer_name,
            amount=amount,
            invoice_number=invoice_number,
            payment_method=payment_method
        )
        
        return await self.send_whatsapp_message(phone, message)
    
    async def send_invoice_notification(
        self,
        phone: str,
        customer_name: str,
        invoice_number: str,
        total_amount: str,
        due_date: str
    ) -> NotificationResult:
        """
        Send invoice notification.
        """
        message = self._format_template(
            "invoice_generated",
            customer_name=customer_name,
            invoice_number=invoice_number,
            total_amount=total_amount,
            due_date=due_date
        )
        
        return await self.send_whatsapp_message(phone, message)
    
    async def send_low_stock_alert(
        self,
        phone: str,
        product_name: str,
        current_stock: str,
        reorder_level: str
    ) -> NotificationResult:
        """
        Send low stock alert to business owner.
        """
        message = self._format_template(
            "low_stock_alert",
            product_name=product_name,
            current_stock=current_stock,
            reorder_level=reorder_level
        )
        
        return await self.send_whatsapp_message(phone, message)
    
    async def send_bulk_reminders(
        self,
        reminders: List[dict]
    ) -> List[NotificationResult]:
        """
        Send bulk payment reminders.
        
        Each reminder should have:
        - phone
        - customer_name
        - invoice_number
        - amount_due
        - due_date
        - days_overdue
        """
        results = []
        
        for reminder in reminders:
            result = await self.send_payment_reminder(
                phone=reminder["phone"],
                customer_name=reminder["customer_name"],
                invoice_number=reminder["invoice_number"],
                amount_due=reminder["amount_due"],
                due_date=reminder["due_date"],
                days_overdue=reminder["days_overdue"]
            )
            results.append(result)
        
        return results


# Singleton instance
notification_service = NotificationService()
