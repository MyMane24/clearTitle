"""
Property OCR Pipeline — FastAPI Application
Entry point: uvicorn backend.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# Codex/sandbox launches can inject a dead local proxy (127.0.0.1:9).
# The Sarvam and Groq SDKs use httpx, which honors these env vars by default.
# If left in place, external API calls fail with WinError 10061.
for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
        os.environ.pop(proxy_var, None)

from backend.routers import router as pipeline_router

# ── Ensure required directories exist ─────────────────────────────────────────
for d in ["uploads", "outputs/structured", "outputs/raw_ocr"]:
    Path(d).mkdir(parents=True, exist_ok=True)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Property OCR Pipeline",
    description="Sarvam OCR + Groq Structuring for property documents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Initialize statute RAG store on startup ──────────────────────────────────
from backend.services.statute_rag import initialize_statute_store


@app.on_event("startup")
async def startup():
    try:
        initialize_statute_store()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to initialize statute store: %s", e)


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
