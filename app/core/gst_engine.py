"""
GST Calculation Engine
======================
Deterministic GST calculation based on HSN codes and state codes.

Rules:
- Intra-state supply: CGST + SGST (each = GST rate / 2)
- Inter-state supply: IGST (= GST rate)
- Seller and buyer state compared using 2-digit state code

AI is NEVER used for tax calculations.
All logic is implemented via explicit tax tables.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from app.core.hsn_lookup import get_gst_rate, get_hsn_for_product, get_hsn_description


# Indian state codes (GST state code → state name)
STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh (new)",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}


def _extract_state_code(gstin_or_state_code: str) -> str:
    """
    Extract 2-digit state code from GSTIN (first 2 digits)
    or return the 2-digit state code directly.
    """
    if not gstin_or_state_code:
        return ""
    code = gstin_or_state_code.strip()
    if len(code) >= 15:
        # Full GSTIN: first 2 digits are state code
        return code[:2]
    if len(code) == 2:
        return code
    return code[:2]


@dataclass
class TaxBreakdown:
    """Immutable tax breakdown for a single line item."""

    hsn_code: str
    hsn_description: str
    taxable_amount: Decimal
    gst_rate: Decimal
    is_inter_state: bool
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_tax: Decimal
    total_amount: Decimal


@dataclass
class InvoiceTaxSummary:
    """Aggregated tax summary for an entire invoice."""

    subtotal: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_tax: Decimal
    total_amount: Decimal
    is_inter_state: bool
    line_items: list[TaxBreakdown]


def _round2(value: Decimal) -> Decimal:
    """Round to 2 decimal places using banker's rounding as per GST rules."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_line_item_tax(
    *,
    product_name: str,
    hsn_code: str | None,
    unit_price: float,
    quantity: int,
    seller_state_code: str,
    buyer_state_code: str,
) -> TaxBreakdown:
    """
    Calculate GST for a single order line item.

    Parameters
    ----------
    product_name:
        Canonical product name (used for HSN lookup if hsn_code is not provided).
    hsn_code:
        HSN code string. If None, auto-looked up from product_name.
    unit_price:
        Price per unit (before tax).
    quantity:
        Number of units.
    seller_state_code:
        2-digit GST state code of the seller.
    buyer_state_code:
        2-digit GST state code of the buyer.

    Returns
    -------
    TaxBreakdown with all computed values.
    """
    # 1. Resolve HSN code
    resolved_hsn = hsn_code or get_hsn_for_product(product_name) or "9999"
    description = get_hsn_description(resolved_hsn)

    # 2. Fetch GST rate from tax table (O(1))
    raw_gst_rate = get_gst_rate(resolved_hsn)
    gst_rate = Decimal(str(raw_gst_rate))

    # 3. Compute taxable amount
    taxable_amount = _round2(Decimal(str(unit_price)) * Decimal(str(quantity)))

    # 4. Determine intra-state vs inter-state
    seller_code = _extract_state_code(seller_state_code)
    buyer_code = _extract_state_code(buyer_state_code)
    is_inter_state = bool(seller_code and buyer_code and seller_code != buyer_code)

    # 5. Compute tax components
    if is_inter_state:
        igst_rate = gst_rate
        cgst_rate = Decimal("0")
        sgst_rate = Decimal("0")
        igst_amount = _round2(taxable_amount * igst_rate / Decimal("100"))
        cgst_amount = Decimal("0")
        sgst_amount = Decimal("0")
    else:
        igst_rate = Decimal("0")
        cgst_rate = _round2(gst_rate / Decimal("2"))
        sgst_rate = _round2(gst_rate / Decimal("2"))
        cgst_amount = _round2(taxable_amount * cgst_rate / Decimal("100"))
        sgst_amount = _round2(taxable_amount * sgst_rate / Decimal("100"))
        igst_amount = Decimal("0")

    total_tax = cgst_amount + sgst_amount + igst_amount
    total_amount = taxable_amount + total_tax

    return TaxBreakdown(
        hsn_code=resolved_hsn,
        hsn_description=description,
        taxable_amount=taxable_amount,
        gst_rate=gst_rate,
        is_inter_state=is_inter_state,
        cgst_rate=cgst_rate,
        sgst_rate=sgst_rate,
        igst_rate=igst_rate,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        total_tax=total_tax,
        total_amount=total_amount,
    )


def calculate_invoice_tax(
    *,
    line_items: list[dict],
    seller_state_code: str,
    buyer_state_code: str,
) -> InvoiceTaxSummary:
    """
    Calculate GST for an entire invoice.

    Parameters
    ----------
    line_items:
        List of dicts with keys: product_name, hsn_code (optional),
        unit_price, quantity.
    seller_state_code:
        2-digit GST state code or full GSTIN of seller.
    buyer_state_code:
        2-digit GST state code or full GSTIN of buyer.

    Returns
    -------
    InvoiceTaxSummary with aggregated tax breakdown.
    """
    breakdowns: list[TaxBreakdown] = []
    total_cgst = Decimal("0")
    total_sgst = Decimal("0")
    total_igst = Decimal("0")
    total_subtotal = Decimal("0")

    for item in line_items:
        breakdown = calculate_line_item_tax(
            product_name=item.get("product_name", ""),
            hsn_code=item.get("hsn_code"),
            unit_price=item["unit_price"],
            quantity=item["quantity"],
            seller_state_code=seller_state_code,
            buyer_state_code=buyer_state_code,
        )
        breakdowns.append(breakdown)
        total_subtotal += breakdown.taxable_amount
        total_cgst += breakdown.cgst_amount
        total_sgst += breakdown.sgst_amount
        total_igst += breakdown.igst_amount

    total_tax = total_cgst + total_sgst + total_igst
    total_amount = total_subtotal + total_tax

    is_inter_state = any(b.is_inter_state for b in breakdowns)

    return InvoiceTaxSummary(
        subtotal=_round2(total_subtotal),
        cgst_amount=_round2(total_cgst),
        sgst_amount=_round2(total_sgst),
        igst_amount=_round2(total_igst),
        total_tax=_round2(total_tax),
        total_amount=_round2(total_amount),
        is_inter_state=is_inter_state,
        line_items=breakdowns,
    )
