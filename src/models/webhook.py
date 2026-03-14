"""
Webhook event model for idempotent processing.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4
from enum import Enum
from sqlalchemy import String, Boolean, ForeignKey, Index, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.core.database import Base
from src.models.base import TimestampMixin


class WebhookSource(str, Enum):
    """Webhook source types."""
    WHATSAPP = "whatsapp"
    PAYMENT_GATEWAY = "payment_gateway"
    SMS = "sms"
    OTHER = "other"


class WebhookStatus(str, Enum):
    """Webhook processing status."""
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class WebhookEvent(Base, TimestampMixin):
    """
    Webhook event log for idempotent processing.
    Stores all incoming webhooks with their processing status.
    """
    
    __tablename__ = "webhook_events"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    
    # Idempotency key (unique per webhook event)
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Source
    source: Mapped[WebhookSource] = mapped_column(
        SQLEnum(WebhookSource),
        nullable=False,
    )
    
    # Event type (message, status, payment, etc.)
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Raw payload
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Processing status
    status: Mapped[WebhookStatus] = mapped_column(
        SQLEnum(WebhookStatus),
        default=WebhookStatus.RECEIVED,
        nullable=False,
    )
    
    # Processing result
    result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Error message if failed
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Processing timestamps
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    # Retry count
    retry_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_webhook_source_type", "source", "event_type"),
        Index("idx_webhook_status", "status"),
        Index("idx_webhook_created", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<WebhookEvent {self.source} {self.event_type} status={self.status}>"
