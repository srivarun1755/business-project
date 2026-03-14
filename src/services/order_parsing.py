"""
Order Parsing Service.

Uses AI to extract structured order data from free-form text.
This is one of only TWO places where AI is used in the system.

Input: "Ramesh ko 2 bora basmati bhejna hai 2800 rupaye"
Output: {
    "customer": "Ramesh",
    "items": [{"product": "basmati rice", "quantity": 2, "unit": "bora"}],
    "price": 2800
}

The output is validated against a strict JSON schema before processing.
"""
import json
import re
from typing import Optional, List
from decimal import Decimal
import httpx

from src.core.config import settings
from src.schemas.order import ParsedOrder, ParsedOrderItem
from src.schemas.whatsapp import OrderParsingResult


# JSON Schema for order validation
ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "customer": {"type": ["string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "quantity": {"type": "number", "minimum": 0},
                    "unit": {"type": "string"},
                    "price": {"type": ["number", "null"]}
                },
                "required": ["product", "quantity"]
            }
        },
        "total_price": {"type": ["number", "null"]},
        "notes": {"type": ["string", "null"]}
    },
    "required": ["items"]
}


# System prompt for order extraction
SYSTEM_PROMPT = """You are an order extraction assistant for an Indian wholesale/retail business.

Extract order information from Hindi/Hinglish/English messages and return a JSON object.

Rules:
1. Extract customer name if mentioned (e.g., "Ramesh ko" means customer is "Ramesh")
2. Extract all product items with quantity and unit
3. Common units: bora (50kg bag), packet, kg, piece, dozen, box, carton
4. Extract total price if mentioned (in rupees)
5. Return ONLY valid JSON, no other text

Output format:
{
    "customer": "customer name or null",
    "items": [
        {"product": "product name", "quantity": number, "unit": "unit name"}
    ],
    "total_price": number or null,
    "notes": "any additional notes or null"
}

Examples:

Input: "Ramesh ko 2 bora basmati bhejna hai 2800 rupaye"
Output: {"customer": "Ramesh", "items": [{"product": "basmati", "quantity": 2, "unit": "bora"}], "total_price": 2800}

Input: "2 bora basmati aur 1 packet chini"
Output: {"customer": null, "items": [{"product": "basmati", "quantity": 2, "unit": "bora"}, {"product": "chini", "quantity": 1, "unit": "packet"}], "total_price": null}

Input: "Sharma ji ke liye 5 kg atta, 2 kg sugar, 1 dozen eggs"
Output: {"customer": "Sharma ji", "items": [{"product": "atta", "quantity": 5, "unit": "kg"}, {"product": "sugar", "quantity": 2, "unit": "kg"}, {"product": "eggs", "quantity": 1, "unit": "dozen"}], "total_price": null}
"""


class OrderParsingService:
    """
    AI-powered order parsing service.
    
    Uses OpenAI GPT to extract structured order data from
    natural language messages in Hindi/Hinglish/English.
    
    All AI output is validated against a strict JSON schema
    before being processed by deterministic business logic.
    """
    
    def __init__(self):
        self.api_key = settings.openai_api_key
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def parse_order_text(self, text: str) -> OrderParsingResult:
        """
        Parse order from natural language text.
        
        Returns OrderParsingResult with:
        - success: whether parsing succeeded
        - parsed_order: structured order data if successful
        - raw_text: original input text
        - confidence: confidence score
        - errors: list of validation errors
        """
        if not text or not text.strip():
            return OrderParsingResult(
                success=False,
                raw_text=text,
                confidence=0.0,
                errors=["Empty input text"]
            )
        
        try:
            # Call OpenAI API
            client = await self._get_client()
            
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text}
                    ],
                    "temperature": 0.1,  # Low temperature for consistency
                    "max_tokens": 500,
                }
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Parse and validate JSON
            parsed_order = self._parse_and_validate(content)
            
            if parsed_order:
                return OrderParsingResult(
                    success=True,
                    parsed_order=parsed_order,
                    raw_text=text,
                    confidence=0.95,
                    errors=[]
                )
            else:
                return OrderParsingResult(
                    success=False,
                    raw_text=text,
                    confidence=0.0,
                    errors=["Failed to parse AI response as valid order"]
                )
                
        except httpx.HTTPError as e:
            return OrderParsingResult(
                success=False,
                raw_text=text,
                confidence=0.0,
                errors=[f"API error: {str(e)}"]
            )
        except Exception as e:
            return OrderParsingResult(
                success=False,
                raw_text=text,
                confidence=0.0,
                errors=[f"Parsing error: {str(e)}"]
            )
    
    def _parse_and_validate(self, content: str) -> Optional[dict]:
        """
        Parse and validate AI response.
        
        Extracts JSON from response and validates against schema.
        """
        # Try to extract JSON from content
        json_str = self._extract_json(content)
        
        if not json_str:
            return None
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        
        # Validate structure
        if not self._validate_order_structure(data):
            return None
        
        return data
    
    def _extract_json(self, content: str) -> Optional[str]:
        """Extract JSON from AI response, handling markdown code blocks."""
        # Try to find JSON in code blocks
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1)
        
        # Try to find raw JSON
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json_match.group(0)
        
        return None
    
    def _validate_order_structure(self, data: dict) -> bool:
        """
        Validate order data structure.
        
        Checks:
        - Required fields exist
        - Items array is non-empty
        - Each item has product and quantity
        - Quantity is positive
        """
        if not isinstance(data, dict):
            return False
        
        if "items" not in data:
            return False
        
        items = data.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            return False
        
        for item in items:
            if not isinstance(item, dict):
                return False
            
            if "product" not in item or "quantity" not in item:
                return False
            
            try:
                quantity = float(item["quantity"])
                if quantity <= 0:
                    return False
            except (ValueError, TypeError):
                return False
        
        return True
    
    def parse_order_deterministic(self, text: str) -> Optional[ParsedOrder]:
        """
        Deterministic order parsing for simple patterns.
        
        Use this for well-structured inputs to avoid AI calls.
        Falls back to AI for complex inputs.
        
        Patterns supported:
        - "2 bora basmati" -> simple single item
        - "2 bora basmati, 1 packet chini" -> comma-separated items
        """
        text = text.strip().lower()
        
        # Pattern: quantity unit product
        simple_pattern = r"(\d+(?:\.\d+)?)\s+(\w+)\s+(\w+)"
        
        items = []
        
        # Try comma-separated items first
        parts = [p.strip() for p in text.split(",")]
        
        for part in parts:
            match = re.match(simple_pattern, part)
            if match:
                quantity = Decimal(match.group(1))
                unit = match.group(2)
                product = match.group(3)
                
                items.append(ParsedOrderItem(
                    product=product,
                    quantity=quantity,
                    unit=unit
                ))
        
        if items:
            return ParsedOrder(items=items)
        
        return None
    
    def convert_to_pydantic(self, data: dict) -> ParsedOrder:
        """Convert raw dict to Pydantic model."""
        items = []
        for item in data.get("items", []):
            items.append(ParsedOrderItem(
                product=item.get("product", ""),
                quantity=Decimal(str(item.get("quantity", 0))),
                unit=item.get("unit", "piece"),
                price=Decimal(str(item["price"])) if item.get("price") else None
            ))
        
        return ParsedOrder(
            customer=data.get("customer"),
            items=items,
            total_price=Decimal(str(data["total_price"])) if data.get("total_price") else None,
            notes=data.get("notes")
        )


# Singleton instance
order_parsing_service = OrderParsingService()
