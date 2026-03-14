"""
Core configuration module for WhatsApp Order Automation Backend.
Uses pydantic-settings for type-safe configuration management.
"""
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = Field(default="WhatsApp Order Automation")
    debug: bool = Field(default=False)
    secret_key: str = Field(default="change-me-in-production")
    api_v1_prefix: str = Field(default="/api/v1")
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/whatsapp_orders"
    )
    database_sync_url: str = Field(
        default="postgresql://user:password@localhost:5432/whatsapp_orders"
    )
    
    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    
    # RabbitMQ
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/")
    
    # WhatsApp Business API
    whatsapp_api_url: str = Field(default="https://graph.facebook.com/v18.0")
    whatsapp_access_token: str = Field(default="")
    whatsapp_phone_number_id: str = Field(default="")
    whatsapp_verify_token: str = Field(default="")
    whatsapp_webhook_secret: str = Field(default="")
    
    # AI Services
    sarvam_api_key: str = Field(default="")
    sarvam_api_url: str = Field(default="https://api.sarvam.ai/v1")
    openai_api_key: str = Field(default="")
    
    # AWS S3
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")
    s3_bucket_name: str = Field(default="whatsapp-orders-bucket")
    s3_region: str = Field(default="ap-south-1")
    
    # GST Configuration
    default_gst_rate: float = Field(default=18.0)
    business_gstin: str = Field(default="")
    business_name: str = Field(default="")
    business_address: str = Field(default="")
    
    # Payment Reminders
    payment_reminder_days: str = Field(default="7,14,30")
    credit_limit_default: float = Field(default=50000.00)
    
    @field_validator("payment_reminder_days")
    @classmethod
    def parse_reminder_days(cls, v: str) -> str:
        """Validate payment reminder days format."""
        try:
            days = [int(d.strip()) for d in v.split(",")]
            if not all(d > 0 for d in days):
                raise ValueError("All reminder days must be positive")
            return v
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid payment_reminder_days format: {e}")
    
    def get_payment_reminder_days(self) -> List[int]:
        """Get payment reminder days as a list of integers."""
        return [int(d.strip()) for d in self.payment_reminder_days.split(",")]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export settings instance
settings = get_settings()
