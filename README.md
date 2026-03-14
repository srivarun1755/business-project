# WhatsApp Order Automation Backend

Production-grade backend system for a WhatsApp-based order automation platform for Indian SMEs.

## Features

- **WhatsApp Integration**: Process text orders and voice notes
- **AI-Powered Parsing**: Convert unstructured messages to structured orders
- **Product Canonicalization**: Fuzzy matching for product name normalization
- **Inventory Management**: Real-time stock tracking
- **GST Invoice Generation**: Compliant invoice generation
- **Credit Ledger**: Track customer credit and outstanding balances
- **Payment Tracking**: Monitor payment status and send reminders
- **Notification Service**: WhatsApp and SMS notifications

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│                    (FastAPI + Auth)                              │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   WhatsApp    │    │    Voice      │    │    Order      │
│   Webhook     │    │  Processing   │    │   Parsing     │
│   Receiver    │    │   Service     │    │   Service     │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│               Product Canonicalization Engine                    │
│           (Deterministic Fuzzy Matching Pipeline)                │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Inventory   │    │  GST/Invoice  │    │    Credit     │
│   Service     │    │   Service     │    │   Ledger      │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Payment Tracking Service                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Notification Service                          │
│               (WhatsApp + SMS Reminders)                         │
└─────────────────────────────────────────────────────────────────┘
```

## Technology Stack

- **Backend Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Cache**: Redis
- **Message Queue**: RabbitMQ
- **Object Storage**: S3-compatible storage
- **AI Services**:
  - Sarvam AI (Speech-to-Text for Hindi/Hinglish)
  - OpenAI GPT (Order extraction)

## AI Usage Policy

AI is limited to two specific tasks:
1. **Speech Recognition**: Converting voice notes to text (Sarvam AI)
2. **Order Extraction**: Parsing free-form text into structured JSON

All financial logic, inventory calculations, and business rules use **deterministic code**.

## Project Structure

```
src/
├── api/                    # API routes and endpoints
│   ├── v1/                 # API version 1
│   │   ├── whatsapp.py     # WhatsApp webhook endpoints
│   │   ├── orders.py       # Order management endpoints
│   │   ├── inventory.py    # Inventory management endpoints
│   │   ├── invoices.py     # Invoice generation endpoints
│   │   ├── customers.py    # Customer management endpoints
│   │   └── payments.py     # Payment tracking endpoints
│   └── deps.py             # API dependencies
├── services/               # Business logic services
│   ├── whatsapp_webhook.py # WhatsApp message handling
│   ├── voice_processing.py # Voice note transcription
│   ├── order_parsing.py    # AI-based order extraction
│   ├── canonicalization.py # Product name normalization
│   ├── inventory.py        # Inventory management
│   ├── invoice.py          # GST invoice generation
│   ├── credit_ledger.py    # Credit tracking
│   ├── payment_tracking.py # Payment monitoring
│   └── notification.py     # Notification dispatch
├── models/                 # SQLAlchemy database models
├── schemas/                # Pydantic schemas
├── core/                   # Core configuration
└── utils/                  # Utility functions
```

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- RabbitMQ 3.12+

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/whatsapp-order-backend.git
cd whatsapp-order-backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run database migrations
alembic upgrade head

# Start the server
uvicorn src.main:app --reload
```

## Configuration

Environment variables (see `.env.example`):

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/whatsapp_orders

# Redis
REDIS_URL=redis://localhost:6379/0

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# WhatsApp Business API
WHATSAPP_API_URL=https://graph.facebook.com/v18.0
WHATSAPP_ACCESS_TOKEN=your_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_id
WHATSAPP_VERIFY_TOKEN=your_verify_token

# AI Services
SARVAM_API_KEY=your_sarvam_key
OPENAI_API_KEY=your_openai_key

# AWS S3
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET_NAME=your_bucket
S3_REGION=ap-south-1
```

## API Documentation

Once running, access:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_canonicalization.py
```

## License

MIT License