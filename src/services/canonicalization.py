"""
Product Canonicalization Service.

Deterministic fuzzy matching pipeline to resolve inconsistent product names
to canonical products. AI is NOT used here - all matching is deterministic.

Pipeline:
1. Exact alias lookup (O(1) via Redis/HashMap)
2. Fuzzy matching using edit distance
3. Phonetic matching for Hindi/Hinglish
4. Fallback to human review

Examples of variations handled:
- "bora" / "boraa" / "1 bora" / "ek bora" -> "basmati rice (50kg bag)"
- "chini" / "cheeni" / "sugar" -> "sugar"
"""
import re
from typing import Optional, List, Tuple
from decimal import Decimal
from dataclasses import dataclass
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product, ProductAlias
from src.core.redis_cache import RedisCache
from src.schemas.product import ProductMatchResult


@dataclass
class MatchCandidate:
    """Internal match candidate."""
    product_id: str
    canonical_name: str
    alias: str
    score: float
    match_type: str  # exact, fuzzy, phonetic


class ProductCanonicalizationService:
    """
    Deterministic product name canonicalization.
    Uses a multi-stage matching pipeline for high accuracy.
    """
    
    # Hindi/Hinglish number words mapping
    HINDI_NUMBERS = {
        "ek": "1", "do": "2", "teen": "3", "char": "4", "paanch": "5",
        "chhe": "6", "saat": "7", "aath": "8", "nau": "9", "das": "10",
        "gyarah": "11", "barah": "12", "terah": "13", "chaudah": "14",
        "pandrah": "15", "solah": "16", "satrah": "17", "atharah": "18",
        "unnis": "19", "bees": "20", "pacchees": "25", "tees": "30",
        "pachaas": "50", "sau": "100", "hazaar": "1000",
    }
    
    # Common unit aliases
    UNIT_ALIASES = {
        "bora": ["bora", "boraa", "bori", "bag", "sack"],
        "kg": ["kg", "kilo", "kilogram", "kgs"],
        "g": ["g", "gram", "grams", "gm"],
        "packet": ["packet", "pkt", "pack", "pakit"],
        "piece": ["piece", "pc", "pcs", "pieces", "aad", "ada"],
        "dozen": ["dozen", "darjan", "drz"],
        "litre": ["litre", "liter", "l", "lt"],
        "bottle": ["bottle", "bottal", "botal"],
        "box": ["box", "dabba", "carton"],
        "quintal": ["quintal", "quintle", "q"],
    }
    
    # Phonetic replacements for Hindi/Hinglish
    PHONETIC_RULES = [
        (r"aa", "a"),
        (r"ee", "i"),
        (r"oo", "u"),
        (r"ph", "f"),
        (r"gh", "g"),
        (r"ch", "c"),
        (r"sh", "s"),
        (r"th", "t"),
        (r"dh", "d"),
        (r"bh", "b"),
        (r"kh", "k"),
    ]
    
    # Minimum confidence thresholds
    EXACT_MATCH_THRESHOLD = 1.0
    FUZZY_MATCH_THRESHOLD = 0.85
    PHONETIC_MATCH_THRESHOLD = 0.80
    
    def __init__(self, db_session: AsyncSession, redis_cache: RedisCache):
        self.db = db_session
        self.cache = redis_cache
        self._alias_map: dict[str, str] = {}  # In-memory fallback
        self._product_names: List[Tuple[str, str]] = []  # (alias, product_id)
    
    async def initialize(self) -> None:
        """Load product aliases into memory and Redis cache."""
        # Load all active products and their aliases
        query = (
            select(Product, ProductAlias)
            .join(ProductAlias, Product.id == ProductAlias.product_id)
            .where(Product.is_active == True)
        )
        result = await self.db.execute(query)
        
        aliases_to_cache = {}
        for product, alias in result.fetchall():
            normalized_alias = self._normalize_text(alias.alias)
            aliases_to_cache[normalized_alias] = product.id
            self._alias_map[normalized_alias] = product.id
            self._product_names.append((alias.alias, product.id))
        
        # Also add canonical names as aliases
        products_query = select(Product).where(Product.is_active == True)
        products_result = await self.db.execute(products_query)
        for product in products_result.scalars():
            normalized = self._normalize_text(product.canonical_name)
            aliases_to_cache[normalized] = product.id
            self._alias_map[normalized] = product.id
            self._product_names.append((product.canonical_name, product.id))
        
        # Bulk update Redis cache
        if aliases_to_cache:
            await self.cache.bulk_set_product_aliases(aliases_to_cache)
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for matching.
        - Lowercase
        - Remove extra whitespace
        - Convert Hindi numbers to digits
        - Remove common prefixes/suffixes
        """
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        
        # Convert Hindi number words to digits
        words = text.split()
        normalized_words = []
        for word in words:
            if word in self.HINDI_NUMBERS:
                normalized_words.append(self.HINDI_NUMBERS[word])
            else:
                normalized_words.append(word)
        
        return " ".join(normalized_words)
    
    def _apply_phonetic_rules(self, text: str) -> str:
        """Apply phonetic rules for Hindi/Hinglish matching."""
        result = text.lower()
        for pattern, replacement in self.PHONETIC_RULES:
            result = re.sub(pattern, replacement, result)
        return result
    
    def _extract_quantity_unit(self, text: str) -> Tuple[Optional[Decimal], Optional[str], str]:
        """
        Extract quantity and unit from text.
        Returns (quantity, unit, remaining_text).
        
        Examples:
        - "2 bora basmati" -> (2, "bora", "basmati")
        - "ek packet chini" -> (1, "packet", "chini")
        """
        text = self._normalize_text(text)
        
        # Pattern: number + unit + product
        quantity_pattern = r"^(\d+(?:\.\d+)?)\s*"
        match = re.match(quantity_pattern, text)
        
        quantity = None
        unit = None
        remaining = text
        
        if match:
            quantity = Decimal(match.group(1))
            remaining = text[match.end():].strip()
        
        # Check for unit in remaining text
        words = remaining.split()
        if words:
            first_word = words[0].lower()
            for canonical_unit, aliases in self.UNIT_ALIASES.items():
                if first_word in aliases:
                    unit = canonical_unit
                    remaining = " ".join(words[1:])
                    break
        
        return quantity, unit, remaining
    
    async def match_product(self, query: str) -> Optional[ProductMatchResult]:
        """
        Main matching method. Runs through the pipeline:
        1. Exact match (O(1))
        2. Fuzzy match
        3. Phonetic match
        
        Returns ProductMatchResult or None if no match found.
        """
        # Extract quantity and unit first
        quantity, unit, product_query = self._extract_quantity_unit(query)
        
        if not product_query:
            product_query = query
        
        normalized_query = self._normalize_text(product_query)
        
        # Step 1: Exact alias lookup (O(1))
        exact_match = await self._exact_lookup(normalized_query)
        if exact_match:
            return exact_match
        
        # Step 2: Fuzzy matching
        fuzzy_match = await self._fuzzy_match(normalized_query)
        if fuzzy_match and fuzzy_match.confidence >= self.FUZZY_MATCH_THRESHOLD:
            return fuzzy_match
        
        # Step 3: Phonetic matching
        phonetic_query = self._apply_phonetic_rules(normalized_query)
        phonetic_match = await self._phonetic_match(phonetic_query)
        if phonetic_match and phonetic_match.confidence >= self.PHONETIC_MATCH_THRESHOLD:
            return phonetic_match
        
        # No match found
        return None
    
    async def _exact_lookup(self, normalized_query: str) -> Optional[ProductMatchResult]:
        """
        Exact alias lookup using Redis cache.
        O(1) complexity.
        """
        # Try Redis first
        product_id = await self.cache.get_product_alias(normalized_query)
        
        # Fallback to in-memory map
        if not product_id:
            product_id = self._alias_map.get(normalized_query)
        
        if product_id:
            # Get product details
            product = await self.db.get(Product, product_id)
            if product and product.is_active:
                return ProductMatchResult(
                    product_id=product_id,
                    canonical_name=product.canonical_name,
                    matched_alias=normalized_query,
                    confidence=1.0,
                    match_type="exact"
                )
        
        return None
    
    async def _fuzzy_match(self, query: str) -> Optional[ProductMatchResult]:
        """
        Fuzzy matching using edit distance.
        Uses rapidfuzz for efficiency.
        """
        if not self._product_names:
            return None
        
        # Use rapidfuzz to find best matches
        aliases = [alias for alias, _ in self._product_names]
        result = process.extractOne(
            query,
            aliases,
            scorer=fuzz.WRatio,
            score_cutoff=self.FUZZY_MATCH_THRESHOLD * 100
        )
        
        if result:
            matched_alias, score, index = result
            product_id = self._product_names[index][1]
            
            product = await self.db.get(Product, product_id)
            if product and product.is_active:
                return ProductMatchResult(
                    product_id=product_id,
                    canonical_name=product.canonical_name,
                    matched_alias=matched_alias,
                    confidence=score / 100.0,
                    match_type="fuzzy"
                )
        
        return None
    
    async def _phonetic_match(self, phonetic_query: str) -> Optional[ProductMatchResult]:
        """
        Phonetic matching for Hindi/Hinglish variations.
        Applies phonetic rules before fuzzy matching.
        """
        if not self._product_names:
            return None
        
        # Apply phonetic rules to all aliases
        phonetic_aliases = [
            (self._apply_phonetic_rules(alias), product_id)
            for alias, product_id in self._product_names
        ]
        
        aliases = [alias for alias, _ in phonetic_aliases]
        result = process.extractOne(
            phonetic_query,
            aliases,
            scorer=fuzz.WRatio,
            score_cutoff=self.PHONETIC_MATCH_THRESHOLD * 100
        )
        
        if result:
            matched_alias, score, index = result
            product_id = phonetic_aliases[index][1]
            
            product = await self.db.get(Product, product_id)
            if product and product.is_active:
                return ProductMatchResult(
                    product_id=product_id,
                    canonical_name=product.canonical_name,
                    matched_alias=self._product_names[index][0],
                    confidence=score / 100.0,
                    match_type="phonetic"
                )
        
        return None
    
    async def add_alias(
        self,
        alias: str,
        product_id: str,
        confidence: Decimal = Decimal("1.00"),
        source: str = "manual"
    ) -> ProductAlias:
        """Add a new alias for a product."""
        normalized = self._normalize_text(alias)
        
        # Create database record
        db_alias = ProductAlias(
            alias=normalized,
            product_id=product_id,
            confidence=confidence,
            source=source,
        )
        self.db.add(db_alias)
        await self.db.flush()
        
        # Update caches
        await self.cache.set_product_alias(normalized, product_id)
        self._alias_map[normalized] = product_id
        
        # Get product for canonical name
        product = await self.db.get(Product, product_id)
        if product:
            self._product_names.append((alias, product_id))
        
        return db_alias
    
    async def learn_alias(
        self,
        query: str,
        product_id: str,
    ) -> ProductAlias:
        """
        Learn a new alias from successful order processing.
        This allows the system to improve over time.
        """
        return await self.add_alias(
            alias=query,
            product_id=product_id,
            confidence=Decimal("0.90"),
            source="learned"
        )
    
    async def increment_alias_usage(self, alias: str) -> None:
        """Increment usage count for an alias (for popularity ranking)."""
        normalized = self._normalize_text(alias)
        
        query = (
            select(ProductAlias)
            .where(ProductAlias.alias == normalized)
        )
        result = await self.db.execute(query)
        db_alias = result.scalar_one_or_none()
        
        if db_alias:
            db_alias.usage_count += 1
            await self.db.flush()
    
    def normalize_unit(self, unit: str) -> str:
        """Normalize unit to canonical form."""
        unit_lower = unit.lower().strip()
        for canonical, aliases in self.UNIT_ALIASES.items():
            if unit_lower in aliases:
                return canonical
        return unit_lower
    
    def parse_quantity_string(self, text: str) -> Tuple[Decimal, str, str]:
        """
        Parse a quantity string into (quantity, unit, product_name).
        
        Examples:
        - "2 bora basmati" -> (2, "bora", "basmati")
        - "ek packet sugar" -> (1, "packet", "sugar")
        """
        quantity, unit, product = self._extract_quantity_unit(text)
        return (
            quantity or Decimal("1"),
            unit or "piece",
            product
        )
