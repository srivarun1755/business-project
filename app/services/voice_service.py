"""
Voice Processing Service
========================
Transcribes WhatsApp voice notes to text using the Sarvam AI speech API.

AI Model 1: Sarvam AI
- Purpose: Hindi/Hinglish/regional dialect speech-to-text
- Triggered: Only for voice note messages
- Output: Normalised text transcript

Cost: ~$0.001 per 30-second clip (estimated).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float


class VoiceProcessingService:
    """
    Wraps the Sarvam AI speech-to-text API.
    Supports Hindi, Hinglish, and regional dialects.
    """

    async def transcribe(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> TranscriptionResult:
        """
        Send audio bytes to Sarvam AI and return transcribed text.

        Parameters
        ----------
        audio_bytes : raw audio file bytes (OGG/MP3/WAV)
        mime_type : MIME type of the audio

        Returns
        -------
        TranscriptionResult with normalised Hindi/Hinglish text
        """
        if not settings.sarvam_api_key:
            logger.warning("Sarvam API key not configured; skipping transcription")
            return TranscriptionResult(text="", language="unknown", confidence=0.0)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.sarvam_api_url,
                headers={"api-subscription-key": settings.sarvam_api_key},
                files={"file": ("audio.ogg", audio_bytes, mime_type)},
                data={
                    "model": "saarika:v1",
                    "language_code": "hi-IN",
                    "with_timestamps": "false",
                },
            )
            response.raise_for_status()
            data = response.json()

        transcript = data.get("transcript", "")
        language = data.get("language_code", "hi-IN")
        confidence = data.get("confidence", 1.0)

        logger.info(
            "Transcribed voice note: lang=%s confidence=%.2f text=%s",
            language, confidence, transcript[:80],
        )

        return TranscriptionResult(
            text=transcript,
            language=language,
            confidence=confidence,
        )
