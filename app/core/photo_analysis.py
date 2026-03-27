"""
Photo Analysis Engine
=====================
Extracts a ``ReferenceProfile`` from a reference image for use in
photography coaching and filter generation.

Processing is entirely local — no AI calls, no network requests.
All algorithms are deterministic and based on standard computer vision
techniques: CIE L*a*b* colour space conversion, k-means clustering,
histogram analysis, and multi-scale gradient estimation.

Public API
----------
    analyse_image(img: PIL.Image.Image, description: str | None = None)
        -> ReferenceProfile

    ReferenceProfile.to_json() -> str
    ReferenceProfile.from_json(raw: str) -> ReferenceProfile
"""

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)

# Output dimensions for the depth map (flattened length = 256*256 = 65 536)
DEPTH_MAP_SIZE = 256

# Working resolution for pixel-level analysis (keeps processing fast on
# mid-range hardware and keeps test fixtures small)
_ANALYSIS_SIZE = (256, 256)

# D65 reference white for CIE L*a*b* conversion
_D65_REF = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────


class LightDirection(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    TOP_LEFT = "TOP_LEFT"
    TOP_RIGHT = "TOP_RIGHT"
    BOTTOM_LEFT = "BOTTOM_LEFT"
    BOTTOM_RIGHT = "BOTTOM_RIGHT"
    OVERHEAD = "OVERHEAD"
    FLAT = "FLAT"


@dataclass
class DominantColor:
    hex: str        # e.g. "#A3B2C1"
    coverage: float  # fraction of pixels in this cluster (0.0–1.0)


@dataclass
class ReferenceProfile:
    """
    Immutable snapshot of visual characteristics extracted from a
    reference photo.  All values are deterministic given the same input.
    """

    # Five dominant colours in the image (LAB-clustered, returned as hex)
    color_palette: list[DominantColor]

    # 3×3 grid of average luminance values (row-major, 0.0–1.0)
    # luminance_map[0] = top-left zone, luminance_map[8] = bottom-right zone
    luminance_map: list[float]

    # Estimated colour temperature in Kelvin (2 000–10 000)
    color_temperature_kelvin: int

    # Average CIE L* for shadow tones (pixels with L < 30), range 0–30
    shadow_level: float

    # Average CIE L* for highlight tones (pixels with L > 70), range 70–100
    highlight_level: float

    # Per-hue-range average HSV saturation (each value 0.0–1.0)
    # Indices → hue range (degrees):
    #   0  reds       0–30 and 330–360
    #   1  oranges    30–60
    #   2  yellows    60–90
    #   3  greens     90–150
    #   4  cyans     150–210
    #   5  blues     210–270
    #   6  magentas  270–330
    saturation_by_hue: list[float]

    # 90th-percentile luminance ÷ 10th-percentile luminance (≥ 1.0)
    contrast_ratio: float

    # Quadrant with the highest average luminance → estimated light source
    light_direction: LightDirection

    # Normalised depth map: 256×256 flattened (length 65 536), values 0–1
    # 0 = furthest, 1 = closest
    depth_map: list[float]

    # Optional free-text description supplied by the user (display only,
    # never processed by AI)
    description: Optional[str] = None

    # ── serialisation ──────────────────────────────────────────────────────

    def to_json(self) -> str:
        d = asdict(self)
        d["light_direction"] = self.light_direction.value
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> "ReferenceProfile":
        d = json.loads(raw)
        d["light_direction"] = LightDirection(d["light_direction"])
        d["color_palette"] = [DominantColor(**c) for c in d["color_palette"]]
        return cls(**d)


# ──────────────────────────────────────────────────────────────────────────────
# Colour-space helpers (sRGB → linear RGB → XYZ → L*a*b*)
# ──────────────────────────────────────────────────────────────────────────────

# L*a*b* inverse-transfer constants (IEC 61966-2-1 / CIE 15:2004)
# Threshold above which the cubic branch is used for f⁻¹(t)
_LAB_FINV_THRESHOLD: float = 0.20690  # = (6/29)³
# Slope used in the linear branch of f⁻¹(t) when t ≤ _LAB_FINV_THRESHOLD
_LAB_FINV_SLOPE: float = 7.787       # = (29/6)² / 3


def _srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """Linearise sRGB values in [0, 1] per the IEC 61966-2-1 standard."""
    return np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)


