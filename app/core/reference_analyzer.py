"""
Reference Image Analyzer
========================
Extracts a ``ReferenceProfile`` from any input image using pure
computer-vision techniques — no network calls, no LLMs.

Extracted data
--------------
- color_palette        : 5 dominant colors (hex + coverage %)
- luminance_zones      : 9-zone 3×3 grid of average LAB L values [0, 1]
- color_temperature_k  : estimated Kelvin value via gray-world assumption
- shadow_level         : average LAB L in dark pixels (L < 30)
- highlight_level      : average LAB L in bright pixels (L > 70)
- per_hue_saturation   : HSV saturation for 8 hue bands
- contrast_ratio       : 90th-percentile L / 10th-percentile L
- light_direction      : coarse direction string (TOP_LEFT, OVERHEAD, etc.)
- depth_map            : 256×256 normalised float array [0, 1] (far→near)

All processing is synchronous and runs in-process.  Callers should
dispatch to a thread-pool executor if used inside FastAPI async routes.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Public data classes
# -------------------------------------------------------------------

DEPTH_MAP_SIZE = 256  # output depth map dimension (square)


@dataclass
class ColorSwatch:
    """A single dominant color from k-means clustering."""

    hex_color: str  # e.g. "#3a7bd5"
    coverage: float  # fraction of pixels, 0.0–1.0
    lab_l: float  # LAB L* value
    lab_a: float  # LAB a* value
    lab_b: float  # LAB b* value


@dataclass
class PerHueSaturation:
    """Average HSV saturation split across 8 hue ranges."""

    reds: float        # hue 0-30° and 330-360°
    oranges: float     # hue 30-60°
    yellows: float     # hue 60-90°
    greens: float      # hue 90-150°
    cyans: float       # hue 150-210°
    blues: float       # hue 210-270°
    magentas: float    # hue 270-330°
    neutrals: float    # near-grey pixels (S < 0.15)


@dataclass
class ReferenceProfile:
    """Full analysis result for a reference image."""

    # Color palette — 5 dominant colors
    color_palette: list[ColorSwatch] = field(default_factory=list)

    # 9-zone 3×3 grid luminance map (row-major, top-left first), values 0–1
    luminance_zones: list[float] = field(default_factory=lambda: [0.0] * 9)

    # Estimated color temperature in Kelvin (2000–10000)
    color_temperature_k: int = 5500

    # Shadow/highlight levels (average LAB L in the respective range)
    shadow_level: float = 0.0    # average L below 30
    highlight_level: float = 1.0  # average L above 70

    # Per-hue average saturation
    per_hue_saturation: PerHueSaturation = field(
        default_factory=lambda: PerHueSaturation(0, 0, 0, 0, 0, 0, 0, 0)
    )

    # Contrast ratio: 90th-percentile L / 10th-percentile L (clamped ≥ 1.0)
    contrast_ratio: float = 1.0

    # Coarse estimated light source direction
    light_direction: str = "OVERHEAD"

    # Depth map — list of DEPTH_MAP_SIZE×DEPTH_MAP_SIZE floats, row-major
    # 0.0 = distant / background, 1.0 = near / foreground
    depth_map: list[float] = field(default_factory=list)

    # Optional free-text description stored as metadata (not processed)
    description: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "color_palette": [
                {
                    "hex_color": s.hex_color,
                    "coverage": round(s.coverage, 4),
                    "lab_l": round(s.lab_l, 2),
                    "lab_a": round(s.lab_a, 2),
                    "lab_b": round(s.lab_b, 2),
                }
                for s in self.color_palette
            ],
            "luminance_zones": [round(v, 4) for v in self.luminance_zones],
            "color_temperature_k": self.color_temperature_k,
            "shadow_level": round(self.shadow_level, 4),
            "highlight_level": round(self.highlight_level, 4),
            "per_hue_saturation": {
                "reds": round(self.per_hue_saturation.reds, 4),
                "oranges": round(self.per_hue_saturation.oranges, 4),
                "yellows": round(self.per_hue_saturation.yellows, 4),
                "greens": round(self.per_hue_saturation.greens, 4),
                "cyans": round(self.per_hue_saturation.cyans, 4),
                "blues": round(self.per_hue_saturation.blues, 4),
                "magentas": round(self.per_hue_saturation.magentas, 4),
                "neutrals": round(self.per_hue_saturation.neutrals, 4),
            },
            "contrast_ratio": round(self.contrast_ratio, 4),
            "light_direction": self.light_direction,
            "depth_map": [round(v, 4) for v in self.depth_map],
            "description": self.description,
        }


# -------------------------------------------------------------------
# Analyzer
# -------------------------------------------------------------------

class ReferenceImageAnalyzer:
    """
    Stateless analyzer.  Create once and call ``analyze()`` for each image.

    Parameters
    ----------
    palette_clusters : int
        Number of k-means clusters for the color palette (default 5).
    max_pixels : int
        Images are down-scaled so that their total pixel count does not
        exceed this value before analysis, keeping runtimes predictable.
    """

    def __init__(
        self,
        palette_clusters: int = 5,
        max_pixels: int = 150_000,
    ) -> None:
        self._k = palette_clusters
        self._max_pixels = max_pixels

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_data: bytes,
        description: Optional[str] = None,
    ) -> ReferenceProfile:
        """
        Analyze image bytes and return a fully-populated ``ReferenceProfile``.

        Parameters
        ----------
        image_data : bytes
            Raw image bytes (JPEG, PNG, WebP, etc.)
        description : str, optional
            Free-text description stored as metadata only.
        """
        img_rgb = self._load_image(image_data)
        img_small = self._resize_for_analysis(img_rgb)

        lab = self._rgb_to_lab(img_small)
        hsv = self._rgb_to_hsv(img_small)

        profile = ReferenceProfile(description=description)

        profile.color_palette = self._extract_palette(lab, img_small)
        profile.luminance_zones = self._extract_luminance_zones(lab)
        profile.color_temperature_k = self._estimate_color_temperature(img_small)
        profile.shadow_level, profile.highlight_level = (
            self._extract_shadow_highlight(lab)
        )
        profile.per_hue_saturation = self._extract_per_hue_saturation(hsv)
        profile.contrast_ratio = self._extract_contrast_ratio(lab)
        profile.light_direction = self._estimate_light_direction(lab)
        profile.depth_map = self._estimate_depth_map(img_small)

        return profile

    # ------------------------------------------------------------------
    # Image loading / pre-processing
    # ------------------------------------------------------------------

    @staticmethod
    def _load_image(data: bytes) -> np.ndarray:
        """Decode image bytes to a uint8 H×W×3 RGB numpy array."""
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return np.asarray(img, dtype=np.uint8)

    def _resize_for_analysis(self, img: np.ndarray) -> np.ndarray:
        """Down-scale image so total pixels ≤ self._max_pixels."""
        h, w = img.shape[:2]
        n_pixels = h * w
        if n_pixels <= self._max_pixels:
            return img
        scale = (self._max_pixels / n_pixels) ** 0.5
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        pil = Image.fromarray(img).resize((new_w, new_h), Image.Resampling.LANCZOS)
        return np.asarray(pil, dtype=np.uint8)

    # ------------------------------------------------------------------
    # Color space conversions (vectorised, no external C libs)
    # ------------------------------------------------------------------

    @staticmethod
    def _rgb_to_lab(img: np.ndarray) -> np.ndarray:
        """
        Convert H×W×3 uint8 RGB to H×W×3 float32 CIE-LAB.

        Uses the standard sRGB → XYZ (D65) → LAB conversion.
        L is in [0, 100], a and b in [-128, 127].
        """
        # Linearise sRGB
        rgb = img.astype(np.float32) / 255.0
        mask = rgb > 0.04045
        rgb[mask] = ((rgb[mask] + 0.055) / 1.055) ** 2.4
        rgb[~mask] = rgb[~mask] / 12.92

        # sRGB to XYZ (D65 reference white)
        m = np.array(
            [
                [0.4124564, 0.3575761, 0.1804375],
                [0.2126729, 0.7151522, 0.0721750],
                [0.0193339, 0.1191920, 0.9503041],
            ],
            dtype=np.float32,
        )
        xyz = rgb @ m.T  # H×W×3

        # Normalise by D65 reference white
        xyz /= np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)

        # XYZ → LAB via the cube-root function
        epsilon = 0.008856
        kappa = 903.3
        mask_xyz = xyz > epsilon
        f = np.where(mask_xyz, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)

        L = 116.0 * f[..., 1] - 16.0          # [0, 100]
        a = 500.0 * (f[..., 0] - f[..., 1])   # [-128, 127]
        b = 200.0 * (f[..., 1] - f[..., 2])   # [-128, 127]

        return np.stack([L, a, b], axis=-1).astype(np.float32)

    @staticmethod
    def _rgb_to_hsv(img: np.ndarray) -> np.ndarray:
        """Convert H×W×3 uint8 RGB to H×W×3 float32 HSV (H∈[0,360), S,V∈[0,1])."""
        rgb = img.astype(np.float32) / 255.0
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

        cmax = np.maximum(np.maximum(r, g), b)
        cmin = np.minimum(np.minimum(r, g), b)
        delta = cmax - cmin

        # Hue
        hue = np.zeros_like(cmax)
        nonzero = delta > 0

        # red is max
        m = nonzero & (cmax == r)
        hue[m] = (60.0 * ((g[m] - b[m]) / delta[m])) % 360.0

        # green is max
        m = nonzero & (cmax == g)
        hue[m] = 60.0 * ((b[m] - r[m]) / delta[m] + 2.0)

        # blue is max
        m = nonzero & (cmax == b)
        hue[m] = 60.0 * ((r[m] - g[m]) / delta[m] + 4.0)

        hue = hue % 360.0

        # Saturation
        with np.errstate(divide="ignore", invalid="ignore"):
            sat = np.where(cmax > 0, delta / cmax, 0.0)

        # Value
        val = cmax

        return np.stack([hue, sat, val], axis=-1).astype(np.float32)

    # ------------------------------------------------------------------
    # Feature extraction methods
    # ------------------------------------------------------------------

    def _extract_palette(
        self, lab: np.ndarray, rgb: np.ndarray
    ) -> list[ColorSwatch]:
        """
        K-means clustering (k=5) in LAB space to find dominant colors.

        Returns swatches sorted by coverage (descending).
        """
        h, w = lab.shape[:2]
        pixels_lab = lab.reshape(-1, 3).astype(np.float64)
        pixels_rgb = rgb.reshape(-1, 3).astype(np.float64)

        n_samples = pixels_lab.shape[0]
        k = min(self._k, n_samples)

        km = KMeans(n_clusters=k, n_init=5, random_state=42)
        labels = km.fit_predict(pixels_lab)
        centers_lab = km.cluster_centers_  # k×3

        swatches: list[ColorSwatch] = []
        for idx in range(k):
            mask = labels == idx
            count = int(np.sum(mask))
            coverage = float(count) / n_samples

            # Mean RGB for this cluster → hex (fall back to centroid-derived
            # color when no pixels are assigned to this cluster)
            if count > 0:
                mean_rgb = pixels_rgb[mask].mean(axis=0).clip(0, 255).astype(np.uint8)
            else:
                # Convert LAB centroid back to a representative grey tone
                grey = int(np.clip(centers_lab[idx, 0] * 255.0 / 100.0, 0, 255))
                mean_rgb = np.array([grey, grey, grey], dtype=np.uint8)

            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(mean_rgb[0]), int(mean_rgb[1]), int(mean_rgb[2])
            )

            L, a, b = float(centers_lab[idx, 0]), float(centers_lab[idx, 1]), float(centers_lab[idx, 2])
            swatches.append(
                ColorSwatch(
                    hex_color=hex_color,
                    coverage=coverage,
                    lab_l=L,
                    lab_a=a,
                    lab_b=b,
                )
            )

        swatches.sort(key=lambda s: s.coverage, reverse=True)
        return swatches

    @staticmethod
    def _extract_luminance_zones(lab: np.ndarray) -> list[float]:
        """
        Divide image into 3×3 grid and compute average L (normalised to [0,1])
        for each of the 9 zones.  Returns a 9-element list in row-major order
        (top-left → top-right → middle-left → … → bottom-right).
        """
        h, w = lab.shape[:2]
        zones: list[float] = []
        for row in range(3):
            for col in range(3):
                r0 = row * h // 3
                r1 = (row + 1) * h // 3
                c0 = col * w // 3
                c1 = (col + 1) * w // 3
                zone_l = lab[r0:r1, c0:c1, 0]  # L channel
                mean_l = float(np.mean(zone_l)) / 100.0  # normalise to [0,1]
                zones.append(float(np.clip(mean_l, 0.0, 1.0)))
        return zones

    @staticmethod
    def _estimate_color_temperature(img_rgb: np.ndarray) -> int:
        """
        Estimate color temperature in Kelvin using the gray-world assumption.

        The ratio of the mean R/G and B/G channels is mapped onto a
        piecewise approximation of the Planckian locus.
        Returns an integer clamped to [2000, 10000] K.
        """
        mean_r = float(np.mean(img_rgb[..., 0])) + 1e-6
        mean_g = float(np.mean(img_rgb[..., 1])) + 1e-6
        mean_b = float(np.mean(img_rgb[..., 2])) + 1e-6

        # Normalize channels
        r_norm = mean_r / mean_g
        b_norm = mean_b / mean_g

        # Blue-red ratio is a rough proxy for CCT:
        # warm (red-biased) → low CCT; cool (blue-biased) → high CCT.
        # Linear mapping derived from empirical Planckian locus samples.
        br_ratio = b_norm / r_norm  # ~0.3 at 2700K, ~1.5 at 7000K

        if br_ratio <= 0.35:
            kelvin = 2000
        elif br_ratio >= 1.8:
            kelvin = 10000
        else:
            # Linear interpolation in log space
            kelvin = int(2000 + (br_ratio - 0.35) / (1.8 - 0.35) * (10000 - 2000))

        return int(np.clip(kelvin, 2000, 10000))

    @staticmethod
    def _extract_shadow_highlight(lab: np.ndarray) -> tuple[float, float]:
        """
        Analyse the LAB L histogram.

        shadow_level   = mean L of pixels where L < 30, normalised to [0, 1]
        highlight_level = mean L of pixels where L > 70, normalised to [0, 1]

        If no pixels fall in a range the boundary value is returned.
        """
        l_channel = lab[..., 0].ravel()

        shadow_pixels = l_channel[l_channel < 30]
        shadow_level = float(np.mean(shadow_pixels) / 100.0) if len(shadow_pixels) > 0 else 0.0

        highlight_pixels = l_channel[l_channel > 70]
        highlight_level = float(np.mean(highlight_pixels) / 100.0) if len(highlight_pixels) > 0 else 1.0

        return float(np.clip(shadow_level, 0.0, 1.0)), float(np.clip(highlight_level, 0.0, 1.0))

    @staticmethod
    def _extract_per_hue_saturation(hsv: np.ndarray) -> PerHueSaturation:
        """
        Compute average HSV saturation within each of 8 hue bands.

        Neutral pixels (S < 0.15) are collected separately and excluded
        from hue-band averages to avoid diluting the chromatic signal.
        """
        hue = hsv[..., 0].ravel()
        sat = hsv[..., 1].ravel()

        def _mean_sat(mask: np.ndarray) -> float:
            vals = sat[mask]
            return float(np.mean(vals)) if len(vals) > 0 else 0.0

        neutral_mask = sat < 0.15
        chromatic = ~neutral_mask

        reds = chromatic & ((hue <= 30) | (hue >= 330))
        oranges = chromatic & (hue > 30) & (hue <= 60)
        yellows = chromatic & (hue > 60) & (hue <= 90)
        greens = chromatic & (hue > 90) & (hue <= 150)
        cyans = chromatic & (hue > 150) & (hue <= 210)
        blues = chromatic & (hue > 210) & (hue <= 270)
        magentas = chromatic & (hue > 270) & (hue < 330)

        return PerHueSaturation(
            reds=_mean_sat(reds),
            oranges=_mean_sat(oranges),
            yellows=_mean_sat(yellows),
            greens=_mean_sat(greens),
            cyans=_mean_sat(cyans),
            blues=_mean_sat(blues),
            magentas=_mean_sat(magentas),
            neutrals=_mean_sat(neutral_mask),
        )

    @staticmethod
    def _extract_contrast_ratio(lab: np.ndarray) -> float:
        """
        Compute contrast ratio as 90th-percentile L / 10th-percentile L.

        Values are clamped so the result is always ≥ 1.0.
        """
        l_vals = lab[..., 0].ravel()
        p10 = float(np.percentile(l_vals, 10))
        p90 = float(np.percentile(l_vals, 90))
        if p10 < 1.0:
            p10 = 1.0
        ratio = p90 / p10
        return float(max(1.0, ratio))

    @staticmethod
    def _estimate_light_direction(lab: np.ndarray) -> str:
        """
        Estimate the dominant light-source direction from the 9-zone grid.

        Finds the brightest zone, then maps its position to one of:
        TOP_LEFT, TOP, TOP_RIGHT, LEFT, OVERHEAD, RIGHT,
        BOTTOM_LEFT, BOTTOM, BOTTOM_RIGHT, FLAT
        """
        h, w = lab.shape[:2]
        zone_means: list[float] = []
        for row in range(3):
            for col in range(3):
                r0 = row * h // 3
                r1 = (row + 1) * h // 3
                c0 = col * w // 3
                c1 = (col + 1) * w // 3
                zone_means.append(float(np.mean(lab[r0:r1, c0:c1, 0])))

        brightest = int(np.argmax(zone_means))
        # Brightest zone → row, col
        row = brightest // 3
        col = brightest % 3

        # Check for uniform / flat lighting: std of zone means is low
        zone_std = float(np.std(zone_means))
        if zone_std < 5.0:
            return "FLAT"

        _direction_map = {
            (0, 0): "TOP_LEFT",
            (0, 1): "TOP",
            (0, 2): "TOP_RIGHT",
            (1, 0): "LEFT",
            (1, 1): "OVERHEAD",
            (1, 2): "RIGHT",
            (2, 0): "BOTTOM_LEFT",
            (2, 1): "BOTTOM",
            (2, 2): "BOTTOM_RIGHT",
        }
        return _direction_map[(row, col)]

    @staticmethod
    def _estimate_depth_map(img_rgb: np.ndarray) -> list[float]:
        """
        Produce a coarse depth map (256×256 float [0,1]) using three
        monocular cues that work without a neural network:

        1. Vertical position  — objects lower in frame tend to be closer.
        2. Atmospheric haze   — distant regions have lower local contrast
                                and shifted colour (atmospheric perspective).
        3. High-frequency detail — near surfaces have sharper texture.

        The three cues are combined with equal weight and the result is
        normalised to [0, 1] where 1.0 = near / foreground.
        """
        target = DEPTH_MAP_SIZE
        pil = Image.fromarray(img_rgb).resize((target, target), Image.Resampling.LANCZOS)
        small = np.asarray(pil, dtype=np.float32) / 255.0  # target×target×3

        h, w = small.shape[:2]

        # --- Cue 1: vertical position prior ---
        # Linear ramp: top row → 0.0 (far), bottom row → 1.0 (near)
        y_coords = np.linspace(0.0, 1.0, h)
        vertical_prior = np.tile(y_coords[:, None], (1, w))  # h×w

        # --- Cue 2: inverse atmospheric haze ---
        # Compute local contrast in a 5-pixel neighbourhood via simple std.
        # High local std → near; low std → far / hazy.
        gray = 0.299 * small[..., 0] + 0.587 * small[..., 1] + 0.114 * small[..., 2]
        pad = 2
        padded = np.pad(gray, pad, mode="edge")
        local_std = np.zeros((h, w), dtype=np.float32)
        for dy in range(-pad, pad + 1):
            for dx in range(-pad, pad + 1):
                shifted = padded[pad + dy : pad + dy + h, pad + dx : pad + dx + w]
                local_std += (shifted - gray) ** 2
        local_std = np.sqrt(local_std / ((2 * pad + 1) ** 2))

        # --- Cue 3: colour saturation (distant objects desaturated) ---
        r, g, b = small[..., 0], small[..., 1], small[..., 2]
        cmax = np.maximum(np.maximum(r, g), b)
        cmin = np.minimum(np.minimum(r, g), b)
        saturation = np.where(cmax > 0, (cmax - cmin) / (cmax + 1e-6), 0.0)

        # --- Combine cues ---
        depth_raw = (vertical_prior + local_std + saturation) / 3.0

        # Normalise to [0, 1]
        d_min = depth_raw.min()
        d_max = depth_raw.max()
        if d_max > d_min:
            depth_norm = (depth_raw - d_min) / (d_max - d_min)
        else:
            depth_norm = depth_raw

        return depth_norm.ravel().tolist()


# -------------------------------------------------------------------
# Module-level singleton
# -------------------------------------------------------------------

_analyzer: Optional[ReferenceImageAnalyzer] = None


def get_analyzer() -> ReferenceImageAnalyzer:
    """Return the module-level ``ReferenceImageAnalyzer`` singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ReferenceImageAnalyzer()
    return _analyzer
