# Property OCR Pipeline

End-to-end document processing pipeline for Karnataka property documents. Extracts structured data from scanned PDFs using Sarvam OCR, LLM-based structuring (Groq + Gemini), and an agentic verification engine (LangGraph + Gemini).

## Architecture

```
Upload PDFs → Preprocess → Sarvam OCR → Merge chunks → Classify → Structure → Store
                                                                             ↓
                                                              Agentic Verification
                                                             (LangGraph + Gemini)
```

| Service | Role |
|---|---|
| **FastAPI** | API server (`backend/main.py`) |
| **Celery + Redis** | Distributed task queue for parallel doc processing |
| **Sarvam OCR** | Vision-based OCR for Indian language documents |
| **Groq / Gemini** | LLM structuring of raw OCR text into structured JSON |
| **MySQL** | Persistent storage for cases, documents, verification reports |
| **LangGraph + Gemini** | Agentic verification engine with deterministic tool functions |
| **Qdrant (in-memory)** | Vector store for human feedback learnings |

## Document Types

- SALE_DEED, GIFT_DEED, ENCUMBRANCE_CERTIFICATE
- RTC_PAHANI, KHATA, MUTATION
- PROPERTY_REGISTER_CARD, PROPERTY_TAX_ASSESSMENT
- E_PAYMENT_RECEIPT, TAX_RECEIPT
- LEGAL_HEIR_CERTIFICATE, PARTITION_DEED
- COURT_ORDER, POSSESSION_CERTIFICATE, CONVERSION_ORDER

## Prerequisites

- Python 3.10+
- MySQL 8.0+
- Redis 7+
- API keys: [Sarvam](https://sarvam.ai), [Groq](https://groq.com), [Gemini](https://ai.google.dev)

## Setup

```bash
# Clone and install
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Edit .env with your API keys and database credentials

# Start services (or use Docker)
mysql -u root -e "CREATE DATABASE IF NOT EXISTS property_ocr"
redis-server

# Run API server
uvicorn backend.main:app --reload --port 8000

# Run Celery worker (separate terminal)
celery -A backend.celery_app worker --loglevel=info --concurrency=4
```

## Environment Variables

| Variable | Default | Required |
|---|---|---|
| `SARVAM_API_KEY` | — | Yes |
| `GROQ_API_KEY` | — | Yes |
| `GEMINI_API_KEY` | — | Yes (verification) |
| `MYSQL_HOST` | 127.0.0.1 | No |
| `MYSQL_PORT` | 3306 | No |
| `MYSQL_USER` | root | No |
| `MYSQL_PASSWORD` | (set in .env) | Yes |
| `MYSQL_DATABASE` | property_ocr | No |
| `REDIS_URL` | redis://localhost:6379/0 | No |
| `GEMINI_MODEL` | gemini-2.5-flash | No |

## API Endpoints

### Pipeline
| Method | Path | Description |
|---|---|---|
| POST | `/api/upload` | Upload PDF documents |
| POST | `/api/process/{case_id}` | Start OCR pipeline |
| GET | `/api/status/{case_id}` | Get pipeline status |
| POST | `/api/retry/{case_id}` | Retry failed documents |
| POST | `/api/clear` | Clear all Redis data |

### Documents
| Method | Path | Description |
|---|---|---|
| GET | `/api/result/{case_id}/{doc_id}` | Get structured result |
| GET | `/api/case/{case_id}/bundle` | Get all structured docs |
| POST | `/api/case/{case_id}/doc/{doc_id}/replace` | Replace a document |
| POST | `/api/case/{case_id}/doc/{doc_id}/skip` | Skip a document |

### Verification
| Method | Path | Description |
|---|---|---|
| POST | `/api/verify/{case_id}` | Run agentic verification |
| GET | `/api/verify/{case_id}/report` | Get verification report |
| POST | `/api/verify/{case_id}/feedback` | Submit human feedback |
| GET | `/api/verify/learnings/stats` | Vector DB stats |
| GET | `/api/verify/training-data` | List training records |

## Project Structure

```
backend/
├── main.py                    # FastAPI app entry point
├── celery_app.py              # Celery config
├── logger.py                  # Logging configuration
├── routers/
│   ├── cases.py               # Upload, process, status, retry
│   ├── documents.py           # Replace, skip, result
│   └── verification.py        # Verify, feedback, training data
├── services/
│   ├── pipeline_orchestrator.py   # Celery chord orchestration
│   ├── preprocessor.py            # PDF image enhancement
│   ├── sarvam_ocr.py              # Sarvam OCR integration
│   ├── ocr_merger.py              # Chunk merging
│   ├── doc_classifier.py          # Keyword-based classification
│   ├── groq_structurer.py         # Groq LLM structuring
│   ├── gemini_structurer.py       # Gemini LLM structuring
│   ├── ec_parser.py               # Deterministic EC parser
│   ├── property_tax_assessment_parser.py
│   ├── mysql_store.py             # MySQL persistence
│   ├── redis_store.py             # Redis state store
│   ├── verification_engine.py     # LangGraph verification
│   ├── verification_tools.py      # Deterministic check tools
│   └── vector_store.py            # Qdrant vector store
├── tasks/
│   └── pipeline_tasks.py      # Celery task definitions
└── utils/
    └── file_utils.py           # File I/O helpers
frontend/
└── index.html                  # Single-page UI
```
