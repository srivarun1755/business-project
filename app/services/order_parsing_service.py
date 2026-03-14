"""
Order Parsing Service
=====================
AI Model 2: LLM-based extraction of structured order JSON from free-form text.

Strict JSON schema validation ensures that only well-formed orders
proceed to downstream business logic. Invalid LLM outputs are rejected.

Cost target: <$0.002 per order.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# JSON Schema for order output (strict Pydantic validation)
# ------------------------------------------------------------------

class OrderItem(BaseModel):
    product: str = Field(..., min_length=1, max_length=200)
    quantity: float = Field(..., gt=0)
    unit: str = Field(default="piece", max_length=50)


class ParsedOrder(BaseModel):
    customer: str | None = None
    items: list[OrderItem] = Field(..., min_length=1)
    price: float | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def items_not_empty(self) -> "ParsedOrder":
        if not self.items:
            raise ValueError("Order must contain at least one item")
        return self


# ------------------------------------------------------------------
# LLM System Prompt (deterministic template)
# ------------------------------------------------------------------

SYSTEM_PROMPT = """You are an order extraction assistant for Indian grocery businesses.

Extract structured order information from the user's message.

Return ONLY valid JSON (no markdown, no explanation) matching this exact schema:
{
  "customer": "<customer name or null>",
  "items": [
    {
      "product": "<canonical product name in English>",
      "quantity": <number>,
      "unit": "<unit: kg/bora/packet/litre/piece/dozen/bag/box>"
    }
  ],
  "price": <total price in rupees or null>,
  "notes": "<any delivery or special instructions or null>"
}

Rules:
- Translate Hindi/Hinglish product names to English (e.g., "chini" → "sugar", "basmati" → "basmati rice")
- Convert Hindi number words to digits (e.g., "ek" → 1, "do" → 2, "teen" → 3)
- "bora" = large gunny bag (typically 25–50 kg); keep unit as "bora"
- If price is not mentioned, set to null
- NEVER include any fields outside the schema"""


class OrderParsingService:
    """
    Converts free-form Hindi/Hinglish order text to structured JSON
    using an LLM with strict schema validation.

    The LLM is the only AI component in the order pipeline.
    All downstream processing is deterministic.
    """

    async def parse(self, text: str) -> ParsedOrder:
        """
        Parse raw order text into a validated ParsedOrder object.

        Raises ValueError if the LLM output fails schema validation
        (caller should request clarification from the customer).
        """
        if not text or not text.strip():
            raise ValueError("Empty order text")

        raw_json = await self._call_llm(text)
        return self._validate(raw_json)

    async def _call_llm(self, text: str) -> str:
        """Call the configured LLM API and return the raw JSON string."""
        if not settings.llm_api_key:
            logger.warning("LLM API key not configured; returning stub response")
            return json.dumps({"items": [{"product": text, "quantity": 1, "unit": "piece"}]})

        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_tokens": settings.llm_max_tokens,
            "temperature": 0,  # deterministic output
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                settings.llm_api_url,
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        raw = data["choices"][0]["message"]["content"].strip()
        logger.debug("LLM order response: %s", raw[:200])
        return raw

    def _validate(self, raw_json: str) -> ParsedOrder:
        """
        Strictly validate LLM output against the ParsedOrder schema.
        Raises ValueError on any schema violation.
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

        try:
            return ParsedOrder.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Order schema validation failed: {exc}") from exc


class LLMDisambiguationService:
    """
    Step 4 of the canonicalization pipeline.
    Used only when all deterministic matching methods fail (<1% of orders).
    """

    async def disambiguate(
        self, raw_token: str, candidates: list[dict[str, str]]
    ) -> str | None:
        """
        Ask the LLM to select the best matching product from candidates.

        Parameters
        ----------
        raw_token : The unrecognised product name from the order
        candidates : List of {"product_id": ..., "name": ...} dicts

        Returns
        -------
        product_id of the best match, or None if LLM cannot determine.
        """
        if not candidates:
            return None

        if not settings.llm_api_key:
            return None

        numbered = "\n".join(
            f"{i + 1}. {c['name']} (id: {c['product_id']})"
            for i, c in enumerate(candidates)
        )
        prompt = (
            f"User ordered: \"{raw_token}\"\n\n"
            f"Available products:\n{numbered}\n\n"
            "Which product number best matches the order? "
            "Reply with ONLY the product_id. If none match, reply 'none'."
        )

        payload = {
            "model": settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a product matching assistant for an Indian grocery store. "
                        "Select the best matching product for the given order token."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 64,
            "temperature": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    settings.llm_api_url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            answer = data["choices"][0]["message"]["content"].strip().lower()
            if answer == "none":
                return None

            # Find returned product_id in candidates
            valid_ids = {c["product_id"] for c in candidates}
            if answer in valid_ids:
                return answer

            logger.warning(
                "LLM disambiguation returned unknown id: %s for token: %s",
                answer, raw_token,
            )
            return None

        except Exception as exc:
            logger.error("LLM disambiguation failed: %s", exc)
            return None
