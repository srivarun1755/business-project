# WhatsApp Order Automation Platform for Indian SMEs

A production-grade backend system that converts unstructured WhatsApp messages
into structured business operations including inventory management, GST invoice
generation, credit tracking, and payment reminders.

## Architecture Overview

```
WhatsApp Webhook
  → Idempotency Check (Redis HashSet)
  → Voice Transcription (Sarvam AI)
  → Order Parsing (LLM → JSON Schema Validation)
  → Product Canonicalization (Exact → Levenshtein → Phonetic → LLM fallback)
  → Inventory Update (Atomic PostgreSQL transaction)
  → Credit Ledger Validation (FIFO settlement)
  → GST Calculation (Deterministic tax tables)
  → Invoice Generation (WeasyPrint PDF)
  → Payment Link Creation
  → WhatsApp Notification
```

## Microservices

| Service                      | Responsibility                                      |
|------------------------------|-----------------------------------------------------|
| API Gateway                  | Auth, rate limiting, routing                        |
| WhatsApp Webhook Receiver    | Idempotent webhook intake                           |
| Voice Processing Service     | Sarvam AI speech-to-text                            |
| Order Parsing Service        | LLM text → structured JSON                         |
| Product Canonicalization     | Fuzzy match raw names to canonical products         |
| Inventory Service            | Atomic stock deduction with row-level locks         |
| GST + Invoice Service        | Deterministic tax + PDF generation                  |
| Credit Ledger Service        | Credit limit enforcement + FIFO settlement          |
| Payment Tracking Service     | Payment status, partial payments                    |
| Notification Service         | WhatsApp message dispatch                           |

## Technology Stack

- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 15
- **Cache / Idempotency**: Redis 7
- **Message Queue**: RabbitMQ (aio-pika)
- **Object Storage**: S3-compatible (MinIO for dev)
- **PDF Generation**: WeasyPrint
- **Fuzzy Matching**: Levenshtein + Soundex/Metaphone (jellyfish)

## AI Usage (Minimal)

| Task                  | Model                    | Trigger Frequency |
|-----------------------|--------------------------|-------------------|
| Voice transcription   | Sarvam AI speech API     | Only voice notes  |
| Order text parsing    | LLM (OpenAI/Groq)        | Every text order  |
| LLM disambiguation    | LLM (OpenAI/Groq)        | <1% of orders     |

AI is **never** used for financial calculations, tax logic, or inventory updates.

## Performance Targets

- **Scale**: 100,000 businesses, 1,000,000 orders/day
- **Latency**: <200 ms per order (p95)
- **AI cost**: <$0.002 per order

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+

### Run locally

```bash
cp .env.example .env
docker compose up -d
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Run tests

```bash
pytest tests/ -v
```

## Database Schema

See `migrations/` for Alembic migration scripts and `app/models/` for ORM models.

### Core Tables

- `customers` — business customer registry
- `products` — canonical product catalogue
- `product_aliases` — alias → product_id mapping (O(1) lookup)
- `inventory` — stock levels per product per tenant
- `orders` — order header
- `order_items` — order line items
- `invoices` — GST invoice records
- `invoice_items` — invoice line items with HSN + tax breakdown
- `payments` — payment records
- `credit_ledger` — double-entry credit ledger
- `hsn_codes` — HSN code → GST rate mapping

## API Endpoints

| Method | Path                             | Description                        |
|--------|----------------------------------|------------------------------------|
| POST   | /webhook/whatsapp                | WhatsApp webhook receiver          |
| POST   | /orders/                         | Create order manually              |
| GET    | /orders/{order_id}               | Get order details                  |
| GET    | /customers/                      | List customers                     |
| POST   | /customers/                      | Create customer                    |
| GET    | /customers/{customer_id}/ledger  | Customer credit ledger             |
| GET    | /products/                       | List products                      |
| POST   | /products/                       | Create product                     |
| POST   | /inventory/upload                | Bulk CSV inventory upload          |
| GET    | /inventory/{product_id}          | Get stock level                    |
| GET    | /invoices/{invoice_id}           | Get invoice                        |
| GET    | /invoices/{invoice_id}/pdf       | Download invoice PDF               |
| GET    | /payments/                       | List payments                      |
| POST   | /payments/                       | Record payment                     |

## Big-O Analysis

| Operation                     | Complexity | Notes                                       |
|-------------------------------|------------|---------------------------------------------|
| Exact alias lookup            | O(1)       | HashMap in Redis                            |
| Levenshtein matching          | O(m)       | m = alias count (200–500 typical)           |
| Phonetic lookup               | O(1)       | HashMap keyed by phonetic code              |
| Inventory deduction           | O(1)       | Row-level lock on product_id                |
| Credit limit check            | O(1)       | Indexed customer balance column             |
| GST calculation               | O(1)       | Tax table lookup by HSN code                |
| HSN code lookup               | O(1)       | HashMap<product_name, HSN>                  |
| Duplicate message check       | O(1)       | Redis HashSet membership                    |
| FIFO invoice settlement       | O(k)       | k = open invoices for customer (small)      |

## Infrastructure Cost Model (1M orders/day)

| Component              | Estimate/month |
|------------------------|----------------|
| Sarvam AI speech       | ~$50 (5% voice)|
| LLM order parsing      | ~$600 (GPT-3.5)|
| WhatsApp Business API  | ~$1,400        |
| PostgreSQL (RDS r6g.xl)| ~$250          |
| Redis (ElastiCache)    | ~$100          |
| App servers (3× c6g.xl)| ~$300          |
| S3 object storage      | ~$20           |
| **Total**              | **~$2,720/mo** |

Cost per order: **~$0.0027** (within target with LLM cost reduction via batching).

## Scaling Strategy

1. **Horizontal scaling**: Stateless FastAPI workers behind a load balancer
2. **Database**: Read replicas for reporting queries; primary for writes
3. **Redis Cluster**: Sharded by tenant_id for idempotency + caching
4. **RabbitMQ**: Fanout exchange per tenant; consumer groups per service
5. **Tenant isolation**: Row-level security on all tables via `tenant_id`
6. **CDN**: Invoice PDFs served via CloudFront/CloudFlare