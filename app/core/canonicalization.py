"""
Product Canonicalization Engine
================================
Resolves inconsistent product names from WhatsApp orders to canonical
product IDs using a 4-step deterministic fuzzy matching pipeline.

Pipeline:
    Step 1 — Exact alias lookup        O(1)  HashMap
    Step 2 — Levenshtein distance      O(m)  m = alias count
    Step 3 — Phonetic matching         O(1)  HashMap keyed by phonetic code
    Step 4 — LLM disambiguation        rare  <1% of orders

AI is only invoked in Step 4 and only when all deterministic methods fail.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

import Levenshtein
import jellyfish

logger = logging.getLogger(__name__)

# Maximum Levenshtein distance to accept a match
MAX_LEVENSHTEIN_DISTANCE = 2


@dataclass
class CanonicalMatch:
    product_id: str
    product_name: str
    matched_alias: str
    match_method: str  # "exact" | "levenshtein" | "phonetic" | "llm"
    confidence: float  # 0.0 – 1.0


class ProductCanonicalizationEngine:
    """
    Stateful canonicalization engine.

    Holds two in-memory hash maps:
        alias_map     : HashMap<alias_lower, (product_id, product_name)>
        phonetic_map  : HashMap<soundex_code, list[(product_id, alias, product_name)]>

    Both are loaded from the database at startup and refreshed on demand.
    Lookups are O(1) for exact and phonetic; O(m) for Levenshtein.
    """

    def __init__(self) -> None:
        # alias_lower → (product_id, canonical_name)
        self._alias_map: dict[str, tuple[str, str]] = {}
        # soundex_code → list of (product_id, alias, canonical_name)
        self._phonetic_map: dict[str, list[tuple[str, str, str]]] = {}
        # all aliases (for Levenshtein scan)
        self._aliases: list[str] = []

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def load_aliases(
        self, aliases: list[tuple[str, str, str]]
    ) -> None:
        """
        Populate the engine from a list of (alias, product_id, product_name).
        Call once at startup and after any alias changes.
        """
        self._alias_map.clear()
        self._phonetic_map.clear()
        self._aliases.clear()

        for alias, product_id, product_name in aliases:
            normalised = _normalise(alias)
            self._alias_map[normalised] = (product_id, product_name)
            self._aliases.append(normalised)

            # Build phonetic index
            code = _soundex(normalised)
            if code not in self._phonetic_map:
                self._phonetic_map[code] = []
            self._phonetic_map[code].append((product_id, normalised, product_name))

        logger.info(
            "Canonicalization engine loaded %d aliases", len(self._alias_map)
        )

    def add_alias(self, alias: str, product_id: str, product_name: str) -> None:
        """Incrementally add a single alias without full reload."""
        normalised = _normalise(alias)
        self._alias_map[normalised] = (product_id, product_name)
        if normalised not in self._aliases:
            self._aliases.append(normalised)
        code = _soundex(normalised)
        if code not in self._phonetic_map:
            self._phonetic_map[code] = []
        self._phonetic_map[code].append((product_id, normalised, product_name))

    # ------------------------------------------------------------------
    # Matching pipeline
    # ------------------------------------------------------------------

    def resolve(self, raw_name: str) -> Optional[CanonicalMatch]:
        """
        Resolve a raw product name to a canonical product.
        Returns None if all steps fail (caller should escalate to LLM).
        """
        token = _normalise(raw_name)

        # Step 1 — Exact alias lookup O(1)
        match = self._exact_match(token)
        if match:
            return match

        # Step 2 — Levenshtein distance O(m)
        match = self._levenshtein_match(token)
        if match:
            return match

        # Step 3 — Phonetic matching O(1)
        match = self._phonetic_match(token)
        if match:
            return match

        # All deterministic steps failed → caller should use LLM (Step 4)
        return None

    def _exact_match(self, token: str) -> Optional[CanonicalMatch]:
        """Step 1: O(1) HashMap lookup."""
        result = self._alias_map.get(token)
        if result:
            product_id, product_name = result
            return CanonicalMatch(
                product_id=product_id,
                product_name=product_name,
                matched_alias=token,
                match_method="exact",
                confidence=1.0,
            )
        return None

    def _levenshtein_match(self, token: str) -> Optional[CanonicalMatch]:
        """
        Step 2: Find closest alias by Levenshtein distance.
        Accepts match if distance ≤ MAX_LEVENSHTEIN_DISTANCE.
        Complexity: O(m) where m = number of aliases.
        """
        best_distance = MAX_LEVENSHTEIN_DISTANCE + 1
        best_alias: Optional[str] = None

        for alias in self._aliases:
            dist = Levenshtein.distance(token, alias)
            if dist < best_distance:
                best_distance = dist
                best_alias = alias

        if best_alias and best_distance <= MAX_LEVENSHTEIN_DISTANCE:
            product_id, product_name = self._alias_map[best_alias]
            confidence = max(0.5, 1.0 - best_distance * 0.2)
            return CanonicalMatch(
                product_id=product_id,
                product_name=product_name,
                matched_alias=best_alias,
                match_method="levenshtein",
                confidence=confidence,
            )
        return None

    def _phonetic_match(self, token: str) -> Optional[CanonicalMatch]:
        """
        Step 3: Phonetic matching using Soundex.
        Complexity: O(1) HashMap lookup by phonetic code.
        """
        code = _soundex(token)
        candidates = self._phonetic_map.get(code, [])
        if candidates:
            # Return first match (all share the same soundex — pick shortest alias)
            candidates_sorted = sorted(candidates, key=lambda x: len(x[1]))
            product_id, matched_alias, product_name = candidates_sorted[0]
            return CanonicalMatch(
                product_id=product_id,
                product_name=product_name,
                matched_alias=matched_alias,
                match_method="phonetic",
                confidence=0.7,
            )
        return None


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

_HINDI_DIGIT_MAP = {
    "ek": "1",
    "do": "2",
    "teen": "3",
    "char": "4",
    "paanch": "5",
    "chhe": "6",
    "saat": "7",
    "aath": "8",
    "nau": "9",
    "das": "10",
}


def _normalise(text: str) -> str:
    """
    Normalise a product name for matching:
    - lowercase
    - strip leading/trailing whitespace
    - remove numeric prefixes (e.g. "1 bora" → "bora")
    - collapse multiple spaces
    - remove special characters except spaces and hyphens
    """
    text = text.strip().lower()
    # Replace Hindi digit words with numerals
    for word, digit in _HINDI_DIGIT_MAP.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    # Remove leading numerals (e.g., "2 bora" → "bora")
    text = re.sub(r"^\d+\s*", "", text)
    # Remove special characters
    text = re.sub(r"[^a-z0-9 \-]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _soundex(text: str) -> str:
    """
    Compute Soundex phonetic code for a text string.
    Multi-word tokens use the Soundex of the first word.
    """
    if not text:
        return ""
    first_word = text.split()[0] if text.split() else text
    try:
        return jellyfish.soundex(first_word)
    except Exception:
        return first_word[:1].upper() + "000"


# Module-level singleton (loaded per-tenant at startup)
_engines: dict[str, ProductCanonicalizationEngine] = {}


def get_engine(tenant_id: str) -> ProductCanonicalizationEngine:
    """Return the canonicalization engine for a tenant, creating if needed."""
    if tenant_id not in _engines:
        _engines[tenant_id] = ProductCanonicalizationEngine()
    return _engines[tenant_id]


def invalidate_engine(tenant_id: str) -> None:
    """Remove cached engine for a tenant (force reload on next request)."""
    _engines.pop(tenant_id, None)
