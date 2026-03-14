"""WhatsApp schemas."""
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field


class WhatsAppContact(BaseModel):
    """WhatsApp contact information."""
    profile: dict = Field(default_factory=dict)
    wa_id: str


class WhatsAppMessage(BaseModel):
    """WhatsApp message structure."""
    id: str
    from_: str = Field(..., alias="from")
    timestamp: str
    type: str  # text, audio, image, document, etc.
    text: Optional[dict] = None  # {"body": "message text"}
    audio: Optional[dict] = None  # {"id": "media_id", "mime_type": "audio/ogg"}
    image: Optional[dict] = None
    document: Optional[dict] = None
    
    class Config:
        populate_by_name = True


class WhatsAppValue(BaseModel):
    """WhatsApp webhook value."""
    messaging_product: str
    metadata: dict
    contacts: Optional[List[WhatsAppContact]] = None
    messages: Optional[List[WhatsAppMessage]] = None
    statuses: Optional[List[dict]] = None


class WhatsAppChange(BaseModel):
    """WhatsApp webhook change."""
    field: str
    value: WhatsAppValue


class WhatsAppEntry(BaseModel):
    """WhatsApp webhook entry."""
    id: str
    changes: List[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    """WhatsApp webhook payload structure."""
    object: str
    entry: List[WhatsAppEntry]
    
    def get_messages(self) -> List[WhatsAppMessage]:
        """Extract all messages from webhook payload."""
        messages = []
        for entry in self.entry:
            for change in entry.changes:
                if change.value.messages:
                    messages.extend(change.value.messages)
        return messages
    
    def get_phone_number_id(self) -> Optional[str]:
        """Get phone number ID from metadata."""
        for entry in self.entry:
            for change in entry.changes:
                return change.value.metadata.get("phone_number_id")
        return None


class WhatsAppTextMessage(BaseModel):
    """WhatsApp text message for sending."""
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: dict  # {"body": "message text"}


class WhatsAppTemplateMessage(BaseModel):
    """WhatsApp template message for sending."""
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "template"
    template: dict  # {"name": "template_name", "language": {"code": "en"}, "components": [...]}


class VoiceNoteProcessingResult(BaseModel):
    """Result of voice note processing."""
    audio_id: str
    transcript: str
    language: str
    confidence: float
    duration_seconds: float


class OrderParsingResult(BaseModel):
    """Result of AI order parsing."""
    success: bool
    parsed_order: Optional[dict] = None
    raw_text: str
    confidence: float
    errors: List[str] = Field(default_factory=list)
