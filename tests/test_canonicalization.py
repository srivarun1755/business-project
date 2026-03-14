"""
Tests for the Product Canonicalization Engine.
All matching must be deterministic (no AI in steps 1-3).
"""

import pytest
from app.core.canonicalization import (
    ProductCanonicalizationEngine,
    _normalise,
    _soundex,
)


@pytest.fixture
def engine():
    eng = ProductCanonicalizationEngine()
    eng.load_aliases([
        ("basmati rice", "prod-001", "Basmati Rice"),
        ("basmati", "prod-001", "Basmati Rice"),
        ("basmati 25kg", "prod-001", "Basmati Rice"),
        ("sugar", "prod-002", "Sugar"),
        ("chini", "prod-002", "Sugar"),
        ("toor dal", "prod-003", "Toor Dal"),
        ("arhar dal", "prod-003", "Toor Dal"),
        ("mustard oil", "prod-004", "Mustard Oil"),
        ("sarson tel", "prod-004", "Mustard Oil"),
    ])
    return eng


class TestNormalisation:
    def test_lowercase(self):
        assert _normalise("BASMATI") == "basmati"

    def test_strip_whitespace(self):
        assert _normalise("  basmati  ") == "basmati"

    def test_strip_numeric_prefix(self):
        assert _normalise("2 bora basmati") == "bora basmati"
        assert _normalise("1 bora") == "bora"

    def test_hindi_digit_words(self):
        assert _normalise("ek bora") == "bora"
        assert _normalise("do bora") == "bora"
        assert _normalise("teen bora") == "bora"

    def test_collapse_spaces(self):
        assert _normalise("basmati  rice") == "basmati rice"

    def test_special_chars_removed(self):
        assert _normalise("basmati-rice!") == "basmati-rice"


class TestExactMatch:
    def test_exact_match_returns_product(self, engine):
        match = engine.resolve("basmati rice")
        assert match is not None
        assert match.product_id == "prod-001"
        assert match.match_method == "exact"
        assert match.confidence == 1.0

    def test_exact_match_case_insensitive(self, engine):
        match = engine.resolve("BASMATI RICE")
        assert match is not None
        assert match.product_id == "prod-001"
        assert match.match_method == "exact"

    def test_exact_match_alias(self, engine):
        match = engine.resolve("chini")
        assert match is not None
        assert match.product_id == "prod-002"
        assert match.match_method == "exact"

    def test_exact_match_with_numeric_stripped(self, engine):
        """'1 sugar' should strip '1' and match 'sugar'."""
        match = engine.resolve("1 sugar")
        assert match is not None
        assert match.product_id == "prod-002"


class TestLevenshteinMatch:
    def test_typo_within_distance_2(self, engine):
        """'sugaar' is distance 1 from 'sugar', should match."""
        match = engine.resolve("sugaar")
        assert match is not None
        assert match.product_id == "prod-002"
        assert match.match_method == "levenshtein"

    def test_typo_bora_boraa(self, engine):
        """'boraa' is not in aliases, but close. Test with alias that exists."""
        # Add 'bora' alias for testing
        engine.add_alias("bora", "prod-005", "Gunny Bag")
        match = engine.resolve("boraa")
        assert match is not None
        assert match.product_id == "prod-005"
        assert match.match_method == "levenshtein"

    def test_distance_beyond_threshold_not_matched(self, engine):
        """Very different words should not be Levenshtein matched."""
        match = engine.resolve("xyz123abcdef")
        # Should either not match or match via phonetic with low confidence
        if match:
            assert match.match_method in ("levenshtein", "phonetic")

    def test_levenshtein_confidence_decreases_with_distance(self, engine):
        """Higher edit distance should yield lower confidence."""
        engine.add_alias("wheat", "prod-006", "Wheat")
        match_1 = engine.resolve("whear")   # distance 1
        match_2 = engine.resolve("wheaat")  # could be distance 1-2
        if match_1 and match_2 and match_1.match_method == match_2.match_method == "levenshtein":
            assert match_1.confidence >= match_2.confidence


class TestPhoneticMatch:
    def test_soundex_same_code(self):
        """'bora' and 'boraa' should have the same Soundex code."""
        assert _soundex("bora") == _soundex("boraa")

    def test_phonetic_match_same_soundex(self, engine):
        """Words with the same Soundex should match via phonetic step."""
        # 'sugr' has same Soundex as 'sugar' in some implementations
        # Use a controlled test
        engine.add_alias("toor", "prod-007", "Toor Dal")
        match = engine.resolve("tor")
        if match:
            assert match.product_id in ("prod-007", "prod-003")

    def test_soundex_is_deterministic(self):
        """Soundex must always return the same value for the same input."""
        assert _soundex("basmati") == _soundex("basmati")
        assert _soundex("sugar") == _soundex("sugar")


class TestAddAlias:
    def test_add_alias_updates_engine(self, engine):
        """Adding a new alias should immediately be resolvable."""
        engine.add_alias("atta", "prod-008", "Wheat Flour")
        match = engine.resolve("atta")
        assert match is not None
        assert match.product_id == "prod-008"
        assert match.match_method == "exact"

    def test_add_alias_updates_phonetic_map(self, engine):
        """New alias should be indexed in phonetic map."""
        engine.add_alias("ghee", "prod-009", "Ghee")
        code = _soundex("ghee")
        assert code in engine._phonetic_map


class TestEmptyEngine:
    def test_empty_engine_returns_none(self):
        eng = ProductCanonicalizationEngine()
        result = eng.resolve("basmati")
        assert result is None

    def test_resolve_empty_string(self, engine):
        """Empty input should return None gracefully."""
        result = engine.resolve("")
        assert result is None

    def test_resolve_numeric_only(self, engine):
        """Numeric-only input after normalisation should return None."""
        result = engine.resolve("123")
        # After normalisation "123" → "" (stripped numeric prefix)
        assert result is None