# sRGB (D65) → CIE XYZ matrix
_M_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
# Pre-computed inverse for the LAB centroid → sRGB conversion
_M_XYZ_TO_RGB = np.linalg.inv(_M_RGB_TO_XYZ)


def _linear_rgb_to_xyz(linear: np.ndarray) -> np.ndarray:
    """(N, 3) linear sRGB → (N, 3) CIE XYZ (D65)."""
    return linear @ _M_RGB_TO_XYZ.T


def _xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    """(N, 3) CIE XYZ (D65) → (N, 3) CIE L*a*b*."""
    t = xyz / _D65_REF
    f = np.where(t > 0.008856, np.cbrt(t), (903.3 * t + 16.0) / 116.0)
    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def _pixels_to_lab(img_rgb: np.ndarray) -> np.ndarray:
    """
    Convert an (H, W, 3) uint8 RGB array to an (H*W, 3) float64 L*a*b* array.
    L ∈ [0, 100], a ∈ [−128, 127], b ∈ [−128, 127].
    """
    flat = img_rgb.reshape(-1, 3).astype(np.float64) / 255.0
    return _xyz_to_lab(_linear_rgb_to_xyz(_srgb_to_linear(flat)))


def _pixels_to_hsv(img_rgb: np.ndarray) -> np.ndarray:
    """
    Convert an (H, W, 3) uint8 RGB array to an (H*W, 3) float64 HSV array.
    H ∈ [0, 360), S ∈ [0, 1], V ∈ [0, 1].
    """
    flat = img_rgb.reshape(-1, 3).astype(np.float64) / 255.0
    r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]
    maxc = flat.max(axis=1)
    minc = flat.min(axis=1)
    delta = maxc - minc

    # Safe saturation: avoid div-by-zero for black pixels
    safe_max = np.where(maxc > 0.0, maxc, 1.0)
    s = np.where(maxc > 0.0, delta / safe_max, 0.0)
    v = maxc

    # Safe hue: avoid div-by-zero for achromatic pixels
    safe_delta = np.where(delta > 0.0, delta, 1.0)
    mask_r = (maxc == r) & (delta > 0.0)
    mask_g = (maxc == g) & (delta > 0.0)
    mask_b = (maxc == b) & (delta > 0.0)
    h = np.zeros(len(flat), dtype=np.float64)
    h = np.where(mask_r, ((g - b) / safe_delta) % 6.0, h)
    h = np.where(mask_g, (b - r) / safe_delta + 2.0, h)
    h = np.where(mask_b, (r - g) / safe_delta + 4.0, h)
    h = h * 60.0
    h = np.where(h < 0.0, h + 360.0, h)
    return np.stack([h, s, v], axis=1)


# ──────────────────────────────────────────────────────────────────────────────
# Colour temperature estimation
# ──────────────────────────────────────────────────────────────────────────────


def _estimate_color_temperature(img_rgb: np.ndarray) -> int:
    """
    Estimate the colour temperature of the scene in Kelvin using the
    Gray World assumption.

    1. Prefer neutral (low-saturation) pixels (HSV S < 0.25) as the illuminant
       sample.  When fewer than 10 neutral pixels are available, fall back to
       using the full pixel set (Gray World on the whole image).
    2. Average the sampled R, G, B values to get the scene illuminant colour.
    3. Compute chromaticity (x, y) in the CIE 1931 colour space.
    4. Apply McCamy's empirical approximation to convert (x, y) to CCT.

    Falls back to 5 500 K (D55 daylight) when the CCT formula produces an
    out-of-range result or when the pixel luminance is effectively zero.
    """
    hsv = _pixels_to_hsv(img_rgb)
    neutral_mask = hsv[:, 1] < 0.25
    flat_rgb = img_rgb.reshape(-1, 3).astype(np.float64) / 255.0

    sample = flat_rgb[neutral_mask] if neutral_mask.sum() >= 10 else flat_rgb

    mean_r, mean_g, mean_b = sample.mean(axis=0)

    total = mean_r + mean_g + mean_b
    if total < 1e-6:
        return 5500

    x = mean_r / total
    y = mean_g / total

    # McCamy's empirical CCT approximation
    # CCT = −449·n³ + 3525·n² − 6823.3·n + 5520.33
    # where n = (x − 0.3320) / (y − 0.1858)
    denom = y - 0.1858
    if abs(denom) < 1e-9:
        return 5500
    n = (x - 0.3320) / denom
    cct = -449.0 * n**3 + 3525.0 * n**2 - 6823.3 * n + 5520.33

    return int(max(2000, min(10000, round(cct))))


