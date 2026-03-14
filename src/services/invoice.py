"""
Invoice Service.

Handles GST-compliant invoice generation with:
- CGST/SGST for intra-state transactions
- IGST for inter-state transactions
- Proper HSN code handling
- PDF generation
- All calculations are deterministic (no AI)
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List
from datetime import datetime, date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from src.models.order import Order, OrderItem
from src.models.customer import Customer
from src.core.config import settings


# Indian state codes for GST
STATE_CODES = {
    "Andhra Pradesh": "37", "Arunachal Pradesh": "12", "Assam": "18",
    "Bihar": "10", "Chhattisgarh": "22", "Goa": "30", "Gujarat": "24",
    "Haryana": "06", "Himachal Pradesh": "02", "Jharkhand": "20",
    "Karnataka": "29", "Kerala": "32", "Madhya Pradesh": "23",
    "Maharashtra": "27", "Manipur": "14", "Meghalaya": "17",
    "Mizoram": "15", "Nagaland": "13", "Odisha": "21", "Punjab": "03",
    "Rajasthan": "08", "Sikkim": "11", "Tamil Nadu": "33",
    "Telangana": "36", "Tripura": "16", "Uttar Pradesh": "09",
    "Uttarakhand": "05", "West Bengal": "19", "Delhi": "07",
}


class InvoiceService:
    """
    GST-compliant invoice generation service.
    
    All calculations are deterministic:
    - Tax calculations based on HSN codes and GST rates
    - CGST/SGST split for intra-state (50/50)
    - IGST for inter-state transactions
    - Amount in words conversion
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._invoice_counter: int = 0
    
    async def create_invoice(
        self,
        order: Order,
        due_days: int = 30,
        notes: Optional[str] = None,
        terms: Optional[str] = None
    ) -> Invoice:
        """
        Create a GST-compliant invoice from an order.
        
        Deterministic calculation of all tax components.
        """
        # Get customer details
        customer = await self.db.get(Customer, order.customer_id)
        if not customer:
            raise ValueError(f"Customer {order.customer_id} not found")
        
        # Generate invoice number
        invoice_number = await self._generate_invoice_number()
        
        # Determine state codes
        seller_state = settings.business_address.split(",")[-1].strip() if settings.business_address else "Maharashtra"
        seller_state_code = STATE_CODES.get(seller_state, "27")  # Default to Maharashtra
        
        customer_state = customer.state or seller_state
        customer_state_code = STATE_CODES.get(customer_state, seller_state_code)
        
        # Create invoice
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order.id,
            customer_name=customer.name,
            customer_gstin=customer.gstin,
            customer_address=customer.address,
            customer_state=customer_state,
            customer_state_code=customer_state_code,
            seller_name=settings.business_name,
            seller_gstin=settings.business_gstin,
            seller_address=settings.business_address,
            seller_state=seller_state,
            seller_state_code=seller_state_code,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=due_days),
            status=InvoiceStatus.ISSUED,
            notes=notes,
            terms=terms or self._default_terms(),
        )
        
        self.db.add(invoice)
        await self.db.flush()
        
        # Create invoice items from order items
        for order_item in order.items:
            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                description=order_item.original_product_name or "Product",
                hsn_code=order_item.hsn_code,
                quantity=order_item.quantity,
                unit=order_item.unit,
                unit_price=order_item.unit_price,
                gst_rate=order_item.gst_rate,
                taxable_amount=Decimal("0"),  # Will be calculated
                tax_amount=Decimal("0"),  # Will be calculated
                total_amount=Decimal("0"),  # Will be calculated
            )
            
            # Deterministic calculation
            invoice_item.calculate_totals()
            
            self.db.add(invoice_item)
        
        await self.db.flush()
        
        # Refresh to get items
        await self.db.refresh(invoice)
        
        # Calculate invoice totals
        invoice.calculate_totals()
        
        # Generate amount in words
        invoice.amount_in_words = self._amount_to_words(invoice.total_amount)
        
        await self.db.flush()
        
        return invoice
    
    async def _generate_invoice_number(self) -> str:
        """
        Generate unique invoice number in GST format.
        Format: STATE_CODE/YEAR/SERIAL
        Example: 27/2024/000001
        """
        current_year = datetime.now().year
        state_code = STATE_CODES.get(
            settings.business_address.split(",")[-1].strip() if settings.business_address else "Maharashtra",
            "27"
        )
        
        # Get max serial for this year
        query = select(func.count(Invoice.id)).where(
            Invoice.invoice_number.like(f"{state_code}/{current_year}/%")
        )
        result = await self.db.execute(query)
        count = result.scalar() or 0
        
        serial = count + 1
        
        return f"{state_code}/{current_year}/{serial:06d}"
    
    def _default_terms(self) -> str:
        """Default invoice terms and conditions."""
        return """
1. Payment is due within 30 days of invoice date.
2. All disputes must be raised within 7 days of invoice receipt.
3. Goods once sold will not be taken back.
4. Subject to local jurisdiction.
""".strip()
    
    def _amount_to_words(self, amount: Decimal) -> str:
        """
        Convert amount to words (Indian format).
        
        Deterministic conversion.
        """
        ones = [
            "", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
            "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
            "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
            "Nineteen"
        ]
        tens = [
            "", "", "Twenty", "Thirty", "Forty", "Fifty",
            "Sixty", "Seventy", "Eighty", "Ninety"
        ]
        
        def convert_less_than_thousand(n: int) -> str:
            if n == 0:
                return ""
            elif n < 20:
                return ones[n]
            elif n < 100:
                return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
            else:
                return ones[n // 100] + " Hundred" + (
                    " and " + convert_less_than_thousand(n % 100)
                    if n % 100 else ""
                )
        
        def convert(n: int) -> str:
            if n == 0:
                return "Zero"
            
            # Indian number system: Lakh, Crore
            crore = n // 10000000
            n %= 10000000
            lakh = n // 100000
            n %= 100000
            thousand = n // 1000
            n %= 1000
            
            result = ""
            if crore:
                result += convert_less_than_thousand(crore) + " Crore "
            if lakh:
                result += convert_less_than_thousand(lakh) + " Lakh "
            if thousand:
                result += convert_less_than_thousand(thousand) + " Thousand "
            if n:
                result += convert_less_than_thousand(n)
            
            return result.strip()
        
        # Split into rupees and paise
        rupees = int(amount)
        paise = int((amount - rupees) * 100)
        
        result = f"Rupees {convert(rupees)}"
        if paise:
            result += f" and {convert(paise)} Paise"
        result += " Only"
        
        return result
    
    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Get invoice by ID."""
        return await self.db.get(Invoice, invoice_id)
    
    async def get_invoice_by_order(self, order_id: str) -> Optional[Invoice]:
        """Get invoice by order ID."""
        query = select(Invoice).where(Invoice.order_id == order_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_invoice_status(
        self,
        invoice_id: str,
        status: InvoiceStatus
    ) -> Invoice:
        """Update invoice status."""
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")
        
        invoice.status = status
        await self.db.flush()
        
        return invoice
    
    async def get_overdue_invoices(self) -> List[Invoice]:
        """Get all overdue invoices."""
        query = select(Invoice).where(
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID]),
            Invoice.due_date < date.today()
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def calculate_tax_breakdown(
        self,
        items: List[InvoiceItem],
        is_inter_state: bool
    ) -> dict:
        """
        Calculate detailed tax breakdown.
        
        Returns dict with:
        - by_rate: breakdown by GST rate
        - totals: CGST, SGST, IGST totals
        """
        breakdown = {
            "by_rate": {},
            "totals": {
                "cgst": Decimal("0"),
                "sgst": Decimal("0"),
                "igst": Decimal("0"),
            }
        }
        
        for item in items:
            rate_key = str(item.gst_rate)
            
            if rate_key not in breakdown["by_rate"]:
                breakdown["by_rate"][rate_key] = {
                    "taxable_amount": Decimal("0"),
                    "tax_amount": Decimal("0"),
                }
            
            breakdown["by_rate"][rate_key]["taxable_amount"] += item.taxable_amount
            breakdown["by_rate"][rate_key]["tax_amount"] += item.tax_amount
        
        # Calculate totals
        total_tax = sum(
            v["tax_amount"] for v in breakdown["by_rate"].values()
        )
        
        if is_inter_state:
            breakdown["totals"]["igst"] = total_tax
        else:
            # 50/50 split for CGST/SGST
            half = (total_tax / 2).quantize(Decimal("0.01"), ROUND_HALF_UP)
            breakdown["totals"]["cgst"] = half
            breakdown["totals"]["sgst"] = total_tax - half
        
        return breakdown
    
    def generate_pdf(self, invoice: Invoice) -> bytes:
        """
        Generate PDF for invoice.
        
        Returns PDF bytes. Can be stored in S3.
        """
        # This is a placeholder - in production, use reportlab
        # to generate a proper GST-compliant invoice PDF
        
        # For now, return a simple text representation as bytes
        content = f"""
TAX INVOICE

Invoice Number: {invoice.invoice_number}
Invoice Date: {invoice.invoice_date}
Due Date: {invoice.due_date}

From:
{invoice.seller_name}
GSTIN: {invoice.seller_gstin}
{invoice.seller_address}

To:
{invoice.customer_name}
GSTIN: {invoice.customer_gstin or 'N/A'}
{invoice.customer_address or 'N/A'}

Items:
{'=' * 60}
"""
        
        for item in invoice.items:
            content += f"""
{item.description}
HSN: {item.hsn_code or 'N/A'}
Qty: {item.quantity} {item.unit}
Rate: ₹{item.unit_price}
Taxable: ₹{item.taxable_amount}
GST @{item.gst_rate}%: ₹{item.tax_amount}
Total: ₹{item.total_amount}
{'=' * 60}
"""
        
        content += f"""
Sub Total: ₹{invoice.subtotal}
CGST: ₹{invoice.cgst_amount}
SGST: ₹{invoice.sgst_amount}
IGST: ₹{invoice.igst_amount}
Total: ₹{invoice.total_amount}

Amount in Words: {invoice.amount_in_words}

Terms:
{invoice.terms or 'N/A'}
"""
        
        return content.encode("utf-8")
