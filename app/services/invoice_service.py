"""
Invoice Service
===============
Orchestrates GST calculation, invoice record creation, and PDF generation.
All financial logic is deterministic — no AI involved.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.order import Order
from app.models.customer import Customer
from app.models.product import Product
from app.core.gst_engine import calculate_invoice_tax
from app.core.hsn_lookup import get_hsn_for_product

logger = logging.getLogger(__name__)

INVOICE_PREFIX = "INV"


class InvoiceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _next_invoice_number(self, tenant_id: str) -> str:
        """Generate a sequential invoice number per tenant."""
        result = await self._db.execute(
            select(func.count(Invoice.id)).where(Invoice.tenant_id == tenant_id)
        )
        count = result.scalar_one() or 0
        today = date.today().strftime("%Y%m%d")
        return f"{INVOICE_PREFIX}-{today}-{count + 1:05d}"

    async def create_invoice(
        self,
        tenant_id: str,
        order: Order,
        seller_gstin: str,
        seller_state_code: str,
        payment_terms_days: int = 30,
    ) -> Invoice:
        """
        Create a GST invoice for a confirmed order.

        Steps:
        1. Fetch customer & product data
        2. Compute GST via deterministic engine
        3. Persist Invoice + InvoiceItems
        4. Return Invoice (PDF generation is async)
        """
        # Fetch customer
        cust_result = await self._db.execute(
            select(Customer).where(Customer.id == order.customer_id)
        )
        customer = cust_result.scalar_one()

        # Build line items for GST calculation
        line_items_for_tax = []
        order_items_data = []

        for item in order.items:
            prod_result = await self._db.execute(
                select(Product).where(Product.id == item.product_id)
            )
            product = prod_result.scalar_one()
            hsn_code = product.hsn_code or get_hsn_for_product(product.name)

            line_items_for_tax.append({
                "product_name": product.name,
                "hsn_code": hsn_code,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
            })
            order_items_data.append({
                "product": product,
                "item": item,
                "hsn_code": hsn_code,
            })

        # Deterministic GST calculation
        tax_summary = calculate_invoice_tax(
            line_items=line_items_for_tax,
            seller_state_code=seller_state_code,
            buyer_state_code=customer.state_code or seller_state_code,
        )

        invoice_number = await self._next_invoice_number(tenant_id)
        invoice_date = date.today()

        invoice = Invoice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            invoice_number=invoice_number,
            order_id=order.id,
            customer_id=customer.id,
            status=InvoiceStatus.ISSUED,
            invoice_date=invoice_date,
            due_date=invoice_date + timedelta(days=payment_terms_days),
            subtotal=float(tax_summary.subtotal),
            cgst_amount=float(tax_summary.cgst_amount),
            sgst_amount=float(tax_summary.sgst_amount),
            igst_amount=float(tax_summary.igst_amount),
            total_tax=float(tax_summary.total_tax),
            total_amount=float(tax_summary.total_amount),
            amount_paid=0.0,
            amount_due=float(tax_summary.total_amount),
            seller_gstin=seller_gstin,
            buyer_gstin=customer.gstin,
            place_of_supply=customer.state_code or seller_state_code,
        )
        self._db.add(invoice)

        # Create invoice line items
        for i, breakdown in enumerate(tax_summary.line_items):
            data = order_items_data[i]
            product = data["product"]
            item = data["item"]

            inv_item = InvoiceItem(
                id=str(uuid.uuid4()),
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                hsn_code=breakdown.hsn_code,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=float(breakdown.taxable_amount / Decimal(str(item.quantity))),
                subtotal=float(breakdown.taxable_amount),
                gst_rate=float(breakdown.gst_rate),
                cgst_rate=float(breakdown.cgst_rate),
                sgst_rate=float(breakdown.sgst_rate),
                igst_rate=float(breakdown.igst_rate),
                cgst_amount=float(breakdown.cgst_amount),
                sgst_amount=float(breakdown.sgst_amount),
                igst_amount=float(breakdown.igst_amount),
                total_price=float(breakdown.total_amount),
            )
            self._db.add(inv_item)

        await self._db.flush()
        logger.info(
            "Invoice created: %s total=%.2f tenant=%s",
            invoice_number, tax_summary.total_amount, tenant_id,
        )
        return invoice
