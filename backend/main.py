"""
Property OCR Pipeline — FastAPI Application
Entry point: uvicorn backend.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv
import os
import logging

load_dotenv()

# Codex/sandbox launches can inject a dead local proxy (127.0.0.1:9).
for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
        os.environ.pop(proxy_var, None)

from backend.observability.logging import configure_json_logging
from backend.observability.tracing import configure_tracing
from prometheus_client import make_asgi_app

configure_json_logging()
configure_tracing()

from backend.routers import router as pipeline_router

# ── Ensure required directories exist ─────────────────────────────────────────
for d in ["uploads", "outputs/structured", "outputs/raw_ocr"]:
    Path(d).mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

# ── Allowed CORS origins ──────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

# ── Lifespan (replaces deprecated @app.on_event) ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB tables once, init statute RAG
    from backend.services.mysql_store import ensure_tables
    try:
        ensure_tables()
    except Exception as e:
        logger.warning("Failed to initialize database tables: %s", e)

    try:
        from backend.services.statute_rag import initialize_statute_store
        initialize_statute_store()
    except Exception as e:
        logger.warning("Failed to initialize statute store: %s", e)

    yield

    # Shutdown (if needed)
    pass


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Property Verification Engine",
    description="Sarvam OCR + Groq Structuring for property documents",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount Prometheus /metrics endpoint
app.mount("/metrics", make_asgi_app())

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ─────────────────────────────────────────────────────────────────
app.include_router(pipeline_router, prefix="/api")

# ── Serve frontend ─────────────────────────────────────────────────────────────
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/", response_class=FileResponse)
async def serve_ui():
    return FileResponse(FRONTEND / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "sarvam_key": bool(os.getenv("SARVAM_API_KEY")),
        "groq_key":   bool(os.getenv("GROQ_API_KEY")),
        "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
    }
