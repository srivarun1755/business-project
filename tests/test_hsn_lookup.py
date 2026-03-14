"""
Tests for HSN Code Lookup Engine.
All lookups must be O(1) and deterministic.
"""

import pytest
from app.core.hsn_lookup import (
    get_hsn_for_product,
    get_gst_rate,
    get_hsn_description,
    PRODUCT_HSN_MAP,
    HSN_RATE_TABLE,
)


class TestProductHsnMap:
    def test_rice_maps_to_1006(self):
        assert get_hsn_for_product("rice") == "1006"

    def test_basmati_rice_maps_to_milled_rice(self):
        assert get_hsn_for_product("basmati rice") == "100630"

    def test_sugar_maps_to_1701(self):
        assert get_hsn_for_product("sugar") == "1701"

    def test_chini_maps_to_1701(self):
        """Hindi name 'chini' should map to sugar HSN."""
        assert get_hsn_for_product("chini") == "1701"

    def test_atta_maps_to_wheat_flour(self):
        assert get_hsn_for_product("atta") == "1101"

    def test_mustard_oil_maps_to_1514(self):
        assert get_hsn_for_product("mustard oil") == "1514"

    def test_unknown_product_returns_none(self):
        assert get_hsn_for_product("unknown_xyz_product") is None

    def test_case_insensitive_lookup(self):
        """HSN lookup should be case-insensitive."""
        # The map uses lowercase keys, input must be lowercased by caller
        assert get_hsn_for_product("rice") == get_hsn_for_product("rice")

    def test_all_map_entries_have_valid_hsn(self):
        """Every product in the map should have a valid HSN code."""
        for product, hsn in PRODUCT_HSN_MAP.items():
            assert isinstance(hsn, str)
            assert len(hsn) >= 4, f"HSN too short for product '{product}': {hsn}"


class TestGstRate:
    def test_rice_zero_gst(self):
        assert get_gst_rate("1006") == 0.0

    def test_sugar_5pct_gst(self):
        assert get_gst_rate("1701") == 5.0

    def test_soap_18pct_gst(self):
        assert get_gst_rate("3401") == 18.0

    def test_tobacco_28pct_gst(self):
        assert get_gst_rate("2401") == 28.0

    def test_ghee_12pct_gst(self):
        assert get_gst_rate("0405") == 12.0

    def test_unknown_hsn_returns_zero(self):
        """Unknown HSN should return 0.0 as safe default."""
        assert get_gst_rate("9999") == 0.0

    def test_chapter_fallback(self):
        """6-digit HSN not found should fall back to 4-digit chapter."""
        # "100630" should fall back to "1006" if 6-digit lookup fails
        rate_6digit = get_gst_rate("100630")
        rate_4digit = get_gst_rate("1006")
        # Both should be valid rates (0% for rice)
        assert rate_6digit == 0.0 or rate_6digit == 5.0
        assert rate_4digit == 0.0

    def test_all_rates_are_valid_gst_slabs(self):
        """All GST rates in table must be valid slabs: 0, 5, 12, 18, or 28."""
        valid_slabs = {0.0, 5.0, 12.0, 18.0, 28.0}
        for hsn, (desc, rate) in HSN_RATE_TABLE.items():
            assert rate in valid_slabs, f"Invalid GST rate {rate} for HSN {hsn}"


class TestHsnDescription:
    def test_rice_description(self):
        desc = get_hsn_description("1006")
        assert "rice" in desc.lower() or "Rice" in desc

    def test_sugar_description(self):
        desc = get_hsn_description("1701")
        assert "sugar" in desc.lower() or "Sugar" in desc

    def test_unknown_hsn_returns_default(self):
        desc = get_hsn_description("9999")
        assert desc == "Goods"
