"""
Notification Service
====================
Sends WhatsApp messages to customers using the WhatsApp Business API.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class NotificationService:
    """Send WhatsApp messages via Meta's Cloud API."""

    async def send_text(self, phone: str, message: str) -> bool:
        """Send a plain text WhatsApp message."""
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            logger.warning("WhatsApp not configured; skipping notification to %s", phone)
            return False

        url = (
            f"{settings.whatsapp_api_url}"
            f"/{settings.whatsapp_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.whatsapp_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
            logger.info("WhatsApp notification sent to %s", phone)
            return True
        except Exception as exc:
            logger.error("Failed to send WhatsApp message to %s: %s", phone, exc)
            return False

    async def send_order_confirmation(
        self,
        phone: str,
        customer_name: str,
        invoice_number: str,
        total_amount: float,
    ) -> bool:
        """Send order confirmation message."""
        message = (
            f"✅ Order Confirmed!\n\n"
            f"Dear {customer_name},\n"
            f"Invoice No: {invoice_number}\n"
            f"Total: ₹{total_amount:,.2f}\n\n"
            f"Thank you for your order!"
        )
        return await self.send_text(phone, message)

    async def send_credit_hold_notification(
        self,
        phone: str,
        customer_name: str,
        outstanding_balance: float,
        credit_limit: float,
    ) -> bool:
        """Notify customer that their order is on credit hold."""
        message = (
            f"⚠️ Order on Credit Hold\n\n"
            f"Dear {customer_name},\n"
            f"Your order cannot be processed as your outstanding balance "
            f"(₹{outstanding_balance:,.2f}) exceeds your credit limit "
            f"(₹{credit_limit:,.2f}).\n\n"
            f"Please clear dues to proceed. Contact us for assistance."
        )
        return await self.send_text(phone, message)

    async def send_payment_reminder(
        self,
        phone: str,
        customer_name: str,
        invoice_number: str,
        amount_due: float,
        due_date: str,
    ) -> bool:
        """Send payment reminder for an overdue invoice."""
        message = (
            f"🔔 Payment Reminder\n\n"
            f"Dear {customer_name},\n"
            f"Invoice {invoice_number} of ₹{amount_due:,.2f} "
            f"is due on {due_date}.\n\n"
            f"Please make payment at your earliest convenience."
        )
        return await self.send_text(phone, message)

    async def send_low_stock_alert(
        self,
        phone: str,
        product_name: str,
        quantity: int,
    ) -> bool:
        """Send low stock alert to the business owner."""
        message = (
            f"📦 Low Stock Alert\n\n"
            f"Product: {product_name}\n"
            f"Remaining Stock: {quantity} units\n\n"
            f"Please restock soon."
        )
        return await self.send_text(phone, message)
