"""
Tests for the Photo Analysis Engine.

All assertions are deterministic — the engine uses a fixed random seed (42)
for k-means and purely mathematical colour-space conversions, so every run
produces the identical output for the same input image.

Fixtures build synthetic images that have analytically predictable properties
(e.g. a pure-red image must yield reds-saturation ≈ 1.0, a pure-white image
must yield a very high highlight_level, etc.), making failures easy to diagnose.
"""

import json
import math

import numpy as np
import pytest
from PIL import Image

from app.core.photo_analysis import (
    DEPTH_MAP_SIZE,
    DominantColor,
    LightDirection,
    ReferenceProfile,
    _compute_contrast_ratio,
    _compute_depth_map,
    _compute_luminance_map,
    _compute_saturation_by_hue,
    _compute_shadow_highlight,
    _estimate_color_temperature,
    _estimate_light_direction,
    _extract_color_palette,
    _pixels_to_hsv,
    _pixels_to_lab,
    analyse_image,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _solid_rgb(r: int, g: int, b: int, size: int = 64) -> np.ndarray:
    """Create a solid-colour (H, W, 3) uint8 RGB array."""
    arr = np.empty((size, size, 3), dtype=np.uint8)
    arr[:] = [r, g, b]
    return arr


def _bright_topleft_image(size: int = 100) -> np.ndarray:
    """
    Image with a bright top-left zone, mid-grey centre, dark bottom-right.
    Used to test luminance map and light direction extraction.
    """
    arr = np.full((size, size, 3), 30, dtype=np.uint8)
    third = size // 3
    arr[:third, :third] = [240, 230, 220]        # bright top-left
    arr[third : 2 * third, third : 2 * third] = [128, 128, 128]  # grey centre
    return arr


def _gradient_image(size: int = 64) -> np.ndarray:
    """
    Horizontal gradient from black (left) to white (right).
    Contrast ratio should be high; no dominant colour direction.
    """
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    for col in range(size):
        val = int(col / (size - 1) * 255)
        arr[:, col, :] = val
    return arr


# ──────────────────────────────────────────────────────────────────────────────
# Colour-space helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestPixelsToLab:
    def test_pure_white_is_max_luminance(self):
        arr = _solid_rgb(255, 255, 255)
        lab = _pixels_to_lab(arr)
        # L* ≈ 100 for pure white
        assert lab[:, 0].mean() > 95.0

    def test_pure_black_is_zero_luminance(self):
        arr = _solid_rgb(0, 0, 0)
        lab = _pixels_to_lab(arr)
        assert lab[:, 0].mean() < 5.0

    def test_output_shape(self):
        arr = _solid_rgb(100, 150, 200, size=32)
        lab = _pixels_to_lab(arr)
        assert lab.shape == (32 * 32, 3)

    def test_L_channel_in_valid_range(self):
        arr = _solid_rgb(80, 120, 200)
        lab = _pixels_to_lab(arr)
        assert lab[:, 0].min() >= 0.0
        assert lab[:, 0].max() <= 100.0


class TestPixelsToHsv:
    def test_pure_red_hue_near_zero(self):
        arr = _solid_rgb(255, 0, 0)
        hsv = _pixels_to_hsv(arr)
        # H ≈ 0°, S ≈ 1, V ≈ 1
        assert abs(hsv[:, 0].mean()) < 5.0
        assert abs(hsv[:, 1].mean() - 1.0) < 0.01
        assert abs(hsv[:, 2].mean() - 1.0) < 0.01

    def test_pure_blue_hue_near_240(self):
        arr = _solid_rgb(0, 0, 255)
        hsv = _pixels_to_hsv(arr)
        assert abs(hsv[:, 0].mean() - 240.0) < 5.0

    def test_pure_white_saturation_zero(self):
        arr = _solid_rgb(255, 255, 255)
        hsv = _pixels_to_hsv(arr)
        assert hsv[:, 1].mean() < 0.01

    def test_pure_black_value_zero(self):
        arr = _solid_rgb(0, 0, 0)
        hsv = _pixels_to_hsv(arr)
        assert hsv[:, 2].mean() < 0.01

    def test_no_nan_or_inf(self):
        """Achromatic pixels (delta == 0) must not produce NaN or Inf."""
        arr = _solid_rgb(128, 128, 128)
        hsv = _pixels_to_hsv(arr)
        assert not np.any(np.isnan(hsv))
        assert not np.any(np.isinf(hsv))


# ──────────────────────────────────────────────────────────────────────────────
# Colour temperature
# ──────────────────────────────────────────────────────────────────────────────


class TestColorTemperature:
    def test_warm_image_returns_low_kelvin(self):
        """Orange-tinted image → warm light → lower CCT."""
        arr = _solid_rgb(220, 160, 80)
        cct = _estimate_color_temperature(arr)
        # Warm tones: expect below 4 500 K
        assert cct < 4500

    def test_cool_image_returns_high_kelvin(self):
        """Blue-tinted image → cool light → higher CCT."""
        arr = _solid_rgb(80, 130, 220)
        cct = _estimate_color_temperature(arr)
        assert cct > 6000

    def test_result_within_valid_range(self):
        for rgb in [(255, 255, 255), (0, 0, 0), (128, 50, 200)]:
            arr = _solid_rgb(*rgb)
            cct = _estimate_color_temperature(arr)
            assert 2000 <= cct <= 10000

    def test_pure_black_returns_fallback(self):
        """No achromatic pixels with luminance → must not crash, return 5 500."""
        arr = _solid_rgb(0, 0, 0)
        cct = _estimate_color_temperature(arr)
        assert cct == 5500


# ──────────────────────────────────────────────────────────────────────────────
# Colour palette
# ──────────────────────────────────────────────────────────────────────────────


class TestColorPalette:
    def test_returns_five_colours(self):
        arr = _solid_rgb(100, 150, 200)
        palette = _extract_color_palette(arr, k=5)
        assert len(palette) == 5

    def test_coverage_sums_to_one(self):
        arr = np.random.default_rng(0).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        palette = _extract_color_palette(arr, k=5)
        total = sum(c.coverage for c in palette)
        assert abs(total - 1.0) < 0.01

    def test_sorted_by_coverage_descending(self):
        arr = np.random.default_rng(1).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        palette = _extract_color_palette(arr, k=5)
        coverages = [c.coverage for c in palette]
        assert coverages == sorted(coverages, reverse=True)

    def test_hex_format(self):
        arr = _solid_rgb(0, 128, 255)
        palette = _extract_color_palette(arr, k=5)
        for colour in palette:
            assert colour.hex.startswith("#")
            assert len(colour.hex) == 7
            # Verify it is valid hex
            int(colour.hex[1:], 16)

    def test_deterministic(self):
        """Same input must produce the same palette on repeated calls."""
        arr = np.random.default_rng(42).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        p1 = _extract_color_palette(arr, k=5)
        p2 = _extract_color_palette(arr, k=5)
        assert [c.hex for c in p1] == [c.hex for c in p2]


# ──────────────────────────────────────────────────────────────────────────────
# 9-zone luminance map
# ──────────────────────────────────────────────────────────────────────────────


class TestLuminanceMap:
    def test_returns_nine_values(self):
        arr = _solid_rgb(128, 128, 128)
        result = _compute_luminance_map(arr)
        assert len(result) == 9

    def test_solid_white_all_high(self):
        arr = _solid_rgb(255, 255, 255)
        lmap = _compute_luminance_map(arr)
        assert all(v > 0.9 for v in lmap)

    def test_solid_black_all_low(self):
        arr = _solid_rgb(0, 0, 0)
        lmap = _compute_luminance_map(arr)
        assert all(v < 0.05 for v in lmap)

    def test_values_in_range(self):
        arr = _gradient_image()
        lmap = _compute_luminance_map(arr)
        assert all(0.0 <= v <= 1.0 for v in lmap)

    def test_bright_topleft_detected(self):
        arr = _bright_topleft_image()
        lmap = _compute_luminance_map(arr)
        # Zone 0 (top-left) should be the brightest
        assert lmap[0] == max(lmap)

    def test_gradient_increases_left_to_right(self):
        """In a left-dark-right-bright gradient the right column zones
        should have higher luminance than the left column zones."""
        arr = _gradient_image(size=90)
        lmap = _compute_luminance_map(arr)
        # Compare left column (zones 0,3,6) vs right column (zones 2,5,8)
        left_avg = (lmap[0] + lmap[3] + lmap[6]) / 3
        right_avg = (lmap[2] + lmap[5] + lmap[8]) / 3
        assert right_avg > left_avg


# ──────────────────────────────────────────────────────────────────────────────
# Shadow / highlight distribution
# ──────────────────────────────────────────────────────────────────────────────


class TestShadowHighlight:
    def test_pure_white_has_high_highlight(self):
        arr = _solid_rgb(255, 255, 255)
        lab = _pixels_to_lab(arr)
        _, highlight = _compute_shadow_highlight(lab)
        assert highlight > 90.0

    def test_pure_black_has_low_shadow(self):
        arr = _solid_rgb(0, 0, 0)
        lab = _pixels_to_lab(arr)
        shadow, _ = _compute_shadow_highlight(lab)
        assert shadow < 5.0

    def test_shadow_level_in_range(self):
        arr = _solid_rgb(10, 10, 10)
        lab = _pixels_to_lab(arr)
        shadow, _ = _compute_shadow_highlight(lab)
        assert 0.0 <= shadow <= 30.0

    def test_highlight_level_in_range(self):
        arr = _solid_rgb(245, 245, 245)
        lab = _pixels_to_lab(arr)
        _, highlight = _compute_shadow_highlight(lab)
        assert 70.0 <= highlight <= 100.0

    def test_midtone_has_zero_shadow_and_high_highlight_defaults(self):
        """A pure mid-grey image has no pixels in the shadow (<30) or
        highlight (>70) bands.  Defaults: shadow=0.0, highlight=100.0."""
        arr = _solid_rgb(128, 128, 128)
        lab = _pixels_to_lab(arr)
        shadow, highlight = _compute_shadow_highlight(lab)
        # Mid-grey L* ≈ 53.4 — outside both shadow and highlight bands
        assert shadow == 0.0
        assert highlight == 100.0


# ──────────────────────────────────────────────────────────────────────────────
# Per-hue saturation
# ──────────────────────────────────────────────────────────────────────────────


class TestSaturationByHue:
    def test_returns_seven_values(self):
        arr = _solid_rgb(200, 100, 50)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        assert len(result) == 7

    def test_pure_red_high_reds_saturation(self):
        arr = _solid_rgb(255, 0, 0)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        # Index 0 = reds (hue 0–30° and 330–360°)
        assert result[0] > 0.9

    def test_pure_green_high_greens_saturation(self):
        arr = _solid_rgb(0, 200, 0)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        # Index 3 = greens (90–150°)
        assert result[3] > 0.9

    def test_pure_blue_high_blues_saturation(self):
        arr = _solid_rgb(0, 0, 255)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        # Index 5 = blues (210–270°)
        assert result[5] > 0.9

    def test_grey_image_all_near_zero(self):
        """Pure grey has zero saturation in every hue band."""
        arr = _solid_rgb(128, 128, 128)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        assert all(v < 0.01 for v in result)

    def test_values_in_range(self):
        arr = np.random.default_rng(7).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        hsv = _pixels_to_hsv(arr)
        result = _compute_saturation_by_hue(hsv)
        assert all(0.0 <= v <= 1.0 for v in result)


# ──────────────────────────────────────────────────────────────────────────────
# Contrast ratio
# ──────────────────────────────────────────────────────────────────────────────


class TestContrastRatio:
    def test_solid_image_returns_one(self):
        """A perfectly flat image has no tonal range: ratio ≈ 1.0."""
        arr = _solid_rgb(128, 128, 128)
        lab = _pixels_to_lab(arr)
        ratio = _compute_contrast_ratio(lab)
        assert abs(ratio - 1.0) < 0.05

    def test_high_contrast_image(self):
        """Black-to-white gradient should produce a high contrast ratio."""
        arr = _gradient_image()
        lab = _pixels_to_lab(arr)
        ratio = _compute_contrast_ratio(lab)
        assert ratio > 5.0

    def test_ratio_always_at_least_one(self):
        arr = np.random.default_rng(3).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        lab = _pixels_to_lab(arr)
        ratio = _compute_contrast_ratio(lab)
        assert ratio >= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Light direction estimation
# ──────────────────────────────────────────────────────────────────────────────


class TestLightDirection:
    def test_top_left_bright_gives_top_left(self):
        lmap = [0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        assert _estimate_light_direction(lmap) == LightDirection.TOP_LEFT

    def test_top_bright_gives_top(self):
        lmap = [0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        assert _estimate_light_direction(lmap) == LightDirection.TOP

    def test_right_bright_gives_right(self):
        lmap = [0.1, 0.1, 0.1, 0.1, 0.1, 0.9, 0.1, 0.1, 0.1]
        assert _estimate_light_direction(lmap) == LightDirection.RIGHT

    def test_uniform_centre_gives_flat(self):
        """All zones equally bright → centre brightest → FLAT (low variance)."""
        lmap = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        assert _estimate_light_direction(lmap) == LightDirection.FLAT

    def test_centre_dominant_but_varied_gives_overhead(self):
        """Centre clearly brightest with non-trivial variance → OVERHEAD."""
        lmap = [0.1, 0.2, 0.1, 0.2, 0.9, 0.2, 0.1, 0.2, 0.1]
        result = _estimate_light_direction(lmap)
        assert result == LightDirection.OVERHEAD

    def test_valid_enum_values_only(self):
        rng = np.random.default_rng(99)
        for _ in range(5):
            lmap = rng.random(9).tolist()
            direction = _estimate_light_direction(lmap)
            assert direction in list(LightDirection)


# ──────────────────────────────────────────────────────────────────────────────
# Depth map
# ──────────────────────────────────────────────────────────────────────────────


class TestDepthMap:
    def test_returns_correct_length(self):
        arr = _solid_rgb(128, 128, 128)
        dmap = _compute_depth_map(arr)
        assert len(dmap) == DEPTH_MAP_SIZE * DEPTH_MAP_SIZE

    def test_values_in_range(self):
        arr = _gradient_image()
        dmap = _compute_depth_map(arr)
        assert all(0.0 <= v <= 1.0 for v in dmap)

    def test_bottom_heavier_than_top_for_plain_image(self):
        """For a plain solid image the vertical cue dominates:
        the bottom half should have a higher average depth value."""
        arr = _solid_rgb(150, 150, 150, size=128)
        dmap = _compute_depth_map(arr)
        half = DEPTH_MAP_SIZE * DEPTH_MAP_SIZE // 2
        top_avg = sum(dmap[:half]) / half
        bot_avg = sum(dmap[half:]) / half
        assert bot_avg > top_avg

    def test_no_nan_or_inf(self):
        arr = _solid_rgb(0, 0, 0)  # Edge case: fully black image
        dmap = _compute_depth_map(arr)
        assert not any(math.isnan(v) or math.isinf(v) for v in dmap)


# ──────────────────────────────────────────────────────────────────────────────
# Full pipeline  (analyse_image)
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyseImage:
    @pytest.fixture
    def sample_profile(self) -> ReferenceProfile:
        arr = _bright_topleft_image()
        return analyse_image(Image.fromarray(arr, "RGB"), description="unit test")

    def test_returns_reference_profile(self, sample_profile):
        assert isinstance(sample_profile, ReferenceProfile)

    def test_color_palette_length(self, sample_profile):
        assert len(sample_profile.color_palette) == 5

    def test_luminance_map_length(self, sample_profile):
        assert len(sample_profile.luminance_map) == 9

    def test_saturation_by_hue_length(self, sample_profile):
        assert len(sample_profile.saturation_by_hue) == 7

    def test_depth_map_length(self, sample_profile):
        assert len(sample_profile.depth_map) == DEPTH_MAP_SIZE * DEPTH_MAP_SIZE

    def test_description_preserved(self, sample_profile):
        assert sample_profile.description == "unit test"

    def test_description_none_by_default(self):
        arr = _solid_rgb(100, 100, 100)
        profile = analyse_image(Image.fromarray(arr, "RGB"))
        assert profile.description is None

    def test_light_direction_top_left(self, sample_profile):
        assert sample_profile.light_direction == LightDirection.TOP_LEFT

    def test_accepts_rgba_input(self):
        """analyse_image must convert RGBA to RGB without raising."""
        arr_rgba = np.full((64, 64, 4), 180, dtype=np.uint8)
        img = Image.fromarray(arr_rgba, "RGBA")
        profile = analyse_image(img)
        assert isinstance(profile, ReferenceProfile)

    def test_accepts_grayscale_input(self):
        """analyse_image must convert grayscale (L mode) to RGB."""
        arr_l = np.full((64, 64), 128, dtype=np.uint8)
        img = Image.fromarray(arr_l, "L")
        profile = analyse_image(img)
        assert isinstance(profile, ReferenceProfile)

    def test_color_temperature_in_valid_range(self, sample_profile):
        assert 2000 <= sample_profile.color_temperature_kelvin <= 10000

    def test_contrast_ratio_at_least_one(self, sample_profile):
        assert sample_profile.contrast_ratio >= 1.0

    def test_shadow_level_in_range(self, sample_profile):
        assert 0.0 <= sample_profile.shadow_level <= 30.0

    def test_highlight_level_in_range(self, sample_profile):
        assert 70.0 <= sample_profile.highlight_level <= 100.0

    def test_deterministic_output(self):
        arr = _bright_topleft_image()
        img = Image.fromarray(arr, "RGB")
        p1 = analyse_image(img)
        p2 = analyse_image(img)
        assert p1.color_temperature_kelvin == p2.color_temperature_kelvin
        assert p1.luminance_map == p2.luminance_map
        assert p1.light_direction == p2.light_direction


# ──────────────────────────────────────────────────────────────────────────────
# ReferenceProfile JSON serialisation
# ──────────────────────────────────────────────────────────────────────────────


class TestReferenceProfileJson:
    @pytest.fixture
    def profile(self) -> ReferenceProfile:
        arr = _bright_topleft_image()
        return analyse_image(Image.fromarray(arr, "RGB"), description="json test")

    def test_to_json_returns_string(self, profile):
        j = profile.to_json()
        assert isinstance(j, str)

    def test_to_json_is_valid_json(self, profile):
        j = profile.to_json()
        data = json.loads(j)
        assert isinstance(data, dict)

    def test_round_trip_preserves_light_direction(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert restored.light_direction == profile.light_direction

    def test_round_trip_preserves_palette_length(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert len(restored.color_palette) == len(profile.color_palette)

    def test_round_trip_preserves_description(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert restored.description == "json test"

    def test_round_trip_preserves_depth_map_length(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert len(restored.depth_map) == DEPTH_MAP_SIZE * DEPTH_MAP_SIZE

    def test_round_trip_preserves_numeric_fields(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert restored.color_temperature_kelvin == profile.color_temperature_kelvin
        assert abs(restored.shadow_level - profile.shadow_level) < 0.001
        assert abs(restored.highlight_level - profile.highlight_level) < 0.001
        assert abs(restored.contrast_ratio - profile.contrast_ratio) < 0.001

    def test_light_direction_serialised_as_string(self, profile):
        data = json.loads(profile.to_json())
        assert isinstance(data["light_direction"], str)
        # Must be a valid LightDirection member value
        LightDirection(data["light_direction"])

    def test_dominant_color_hex_roundtrip(self, profile):
        restored = ReferenceProfile.from_json(profile.to_json())
        assert isinstance(restored.color_palette[0], DominantColor)
        assert restored.color_palette[0].hex == profile.color_palette[0].hex
