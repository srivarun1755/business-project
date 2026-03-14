"""
Voice Processing Service.

Uses Sarvam AI speech API to convert WhatsApp voice notes
into clean Hindi/Hinglish text transcripts.

This is one of only TWO places where AI is used in the system.
"""
import httpx
from typing import Optional
from dataclasses import dataclass
import base64

from src.core.config import settings
from src.schemas.whatsapp import VoiceNoteProcessingResult


@dataclass
class SarvamTranscriptionResponse:
    """Response from Sarvam AI transcription API."""
    transcript: str
    language: str
    confidence: float
    duration_seconds: float


class VoiceProcessingService:
    """
    Voice note transcription service using Sarvam AI.
    
    Sarvam AI is specifically designed for Indian languages:
    - Hindi
    - Hinglish (Hindi-English mix)
    - Regional dialects (Bhojpuri, etc.)
    
    The output is normalized text that can be processed
    by the Order Parsing Service.
    """
    
    def __init__(self):
        self.api_key = settings.sarvam_api_key
        self.api_url = settings.sarvam_api_url
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def download_whatsapp_audio(
        self,
        media_id: str,
        access_token: str
    ) -> bytes:
        """
        Download audio file from WhatsApp.
        
        WhatsApp voice notes are typically in OGG/Opus format.
        """
        client = await self._get_client()
        
        # First, get the media URL
        url_response = await client.get(
            f"{settings.whatsapp_api_url}/{media_id}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        url_response.raise_for_status()
        media_url = url_response.json().get("url")
        
        if not media_url:
            raise ValueError(f"Could not get URL for media {media_id}")
        
        # Download the actual audio file
        audio_response = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        audio_response.raise_for_status()
        
        return audio_response.content
    
    async def transcribe_audio(
        self,
        audio_data: bytes,
        language_hint: str = "hi-IN"
    ) -> SarvamTranscriptionResponse:
        """
        Transcribe audio using Sarvam AI Speech API.
        
        Sarvam AI supports:
        - Hindi (hi-IN)
        - English (en-IN)
        - Multiple regional languages
        
        Returns clean text transcript.
        """
        client = await self._get_client()
        
        # Encode audio as base64
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        
        # Call Sarvam AI transcription endpoint
        response = await client.post(
            f"{self.api_url}/speech/transcribe",
            json={
                "audio": audio_b64,
                "language_code": language_hint,
                "model": "saaras:v1",  # Sarvam's speech model
                "with_timestamps": False,
                "with_diarization": False,
            }
        )
        response.raise_for_status()
        
        result = response.json()
        
        return SarvamTranscriptionResponse(
            transcript=result.get("transcript", ""),
            language=result.get("language_code", language_hint),
            confidence=result.get("confidence", 0.0),
            duration_seconds=result.get("duration_seconds", 0.0),
        )
    
    async def process_voice_note(
        self,
        media_id: str,
    ) -> VoiceNoteProcessingResult:
        """
        Process a WhatsApp voice note end-to-end.
        
        Steps:
        1. Download audio from WhatsApp
        2. Transcribe using Sarvam AI
        3. Normalize and clean transcript
        
        Returns VoiceNoteProcessingResult with transcript.
        """
        # Download audio
        audio_data = await self.download_whatsapp_audio(
            media_id=media_id,
            access_token=settings.whatsapp_access_token
        )
        
        # Transcribe
        transcription = await self.transcribe_audio(
            audio_data=audio_data,
            language_hint="hi-IN"  # Default to Hindi
        )
        
        # Clean and normalize transcript
        cleaned_transcript = self._clean_transcript(transcription.transcript)
        
        return VoiceNoteProcessingResult(
            audio_id=media_id,
            transcript=cleaned_transcript,
            language=transcription.language,
            confidence=transcription.confidence,
            duration_seconds=transcription.duration_seconds,
        )
    
    def _clean_transcript(self, text: str) -> str:
        """
        Clean and normalize transcript.
        
        - Remove filler words
        - Fix common transcription errors
        - Normalize punctuation
        """
        if not text:
            return ""
        
        # Remove common filler words
        filler_words = [
            "umm", "uhh", "aaa", "hmm",
            "toh", "matlab", "basically",
        ]
        
        words = text.split()
        cleaned_words = [
            w for w in words
            if w.lower() not in filler_words
        ]
        
        cleaned = " ".join(cleaned_words)
        
        # Fix common transcription errors in order context
        corrections = {
            "bura": "bora",  # Common mishearing
            "chene": "chini",  # Sugar
            "aata": "atta",  # Flour
        }
        
        for wrong, correct in corrections.items():
            cleaned = cleaned.replace(wrong, correct)
        
        return cleaned.strip()


# Singleton instance
voice_processing_service = VoiceProcessingService()
