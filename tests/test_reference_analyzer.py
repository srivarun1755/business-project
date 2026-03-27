"""
Tests for app.core.reference_analyzer
======================================
All tests are synchronous and use synthetic images generated with
Pillow — no network calls, no fixtures from disk.
"""

from __future__ import annotations

import io
import math

import numpy as np
import pytest
from PIL import Image

from app.core.reference_analyzer import (
    DEPTH_MAP_SIZE,
    ColorSwatch,
    PerHueSaturation,
    ReferenceImageAnalyzer,
    ReferenceProfile,
    get_analyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg(
    width: int = 64,
    height: int = 64,
    color: tuple[int, int, int] = (128, 128, 128),
) -> bytes:
    """Return a solid-color JPEG as bytes."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_png(width: int = 64, height: int = 64, color=(200, 100, 50)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_gradient_png(width: int = 96, height: int = 96) -> bytes:
    """
    Gradient image: left column is black, right column is white.
    Top half is red-biased; bottom half is blue-biased.
    """
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        arr[:height // 2, x] = [int(x * 255 / width), 0, 0]
        arr[height // 2 :, x] = [0, 0, int(x * 255 / width)]
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_warm_image() -> bytes:
    """Strongly red/orange biased image (warm color temperature)."""
    return _make_jpeg(color=(220, 140, 60))


def _make_cool_image() -> bytes:
    """Strongly blue biased image (cool color temperature)."""
    return _make_jpeg(color=(60, 120, 220))


def _make_bright_top_image() -> bytes:
    """Top third very bright, bottom two-thirds dark → light from TOP."""
    arr = np.zeros((96, 96, 3), dtype=np.uint8)
    arr[:32, :] = 240   # bright top
    arr[32:, :] = 30    # dark rest
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_flat_image() -> bytes:
    """Uniform mid-grey image → FLAT lighting."""
    return _make_jpeg(color=(127, 127, 127))


# ---------------------------------------------------------------------------
# ReferenceProfile.to_dict
# ---------------------------------------------------------------------------

class TestReferenceProfileToDict:
    def test_to_dict_returns_all_keys(self):
        profile = ReferenceProfile()
        d = profile.to_dict()
        expected_keys = {
            "color_palette",
            "luminance_zones",
            "color_temperature_k",
            "shadow_level",
            "highlight_level",
            "per_hue_saturation",
            "contrast_ratio",
            "light_direction",
            "depth_map",
            "description",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_description_roundtrip(self):
        profile = ReferenceProfile(description="golden hour shot")
        assert profile.to_dict()["description"] == "golden hour shot"

    def test_to_dict_description_none(self):
        profile = ReferenceProfile()
        assert profile.to_dict()["description"] is None

    def test_to_dict_luminance_zones_length(self):
        profile = ReferenceProfile()
        assert len(profile.to_dict()["luminance_zones"]) == 9

    def test_to_dict_per_hue_saturation_keys(self):
        profile = ReferenceProfile()
        sat = profile.to_dict()["per_hue_saturation"]
        expected = {"reds", "oranges", "yellows", "greens", "cyans", "blues", "magentas", "neutrals"}
        assert set(sat.keys()) == expected


# ---------------------------------------------------------------------------
# ReferenceImageAnalyzer._load_image
# ---------------------------------------------------------------------------

class TestLoadImage:
    def test_loads_jpeg_to_rgb_array(self):
        data = _make_jpeg(64, 64, (200, 100, 50))
        arr = ReferenceImageAnalyzer._load_image(data)
        assert arr.ndim == 3
        assert arr.shape[2] == 3
        assert arr.dtype == np.uint8

    def test_loads_png_to_rgb_array(self):
        data = _make_png(32, 48, (10, 20, 30))
        arr = ReferenceImageAnalyzer._load_image(data)
        assert arr.shape == (48, 32, 3)

    def test_solid_color_values_approx_correct(self):
        data = _make_jpeg(32, 32, (200, 100, 50))
        arr = ReferenceImageAnalyzer._load_image(data)
        # JPEG compression introduces small artefacts; allow ±10 tolerance
        assert abs(int(arr[..., 0].mean()) - 200) < 10
        assert abs(int(arr[..., 1].mean()) - 100) < 10
        assert abs(int(arr[..., 2].mean()) - 50) < 10


# ---------------------------------------------------------------------------
# ReferenceImageAnalyzer._resize_for_analysis
# ---------------------------------------------------------------------------

class TestResizeForAnalysis:
    def setup_method(self):
        self.analyzer = ReferenceImageAnalyzer(max_pixels=10_000)

    def test_large_image_is_downscaled(self):
        big = np.zeros((400, 400, 3), dtype=np.uint8)
        small = self.analyzer._resize_for_analysis(big)
        assert small.shape[0] * small.shape[1] <= 10_000

    def test_small_image_unchanged(self):
        small = np.zeros((50, 50, 3), dtype=np.uint8)
        result = self.analyzer._resize_for_analysis(small)
        assert result.shape == (50, 50, 3)

    def test_aspect_ratio_roughly_preserved(self):
        img = np.zeros((200, 400, 3), dtype=np.uint8)
        result = self.analyzer._resize_for_analysis(img)
        ratio = result.shape[1] / result.shape[0]
        assert abs(ratio - 2.0) < 0.3


# ---------------------------------------------------------------------------
# Color space conversions
# ---------------------------------------------------------------------------

class TestRgbToLab:
    def test_pure_white_has_max_L(self):
        white = np.array([[[255, 255, 255]]], dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(white)
        assert lab[0, 0, 0] > 95.0  # L ≈ 100

    def test_pure_black_has_zero_L(self):
        black = np.array([[[0, 0, 0]]], dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(black)
        assert lab[0, 0, 0] < 2.0  # L ≈ 0

    def test_grey_has_near_zero_a_b(self):
        grey = np.array([[[128, 128, 128]]], dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(grey)
        assert abs(lab[0, 0, 1]) < 2.0  # a ≈ 0
        assert abs(lab[0, 0, 2]) < 2.0  # b ≈ 0

    def test_output_shape_preserved(self):
        img = np.zeros((30, 40, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        assert lab.shape == (30, 40, 3)


class TestRgbToHsv:
    def test_pure_red(self):
        red = np.array([[[255, 0, 0]]], dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(red)
        assert abs(hsv[0, 0, 0] - 0.0) < 1.0 or abs(hsv[0, 0, 0] - 360.0) < 1.0
        assert abs(hsv[0, 0, 1] - 1.0) < 0.02
        assert abs(hsv[0, 0, 2] - 1.0) < 0.02

    def test_pure_blue(self):
        blue = np.array([[[0, 0, 255]]], dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(blue)
        assert abs(hsv[0, 0, 0] - 240.0) < 1.0

    def test_white_has_zero_saturation(self):
        white = np.array([[[255, 255, 255]]], dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(white)
        assert hsv[0, 0, 1] < 0.01

    def test_black_has_zero_value(self):
        black = np.array([[[0, 0, 0]]], dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(black)
        assert hsv[0, 0, 2] < 0.01


# ---------------------------------------------------------------------------
# Color palette extraction
# ---------------------------------------------------------------------------

class TestExtractPalette:
    def setup_method(self):
        self.analyzer = ReferenceImageAnalyzer(palette_clusters=5)

    def test_palette_has_five_swatches(self):
        img = _make_jpeg(64, 64)
        arr = ReferenceImageAnalyzer._load_image(img)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        swatches = self.analyzer._extract_palette(lab, arr)
        assert len(swatches) == 5

    def test_coverage_sums_to_one(self):
        img = _make_jpeg(64, 64)
        arr = ReferenceImageAnalyzer._load_image(img)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        swatches = self.analyzer._extract_palette(lab, arr)
        total = sum(s.coverage for s in swatches)
        assert abs(total - 1.0) < 0.01

    def test_swatches_sorted_by_coverage_descending(self):
        img = _make_jpeg(64, 64)
        arr = ReferenceImageAnalyzer._load_image(img)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        swatches = self.analyzer._extract_palette(lab, arr)
        coverages = [s.coverage for s in swatches]
        assert coverages == sorted(coverages, reverse=True)

    def test_hex_color_format(self):
        img = _make_jpeg(64, 64)
        arr = ReferenceImageAnalyzer._load_image(img)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        swatches = self.analyzer._extract_palette(lab, arr)
        for s in swatches:
            assert s.hex_color.startswith("#")
            assert len(s.hex_color) == 7

    def test_fewer_pixels_than_k_still_works(self):
        # Tiny 2×2 image — k must be clamped to pixel count
        analyzer = ReferenceImageAnalyzer(palette_clusters=5)
        img = _make_jpeg(2, 2, (100, 150, 200))
        arr = ReferenceImageAnalyzer._load_image(img)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        swatches = analyzer._extract_palette(lab, arr)
        assert len(swatches) <= 5
        assert all(isinstance(s, ColorSwatch) for s in swatches)


# ---------------------------------------------------------------------------
# Luminance zones
# ---------------------------------------------------------------------------

class TestExtractLuminanceZones:
    def test_returns_nine_values(self):
        img = np.zeros((90, 90, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        zones = ReferenceImageAnalyzer._extract_luminance_zones(lab)
        assert len(zones) == 9

    def test_all_values_in_zero_one(self):
        img = np.random.randint(0, 256, (90, 90, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        zones = ReferenceImageAnalyzer._extract_luminance_zones(lab)
        for v in zones:
            assert 0.0 <= v <= 1.0

    def test_pure_white_image_all_zones_near_one(self):
        img = np.full((90, 90, 3), 255, dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        zones = ReferenceImageAnalyzer._extract_luminance_zones(lab)
        for v in zones:
            assert v > 0.95

    def test_pure_black_image_all_zones_near_zero(self):
        img = np.zeros((90, 90, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        zones = ReferenceImageAnalyzer._extract_luminance_zones(lab)
        for v in zones:
            assert v < 0.05

    def test_top_bright_bottom_dark(self):
        """Bright top strip → top zones should be brighter than bottom zones."""
        arr = np.zeros((90, 90, 3), dtype=np.uint8)
        arr[:30, :] = 240
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        zones = ReferenceImageAnalyzer._extract_luminance_zones(lab)
        top_mean = sum(zones[:3]) / 3
        bottom_mean = sum(zones[6:]) / 3
        assert top_mean > bottom_mean


# ---------------------------------------------------------------------------
# Color temperature estimation
# ---------------------------------------------------------------------------

class TestEstimateColorTemperature:
    def test_returns_int(self):
        arr = _make_jpeg()
        img = ReferenceImageAnalyzer._load_image(arr)
        temp = ReferenceImageAnalyzer._estimate_color_temperature(img)
        assert isinstance(temp, int)

    def test_result_in_valid_range(self):
        arr = _make_jpeg()
        img = ReferenceImageAnalyzer._load_image(arr)
        temp = ReferenceImageAnalyzer._estimate_color_temperature(img)
        assert 2000 <= temp <= 10000

    def test_warm_image_lower_than_cool_image(self):
        warm = ReferenceImageAnalyzer._load_image(_make_warm_image())
        cool = ReferenceImageAnalyzer._load_image(_make_cool_image())
        temp_warm = ReferenceImageAnalyzer._estimate_color_temperature(warm)
        temp_cool = ReferenceImageAnalyzer._estimate_color_temperature(cool)
        assert temp_warm < temp_cool

    def test_neutral_grey_mid_range(self):
        grey = ReferenceImageAnalyzer._load_image(_make_jpeg(color=(128, 128, 128)))
        temp = ReferenceImageAnalyzer._estimate_color_temperature(grey)
        assert 3000 <= temp <= 8000


# ---------------------------------------------------------------------------
# Shadow / highlight extraction
# ---------------------------------------------------------------------------

class TestExtractShadowHighlight:
    def test_pure_black_shadow_level_near_zero(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        shadow, _ = ReferenceImageAnalyzer._extract_shadow_highlight(lab)
        assert shadow < 0.05

    def test_pure_white_highlight_level_near_one(self):
        img = np.full((50, 50, 3), 255, dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        _, highlight = ReferenceImageAnalyzer._extract_shadow_highlight(lab)
        assert highlight > 0.95

    def test_values_in_zero_one(self):
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        shadow, highlight = ReferenceImageAnalyzer._extract_shadow_highlight(lab)
        assert 0.0 <= shadow <= 1.0
        assert 0.0 <= highlight <= 1.0

    def test_dark_image_shadow_below_highlight(self):
        img = np.full((50, 50, 3), 20, dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        shadow, highlight = ReferenceImageAnalyzer._extract_shadow_highlight(lab)
        assert shadow <= highlight


# ---------------------------------------------------------------------------
# Per-hue saturation
# ---------------------------------------------------------------------------

class TestExtractPerHueSaturation:
    def test_returns_per_hue_saturation_instance(self):
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(img)
        result = ReferenceImageAnalyzer._extract_per_hue_saturation(hsv)
        assert isinstance(result, PerHueSaturation)

    def test_all_values_in_zero_one(self):
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(img)
        result = ReferenceImageAnalyzer._extract_per_hue_saturation(hsv)
        for field_val in [
            result.reds,
            result.oranges,
            result.yellows,
            result.greens,
            result.cyans,
            result.blues,
            result.magentas,
            result.neutrals,
        ]:
            assert 0.0 <= field_val <= 1.0

    def test_pure_grey_image_high_neutral_saturation(self):
        """A grey image should have all pixels classified as neutral."""
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(img)
        result = ReferenceImageAnalyzer._extract_per_hue_saturation(hsv)
        # Chromatic bands should be zero (no chromatic pixels)
        assert result.reds == 0.0
        assert result.greens == 0.0
        assert result.blues == 0.0

    def test_pure_red_image_has_high_reds(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        img[:, :, 0] = 255  # pure red
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(img)
        result = ReferenceImageAnalyzer._extract_per_hue_saturation(hsv)
        assert result.reds > 0.8

    def test_pure_blue_image_has_high_blues(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        img[:, :, 2] = 255  # pure blue
        hsv = ReferenceImageAnalyzer._rgb_to_hsv(img)
        result = ReferenceImageAnalyzer._extract_per_hue_saturation(hsv)
        assert result.blues > 0.8


# ---------------------------------------------------------------------------
# Contrast ratio
# ---------------------------------------------------------------------------

class TestExtractContrastRatio:
    def test_pure_white_returns_one(self):
        img = np.full((50, 50, 3), 255, dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        ratio = ReferenceImageAnalyzer._extract_contrast_ratio(lab)
        # p10 and p90 both ≈ 100, ratio ≈ 1.0
        assert abs(ratio - 1.0) < 0.1

    def test_pure_black_returns_one(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        ratio = ReferenceImageAnalyzer._extract_contrast_ratio(lab)
        assert ratio >= 1.0

    def test_high_contrast_image_returns_high_ratio(self):
        """Half-black, half-white image should have a high contrast ratio."""
        arr = np.zeros((50, 50, 3), dtype=np.uint8)
        arr[:25, :] = 255
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        ratio = ReferenceImageAnalyzer._extract_contrast_ratio(lab)
        assert ratio > 5.0

    def test_ratio_always_at_least_one(self):
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        ratio = ReferenceImageAnalyzer._extract_contrast_ratio(lab)
        assert ratio >= 1.0


# ---------------------------------------------------------------------------
# Light direction estimation
# ---------------------------------------------------------------------------

class TestEstimateLightDirection:
    def test_returns_string(self):
        img = np.zeros((90, 90, 3), dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(img)
        direction = ReferenceImageAnalyzer._estimate_light_direction(lab)
        assert isinstance(direction, str)

    def test_valid_direction_values(self):
        valid = {
            "TOP_LEFT", "TOP", "TOP_RIGHT",
            "LEFT", "OVERHEAD", "RIGHT",
            "BOTTOM_LEFT", "BOTTOM", "BOTTOM_RIGHT",
            "FLAT",
        }
        for _ in range(5):
            img = np.random.randint(0, 256, (90, 90, 3), dtype=np.uint8)
            lab = ReferenceImageAnalyzer._rgb_to_lab(img)
            direction = ReferenceImageAnalyzer._estimate_light_direction(lab)
            assert direction in valid

    def test_bright_top_detected_as_top(self):
        arr = np.zeros((90, 90, 3), dtype=np.uint8)
        arr[:30, :] = 250  # very bright top strip
        arr[30:, :] = 10   # very dark rest
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        direction = ReferenceImageAnalyzer._estimate_light_direction(lab)
        assert direction in {"TOP", "TOP_LEFT", "TOP_RIGHT"}

    def test_uniform_image_returns_flat(self):
        arr = np.full((90, 90, 3), 128, dtype=np.uint8)
        lab = ReferenceImageAnalyzer._rgb_to_lab(arr)
        direction = ReferenceImageAnalyzer._estimate_light_direction(lab)
        assert direction == "FLAT"


# ---------------------------------------------------------------------------
# Depth map estimation
# ---------------------------------------------------------------------------

class TestEstimateDepthMap:
    def test_returns_correct_length(self):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        depth = ReferenceImageAnalyzer._estimate_depth_map(img)
        assert len(depth) == DEPTH_MAP_SIZE * DEPTH_MAP_SIZE

    def test_all_values_in_zero_one(self):
        img = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
        depth = ReferenceImageAnalyzer._estimate_depth_map(img)
        assert all(0.0 <= v <= 1.0 for v in depth)

    def test_vertical_prior_bottom_heavier(self):
        """
        For a featureless image the vertical prior should make the bottom
        half of the depth map on average higher than the top half.
        """
        # Use a solid color so texture/saturation cues are uniform
        img = np.full((96, 96, 3), 128, dtype=np.uint8)
        depth = ReferenceImageAnalyzer._estimate_depth_map(img)
        arr = np.array(depth).reshape(DEPTH_MAP_SIZE, DEPTH_MAP_SIZE)
        top_mean = arr[:DEPTH_MAP_SIZE // 2, :].mean()
        bottom_mean = arr[DEPTH_MAP_SIZE // 2:, :].mean()
        assert bottom_mean > top_mean


# ---------------------------------------------------------------------------
# Full end-to-end analyzer.analyze()
# ---------------------------------------------------------------------------

class TestAnalyzeEndToEnd:
    def setup_method(self):
        self.analyzer = ReferenceImageAnalyzer()

    def test_returns_reference_profile(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert isinstance(profile, ReferenceProfile)

    def test_color_palette_has_five_swatches(self):
        profile = self.analyzer.analyze(_make_jpeg(64, 64, (100, 150, 200)))
        assert len(profile.color_palette) == 5

    def test_luminance_zones_length_nine(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert len(profile.luminance_zones) == 9

    def test_color_temperature_in_range(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert 2000 <= profile.color_temperature_k <= 10000

    def test_contrast_ratio_at_least_one(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert profile.contrast_ratio >= 1.0

    def test_light_direction_is_valid_string(self):
        valid = {
            "TOP_LEFT", "TOP", "TOP_RIGHT",
            "LEFT", "OVERHEAD", "RIGHT",
            "BOTTOM_LEFT", "BOTTOM", "BOTTOM_RIGHT",
            "FLAT",
        }
        profile = self.analyzer.analyze(_make_jpeg())
        assert profile.light_direction in valid

    def test_depth_map_length(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert len(profile.depth_map) == DEPTH_MAP_SIZE * DEPTH_MAP_SIZE

    def test_depth_map_values_in_range(self):
        profile = self.analyzer.analyze(_make_jpeg())
        assert all(0.0 <= v <= 1.0 for v in profile.depth_map)

    def test_description_stored_verbatim(self):
        profile = self.analyzer.analyze(_make_jpeg(), description="golden hour")
        assert profile.description == "golden hour"

    def test_png_input_works(self):
        profile = self.analyzer.analyze(_make_png())
        assert isinstance(profile, ReferenceProfile)

    def test_gradient_image_works(self):
        profile = self.analyzer.analyze(_make_gradient_png())
        assert profile.light_direction in {
            "TOP_LEFT", "TOP", "TOP_RIGHT",
            "LEFT", "OVERHEAD", "RIGHT",
            "BOTTOM_LEFT", "BOTTOM", "BOTTOM_RIGHT",
            "FLAT",
        }

    def test_to_dict_structure(self):
        profile = self.analyzer.analyze(_make_jpeg())
        d = profile.to_dict()
        assert isinstance(d["color_palette"], list)
        assert isinstance(d["luminance_zones"], list)
        assert isinstance(d["color_temperature_k"], int)
        assert isinstance(d["shadow_level"], float)
        assert isinstance(d["highlight_level"], float)
        assert isinstance(d["contrast_ratio"], float)
        assert isinstance(d["light_direction"], str)
        assert isinstance(d["depth_map"], list)

    def test_warm_image_lower_temperature_than_cool(self):
        warm_profile = self.analyzer.analyze(_make_warm_image())
        cool_profile = self.analyzer.analyze(_make_cool_image())
        assert warm_profile.color_temperature_k < cool_profile.color_temperature_k

    def test_bright_top_light_comes_from_top(self):
        profile = self.analyzer.analyze(_make_bright_top_image())
        assert profile.light_direction in {"TOP", "TOP_LEFT", "TOP_RIGHT"}

    def test_flat_lighting_detected(self):
        profile = self.analyzer.analyze(_make_flat_image())
        assert profile.light_direction == "FLAT"

    def test_shadow_level_dark_image(self):
        dark = _make_jpeg(color=(15, 15, 15))
        profile = self.analyzer.analyze(dark)
        # Very dark image → shadow_level should be very low
        assert profile.shadow_level < 0.2

    def test_highlight_level_bright_image(self):
        bright = _make_jpeg(color=(240, 240, 240))
        profile = self.analyzer.analyze(bright)
        # Very bright image → highlight_level should be very high
        assert profile.highlight_level > 0.8


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

class TestGetAnalyzer:
    def test_returns_analyzer_instance(self):
        analyzer = get_analyzer()
        assert isinstance(analyzer, ReferenceImageAnalyzer)

    def test_singleton_same_instance(self):
        a1 = get_analyzer()
        a2 = get_analyzer()
        assert a1 is a2