# ──────────────────────────────────────────────────────────────────────────────
# Colour palette (k-means in L*a*b*)
# ──────────────────────────────────────────────────────────────────────────────


def _extract_color_palette(img_rgb: np.ndarray, k: int = 5) -> list[DominantColor]:
    """
    Cluster the image pixels into *k* dominant colours using k-means in
    CIE L*a*b* space (perceptually uniform).

    Returns DominantColor objects sorted by coverage (largest first).
    Each hex value is the cluster centroid converted back to sRGB.
    """
    lab = _pixels_to_lab(img_rgb)
    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = kmeans.fit_predict(lab)
    centroids_lab = kmeans.cluster_centers_  # (k, 3)

    n_pixels = len(labels)
    palette: list[DominantColor] = []

    for i in range(k):
        count = int((labels == i).sum())
        coverage = count / n_pixels

        # Convert centroid from L*a*b* back to sRGB for the hex value
        L, a, b_val = centroids_lab[i]
        fy = (L + 16.0) / 116.0
        fx = a / 500.0 + fy
        fz = fy - b_val / 200.0

        # f^3 if f > _LAB_FINV_THRESHOLD, else (f - 16/116) / _LAB_FINV_SLOPE
        def _finv(f: float) -> float:
            return f**3 if f > _LAB_FINV_THRESHOLD else (f - 16.0 / 116.0) / _LAB_FINV_SLOPE

        X = _finv(fx) * _D65_REF[0]
        Y = _finv(fy) * _D65_REF[1]
        Z = _finv(fz) * _D65_REF[2]

        # XYZ → linear sRGB (inverse of _M_RGB_TO_XYZ)
        linear = _M_XYZ_TO_RGB @ np.array([X, Y, Z])
        linear = np.clip(linear, 0.0, 1.0)

        # Linear → sRGB gamma
        srgb = np.where(
            linear <= 0.0031308,
            linear * 12.92,
            1.055 * linear ** (1.0 / 2.4) - 0.055,
        )
        srgb = np.clip(srgb, 0.0, 1.0)
        r_int, g_int, b_int = (int(round(c * 255)) for c in srgb)
        hex_str = f"#{r_int:02X}{g_int:02X}{b_int:02X}"

        palette.append(DominantColor(hex=hex_str, coverage=round(coverage, 4)))

    palette.sort(key=lambda c: c.coverage, reverse=True)
    return palette


# ──────────────────────────────────────────────────────────────────────────────
# 9-zone luminance map
# ──────────────────────────────────────────────────────────────────────────────


def _compute_luminance_map(img_rgb: np.ndarray) -> list[float]:
    """
    Divide the image into a 3×3 grid and return the average CIE L*
    (normalised to [0, 1]) for each zone in row-major order:

        [top-left, top-center, top-right,
         mid-left, center,     mid-right,
         bot-left, bot-center, bot-right]
    """
    H, W = img_rgb.shape[:2]
    lab = _pixels_to_lab(img_rgb)  # (H*W, 3)
    L_channel = lab[:, 0].reshape(H, W)  # (H, W), range 0–100

    rows, cols = 3, 3
    zone_values: list[float] = []
    for row in range(rows):
        r0 = row * H // rows
        r1 = (row + 1) * H // rows
        for col in range(cols):
            c0 = col * W // cols
            c1 = (col + 1) * W // cols
            zone_L = L_channel[r0:r1, c0:c1]
            zone_values.append(float(zone_L.mean() / 100.0))

    return zone_values


# ──────────────────────────────────────────────────────────────────────────────
# Shadow / highlight distribution
# ──────────────────────────────────────────────────────────────────────────────


