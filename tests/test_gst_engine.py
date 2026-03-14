"""
Tests for the GST Calculation Engine.
All financial logic must be deterministic and never involve AI.
"""

import pytest
from decimal import Decimal
from app.core.gst_engine import (
    calculate_line_item_tax,
    calculate_invoice_tax,
)


class TestLineItemTax:
    def test_intra_state_rice_zero_gst(self):
        """Rice has 0% GST — no tax on intra-state supply."""
        result = calculate_line_item_tax(
            product_name="rice",
            hsn_code="1006",
            unit_price=1000.0,
            quantity=2,
            seller_state_code="27",
            buyer_state_code="27",
        )
        assert result.gst_rate == Decimal("0")
        assert result.cgst_amount == Decimal("0")
        assert result.sgst_amount == Decimal("0")
        assert result.igst_amount == Decimal("0")
        assert result.total_tax == Decimal("0")
        assert result.total_amount == Decimal("2000.00")
        assert result.is_inter_state is False

    def test_intra_state_sugar_5pct_gst(self):
        """Sugar has 5% GST — split as CGST 2.5% + SGST 2.5% intra-state."""
        result = calculate_line_item_tax(
            product_name="sugar",
            hsn_code="1701",
            unit_price=40.0,
            quantity=100,
            seller_state_code="27",
            buyer_state_code="27",
        )
        assert result.gst_rate == Decimal("5")
        assert result.taxable_amount == Decimal("4000.00")
        assert result.cgst_rate == Decimal("2.5")
        assert result.sgst_rate == Decimal("2.5")
        assert result.cgst_amount == Decimal("100.00")
        assert result.sgst_amount == Decimal("100.00")
        assert result.igst_amount == Decimal("0")
        assert result.total_tax == Decimal("200.00")
        assert result.total_amount == Decimal("4200.00")

    def test_inter_state_uses_igst(self):
        """Inter-state supply uses IGST instead of CGST+SGST."""
        result = calculate_line_item_tax(
            product_name="sugar",
            hsn_code="1701",
            unit_price=40.0,
            quantity=100,
            seller_state_code="27",  # Maharashtra
            buyer_state_code="09",  # Uttar Pradesh
        )
        assert result.is_inter_state is True
        assert result.igst_rate == Decimal("5")
        assert result.igst_amount == Decimal("200.00")
        assert result.cgst_amount == Decimal("0")
        assert result.sgst_amount == Decimal("0")

    def test_18pct_gst_product(self):
        """Soap (34xx) has 18% GST."""
        result = calculate_line_item_tax(
            product_name="soap",
            hsn_code="3401",
            unit_price=50.0,
            quantity=10,
            seller_state_code="27",
            buyer_state_code="27",
        )
        assert result.gst_rate == Decimal("18")
        assert result.taxable_amount == Decimal("500.00")
        assert result.cgst_rate == Decimal("9")
        assert result.sgst_rate == Decimal("9")
        assert result.total_tax == Decimal("90.00")
        assert result.total_amount == Decimal("590.00")

    def test_hsn_auto_lookup_from_product_name(self):
        """If hsn_code is None, should auto-lookup from product name."""
        result = calculate_line_item_tax(
            product_name="basmati rice",
            hsn_code=None,
            unit_price=2800.0,
            quantity=1,
            seller_state_code="27",
            buyer_state_code="27",
        )
        # Basmati rice maps to 100630 (5% GST for milled rice)
        assert result.hsn_code == "100630"

    def test_unknown_hsn_defaults_to_zero(self):
        """Unknown HSN should not crash and default to 0% GST."""
        result = calculate_line_item_tax(
            product_name="unknown widget",
            hsn_code="9999",
            unit_price=100.0,
            quantity=1,
            seller_state_code="27",
            buyer_state_code="27",
        )
        assert result.total_tax >= Decimal("0")

    def test_same_state_code_is_intra_state(self):
        """Same state codes should produce intra-state (CGST+SGST) result."""
        result = calculate_line_item_tax(
            product_name="tea",
            hsn_code="0902",
            unit_price=200.0,
            quantity=5,
            seller_state_code="29",
            buyer_state_code="29",
        )
        assert result.is_inter_state is False
        assert result.igst_amount == Decimal("0")
        assert result.cgst_amount > Decimal("0")
        assert result.sgst_amount > Decimal("0")

    def test_gstin_state_code_extraction(self):
        """State code can be extracted from full GSTIN (first 2 digits)."""
        result = calculate_line_item_tax(
            product_name="sugar",
            hsn_code="1701",
            unit_price=100.0,
            quantity=10,
            seller_state_code="27AAPFU0939F1ZV",  # Full GSTIN — Maharashtra
            buyer_state_code="27XXXXX0000X1ZV",   # Full GSTIN — Maharashtra
        )
        assert result.is_inter_state is False


class TestInvoiceTax:
    def test_invoice_aggregates_correctly(self):
        """Invoice total should be sum of all line items."""
        line_items = [
            {"product_name": "rice", "hsn_code": "1006", "unit_price": 50.0, "quantity": 10},
            {"product_name": "sugar", "hsn_code": "1701", "unit_price": 40.0, "quantity": 5},
        ]
        summary = calculate_invoice_tax(
            line_items=line_items,
            seller_state_code="27",
            buyer_state_code="27",
        )
        # Rice: 500 (0% GST), Sugar: 200 (5% GST = 10)
        assert summary.subtotal == Decimal("700.00")
        assert summary.cgst_amount == Decimal("5.00")   # 200 * 2.5%
        assert summary.sgst_amount == Decimal("5.00")   # 200 * 2.5%
        assert summary.total_tax == Decimal("10.00")
        assert summary.total_amount == Decimal("710.00")

    def test_invoice_inter_state_uses_igst(self):
        """Multi-item invoice between states should use IGST."""
        line_items = [
            {"product_name": "sugar", "hsn_code": "1701", "unit_price": 100.0, "quantity": 2},
        ]
        summary = calculate_invoice_tax(
            line_items=line_items,
            seller_state_code="27",
            buyer_state_code="09",
        )
        assert summary.is_inter_state is True
        assert summary.igst_amount == Decimal("10.00")
        assert summary.cgst_amount == Decimal("0")
        assert summary.sgst_amount == Decimal("0")

    def test_rounding_two_decimal_places(self):
        """All monetary values should be rounded to 2 decimal places."""
        line_items = [
            {"product_name": "sugar", "hsn_code": "1701", "unit_price": 3.33, "quantity": 3},
        ]
        summary = calculate_invoice_tax(
            line_items=line_items,
            seller_state_code="27",
            buyer_state_code="27",
        )
        # 3.33 * 3 = 9.99
        assert summary.subtotal == Decimal("9.99")
        # Check all amounts have at most 2 decimal places
        for field in (
            summary.subtotal, summary.cgst_amount, summary.sgst_amount,
            summary.total_tax, summary.total_amount
        ):
            assert field == field.quantize(Decimal("0.01"))
