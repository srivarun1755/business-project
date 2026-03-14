"""
PDF Invoice Generator
=====================
Generates GST-compliant invoice PDFs using Jinja2 templates + WeasyPrint.

PDF templates are pre-compiled for low latency.
AI is never used for invoice generation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


@dataclass
class InvoiceLineItem:
    product_name: str
    hsn_code: str
    quantity: int
    unit: str
    unit_price: Decimal
    subtotal: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_price: Decimal


@dataclass
class InvoiceData:
    invoice_number: str
    invoice_date: date
    due_date: Optional[date]
    seller_name: str
    seller_address: str
    seller_gstin: str
    seller_state: str
    buyer_name: str
    buyer_address: str
    buyer_gstin: Optional[str]
    buyer_state: str
    items: list[InvoiceLineItem]
    subtotal: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_tax: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    is_inter_state: bool
    notes: Optional[str] = None


def generate_invoice_pdf(invoice: InvoiceData) -> bytes:
    """
    Render an invoice to PDF bytes using WeasyPrint.
    Returns raw PDF bytes suitable for storage or HTTP response.
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        logger.warning("WeasyPrint not installed, returning empty bytes")
        return b""

    html_content = _render_html(invoice)
    pdf_bytes = HTML(string=html_content, base_url=TEMPLATE_DIR).write_pdf()
    return pdf_bytes


def generate_invoice_html(invoice: InvoiceData) -> str:
    """Render the invoice as HTML string (useful for preview / testing)."""
    return _render_html(invoice)


def _render_html(invoice: InvoiceData) -> str:
    """Render invoice HTML from Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # Register custom filters
    env.filters["currency"] = lambda v: f"₹{v:,.2f}"
    env.filters["pct"] = lambda v: f"{v}%"

    template = env.get_template("invoice.html")
    return template.render(inv=invoice)