def _compute_shadow_highlight(lab_pixels: np.ndarray) -> tuple[float, float]:
    """
    Analyse the L* channel histogram.

    shadow_level   = mean L* of pixels where L* < 30  (range 0–30)
    highlight_level = mean L* of pixels where L* > 70 (range 70–100)
    """
    L = lab_pixels[:, 0]
    shadow_px = L[L < 30.0]
    highlight_px = L[L > 70.0]

    shadow_level = float(shadow_px.mean()) if len(shadow_px) > 0 else 0.0
    highlight_level = float(highlight_px.mean()) if len(highlight_px) > 0 else 100.0

    return round(shadow_level, 2), round(highlight_level, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Per-hue-range saturation
# ──────────────────────────────────────────────────────────────────────────────

# (label, lower_bound, upper_bound) — hue in degrees [0, 360)
_HUE_RANGES = [
    ("reds", [(0.0, 30.0), (330.0, 360.0)]),
    ("oranges", [(30.0, 60.0)]),
    ("yellows", [(60.0, 90.0)]),
    ("greens", [(90.0, 150.0)]),
    ("cyans", [(150.0, 210.0)]),
    ("blues", [(210.0, 270.0)]),
    ("magentas", [(270.0, 330.0)]),
]


def _compute_saturation_by_hue(hsv_pixels: np.ndarray) -> list[float]:
    """
    Return average HSV saturation for each of the 7 hue bands defined in
    ``_HUE_RANGES``.  Returns 0.0 for bands with no pixels.
    """
    H = hsv_pixels[:, 0]
    S = hsv_pixels[:, 1]
    results: list[float] = []

    for _label, ranges in _HUE_RANGES:
        mask = np.zeros(len(H), dtype=bool)
        for lo, hi in ranges:
            mask |= (H >= lo) & (H < hi)
        sat_vals = S[mask]
        results.append(float(sat_vals.mean()) if len(sat_vals) > 0 else 0.0)

    return [round(v, 4) for v in results]


# ──────────────────────────────────────────────────────────────────────────────
# Contrast ratio
# ──────────────────────────────────────────────────────────────────────────────


def _compute_contrast_ratio(lab_pixels: np.ndarray) -> float:
    """
    Ratio of the 90th-percentile L* to the 10th-percentile L*.

    Returns 1.0 when the scene is perfectly flat (no tonal range).
    """
    L = lab_pixels[:, 0]
    p10 = float(np.percentile(L, 10))
    p90 = float(np.percentile(L, 90))
    if p10 < 0.5:
        # Avoid division by near-zero — clamp denominator
        p10 = 0.5
    return round(p90 / p10, 3)


# ──────────────────────────────────────────────────────────────────────────────
# Light direction estimation
# ──────────────────────────────────────────────────────────────────────────────

# Maps 3×3 zone index (row-major) → LightDirection
_ZONE_TO_DIRECTION: dict[int, LightDirection] = {
    0: LightDirection.TOP_LEFT,
    1: LightDirection.TOP,
    2: LightDirection.TOP_RIGHT,
    3: LightDirection.LEFT,
    4: LightDirection.OVERHEAD,   # centre zone → overhead or flat
    5: LightDirection.RIGHT,
    6: LightDirection.BOTTOM_LEFT,
    7: LightDirection.BOTTOM,
    8: LightDirection.BOTTOM_RIGHT,
}


def _estimate_light_direction(luminance_map: list[float]) -> LightDirection:
    """
    Identify the light source direction from the 9-zone luminance map.

    Rules (in priority order):
    1. When the spatial variance across all nine zones is below 0.005 the
       lighting is essentially uniform → return FLAT.
    2. Otherwise, the zone with the highest average luminance is the primary
       candidate and maps to a cardinal/diagonal direction.
    3. When the centre zone (4) is the brightest but the variance is still
       above the flat threshold → OVERHEAD (direct overhead flash/sun).
    """
    arr = np.array(luminance_map)

    # Flat / even diffuse lighting
    if arr.var() < 0.005:
        return LightDirection.FLAT

    brightest_zone = int(arr.argmax())
    return _ZONE_TO_DIRECTION[brightest_zone]


# ──────────────────────────────────────────────────────────────────────────────
# Simplified depth map
# ──────────────────────────────────────────────────────────────────────────────


def _compute_depth_map(img_rgb: np.ndarray) -> list[float]:
    """
    Produce a normalised depth map (256×256, row-major) using three
    monocular depth cues combined by equal-weight averaging:

    1. **Vertical position** — lower pixels are closer (natural scene prior).
    2. **Atmospheric perspective** — distant objects appear de-saturated;
       high HSV saturation indicates proximity.
    3. **Local contrast / sharpness** — near objects show more high-frequency
       detail; estimated with a Laplacian edge response.

    All three cues are independently normalised to [0, 1] before averaging,
    so no single cue dominates.  The final map is min–max normalised.
    """
    H, W = img_rgb.shape[:2]

    # ── Cue 1: vertical position (linear gradient, bottom = 1) ────────────
    y_coords = np.linspace(0.0, 1.0, H)[:, np.newaxis]  # (H, 1)
    vertical_cue = np.broadcast_to(y_coords, (H, W)).copy()

    # ── Cue 2: saturation (atmospheric perspective) ───────────────────────
    hsv = _pixels_to_hsv(img_rgb)
    sat_map = hsv[:, 1].reshape(H, W)

    # ── Cue 3: local contrast (Laplacian magnitude) ───────────────────────
    gray = np.array(Image.fromarray(img_rgb).convert("L"), dtype=np.float64)
    # 4-connected discrete Laplacian with border replication padding
    padded = np.pad(gray, 1, mode="edge")
    lap = (
        -4.0 * padded[1:-1, 1:-1]
        + padded[0:-2, 1:-1]   # north
        + padded[2:,   1:-1]   # south
        + padded[1:-1, 0:-2]   # west
        + padded[1:-1, 2:]     # east
    )
    contrast_cue = np.abs(lap)

    # ── Normalise each cue to [0, 1] ──────────────────────────────────────
    def _norm(m: np.ndarray) -> np.ndarray:
        lo, hi = m.min(), m.max()
        if hi - lo < 1e-8:
            return np.zeros_like(m)
        return (m - lo) / (hi - lo)

    depth = (_norm(vertical_cue) + _norm(sat_map) + _norm(contrast_cue)) / 3.0

    # ── Resize to DEPTH_MAP_SIZE × DEPTH_MAP_SIZE ─────────────────────────
    depth_img = Image.fromarray((depth * 255.0).astype(np.uint8)).resize(
        (DEPTH_MAP_SIZE, DEPTH_MAP_SIZE), Image.BILINEAR
    )
    depth_arr = np.array(depth_img, dtype=np.float64) / 255.0

    # Final min–max normalisation to guarantee [0, 1]
    depth_arr = _norm(depth_arr)
    return [round(float(v), 4) for v in depth_arr.flatten()]


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────


def analyse_image(
    img: Image.Image,
    description: Optional[str] = None,
) -> ReferenceProfile:
    """
    Extract a complete ``ReferenceProfile`` from *img*.

    Parameters
    ----------
    img:
        A ``PIL.Image.Image`` in any mode.  It is converted to RGB internally.
    description:
        Optional free-text description supplied by the user (stored in the
        profile for display purposes only — never processed by AI).

    Returns
    -------
    ReferenceProfile
        Fully populated profile ready for photography coaching and filter
        generation.
    """
    img_rgb = img.convert("RGB").resize(_ANALYSIS_SIZE, Image.LANCZOS)
    arr = np.array(img_rgb, dtype=np.uint8)  # (256, 256, 3)

    lab_pixels = _pixels_to_lab(arr)
    hsv_pixels = _pixels_to_hsv(arr)

    logger.debug("Photo analysis: computing colour palette …")
    color_palette = _extract_color_palette(arr, k=5)

    logger.debug("Photo analysis: computing luminance map …")
    luminance_map = _compute_luminance_map(arr)

    logger.debug("Photo analysis: estimating colour temperature …")
    color_temperature_kelvin = _estimate_color_temperature(arr)

    logger.debug("Photo analysis: shadow/highlight distribution …")
    shadow_level, highlight_level = _compute_shadow_highlight(lab_pixels)

    logger.debug("Photo analysis: per-hue saturation …")
    saturation_by_hue = _compute_saturation_by_hue(hsv_pixels)

    logger.debug("Photo analysis: contrast ratio …")
    contrast_ratio = _compute_contrast_ratio(lab_pixels)

    logger.debug("Photo analysis: light direction …")
    light_direction = _estimate_light_direction(luminance_map)

    logger.debug("Photo analysis: depth map …")
    depth_map = _compute_depth_map(arr)

    return ReferenceProfile(
        color_palette=color_palette,
        luminance_map=luminance_map,
        color_temperature_kelvin=color_temperature_kelvin,
        shadow_level=shadow_level,
        highlight_level=highlight_level,
        saturation_by_hue=saturation_by_hue,
        contrast_ratio=contrast_ratio,
        light_direction=light_direction,
        depth_map=depth_map,
        description=description,
    )
