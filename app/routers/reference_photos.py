"""
Reference Photos Router
=======================
Provides an endpoint for uploading a reference image and receiving a
fully-populated ``ReferenceProfile`` in JSON.

POST /reference-photos/analyze
    Upload an image file (JPEG, PNG, WebP, …).
    Returns the extracted ``ReferenceProfile`` as JSON.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.reference_analyzer import ReferenceProfile, get_analyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reference-photos", tags=["Reference Photos"])

# Maximum accepted upload size: 20 MB
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

# Allowed MIME prefixes
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff"}


@router.post(
    "/analyze",
    summary="Analyze a reference photo",
    response_description="Extracted ReferenceProfile",
    status_code=status.HTTP_200_OK,
)
async def analyze_reference_photo(
    file: Annotated[UploadFile, File(description="Reference image (JPEG/PNG/WebP)")],
    description: Annotated[
        Optional[str],
        Form(description="Optional free-text shot description stored as metadata"),
    ] = None,
) -> dict:
    """
    Analyze an uploaded reference photo and return a ``ReferenceProfile``
    containing:

    - **color_palette** — 5 dominant colors (hex + LAB values + coverage)
    - **luminance_zones** — 9 average luminance values for a 3×3 grid
    - **color_temperature_k** — estimated Kelvin (2000–10000)
    - **shadow_level** / **highlight_level** — LAB L distribution endpoints
    - **per_hue_saturation** — saturation split across 8 hue bands
    - **contrast_ratio** — 90th-pct L / 10th-pct L
    - **light_direction** — coarse light source position (TOP_LEFT, OVERHEAD, …)
    - **depth_map** — 256×256 normalised depth array (0=far, 1=near)

    All processing is offline, deterministic, and runs in milliseconds on
    typical hardware.
    """
    # Validate content type
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported image type '{content_type}'. "
                f"Accepted: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}"
            ),
        )

    # Read and size-check the upload
    image_data = await file.read()
    if len(image_data) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )
    if len(image_data) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds maximum allowed size of {_MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

    # Run CPU-bound analysis in a thread-pool executor so we don't block
    # the async event loop.
    try:
        analyzer = get_analyzer()
        loop = asyncio.get_event_loop()
        profile: ReferenceProfile = await loop.run_in_executor(
            None, analyzer.analyze, image_data, description
        )
    except Exception as exc:
        logger.exception("Reference image analysis failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to process the uploaded image. Please ensure it is a valid image file.",
        ) from exc

    return profile.to_dict()
