from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "WhatsApp Order Automation"
    debug: bool = False
    secret_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/orders_db"
    database_url_sync: str = "postgresql://user:password@localhost:5432/orders_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    idempotency_ttl_seconds: int = 86400  # 24 hours

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # S3 / Object Storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_invoices: str = "invoices"

    # AI — Sarvam AI (speech)
    sarvam_api_key: str = ""
    sarvam_api_url: str = "https://api.sarvam.ai/speech-to-text"

    # AI — LLM (order parsing / disambiguation)
    llm_api_key: str = ""
    llm_api_url: str = "https://api.openai.com/v1/chat/completions"
    llm_model: str = "gpt-3.5-turbo"
    llm_max_tokens: int = 512

    # WhatsApp Business API
    whatsapp_token: str = ""
    whatsapp_verify_token: str = "whatsapp-verify-token"
    whatsapp_api_url: str = "https://graph.facebook.com/v19.0"
    whatsapp_phone_number_id: str = ""

    # Business defaults
    default_credit_limit: float = 50000.0
    low_stock_threshold: int = 10
    seller_gstin: str = ""
    seller_state_code: str = "27"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
