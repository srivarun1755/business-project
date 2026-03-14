"""
Tests for Order Parsing Service.
JSON schema validation must reject malformed LLM outputs.
"""

import json
import pytest
from app.services.order_parsing_service import OrderParsingService, ParsedOrder


class TestOrderParsing:
    def setup_method(self):
        self.svc = OrderParsingService()

    def test_validate_valid_order(self):
        raw = json.dumps({
            "customer": "Ramesh",
            "items": [
                {"product": "basmati rice", "quantity": 2, "unit": "bora"}
            ],
            "price": 2800.0,
        })
        order = self.svc._validate(raw)
        assert isinstance(order, ParsedOrder)
        assert order.customer == "Ramesh"
        assert len(order.items) == 1
        assert order.items[0].product == "basmati rice"
        assert order.items[0].quantity == 2
        assert order.items[0].unit == "bora"
        assert order.price == 2800.0

    def test_validate_multi_item_order(self):
        raw = json.dumps({
            "items": [
                {"product": "basmati rice", "quantity": 2, "unit": "bora"},
                {"product": "sugar", "quantity": 1, "unit": "packet"},
            ],
        })
        order = self.svc._validate(raw)
        assert len(order.items) == 2

    def test_validate_rejects_invalid_json(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            self.svc._validate("this is not json")

    def test_validate_rejects_empty_items(self):
        raw = json.dumps({"customer": "Ramesh", "items": []})
        with pytest.raises(ValueError):
            self.svc._validate(raw)

    def test_validate_rejects_negative_quantity(self):
        raw = json.dumps({
            "items": [{"product": "rice", "quantity": -5, "unit": "kg"}]
        })
        with pytest.raises(ValueError):
            self.svc._validate(raw)

    def test_validate_rejects_zero_quantity(self):
        raw = json.dumps({
            "items": [{"product": "rice", "quantity": 0, "unit": "kg"}]
        })
        with pytest.raises(ValueError):
            self.svc._validate(raw)

    def test_validate_rejects_empty_product(self):
        raw = json.dumps({
            "items": [{"product": "", "quantity": 1, "unit": "kg"}]
        })
        with pytest.raises(ValueError):
            self.svc._validate(raw)

    def test_validate_optional_fields_nullable(self):
        """customer, price, notes are optional."""
        raw = json.dumps({
            "items": [{"product": "sugar", "quantity": 5, "unit": "kg"}]
        })
        order = self.svc._validate(raw)
        assert order.customer is None
        assert order.price is None
        assert order.notes is None

    def test_validate_unit_defaults_to_piece(self):
        """Unit should default to 'piece' if not specified."""
        raw = json.dumps({
            "items": [{"product": "biscuit", "quantity": 2}]
        })
        order = self.svc._validate(raw)
        assert order.items[0].unit == "piece"

    def test_validate_rejects_missing_items_key(self):
        raw = json.dumps({"customer": "Ramesh"})
        with pytest.raises(ValueError):
            self.svc._validate(raw)

    def test_validate_accepts_float_quantity(self):
        """Fractional quantities (e.g., 2.5 kg) should be valid."""
        raw = json.dumps({
            "items": [{"product": "oil", "quantity": 2.5, "unit": "litre"}]
        })
        order = self.svc._validate(raw)
        assert order.items[0].quantity == 2.5

    @pytest.mark.asyncio
    async def test_parse_raises_on_empty_text(self):
        with pytest.raises(ValueError, match="Empty order text"):
            await self.svc.parse("")

    @pytest.mark.asyncio
    async def test_parse_raises_on_whitespace_only(self):
        with pytest.raises(ValueError, match="Empty order text"):
            await self.svc.parse("   ")
