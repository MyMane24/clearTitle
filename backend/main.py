"""
ClearTitle — Property OCR Pipeline FastAPI Application
Entry point: uvicorn backend.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import CORS_ORIGINS, GEMINI_API_KEY, GROQ_API_KEY, SARVAM_API_KEY
from backend.logger import get_logger
from backend.routers import auth as auth_router
from backend.routers import cases as cases_router
from backend.routers import results as results_router

logger = get_logger(__name__)

# ── Ensure required directories exist ─────────────────────────────────────────
for d in ["uploads", "outputs/structured", "outputs/raw_ocr"]:
    Path(d).mkdir(parents=True, exist_ok=True)

# ── Lifespan (replaces deprecated @app.on_event) ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB tables once
    from backend.database.migrations import ensure_tables
    try:
        ensure_tables()
    except Exception as e:
        logger.warning("Failed to initialize database tables: %s", e)
    yield


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ClearTitle Property Verification Engine",
    description="Sarvam OCR + LLM structuring + title-chain verification for property documents",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── API routes ─────────────────────────────────────────────────────────────────
app.include_router(auth_router.router, prefix="/api")
app.include_router(cases_router.router, prefix="/api")
app.include_router(results_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "sarvam_key": bool(SARVAM_API_KEY),
        "groq_key":   bool(GROQ_API_KEY),
        "gemini_key": bool(GEMINI_API_KEY),
    }


# ── Serve frontend ─────────────────────────────────────────────────────────────
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SPA_DIST = FRONTEND / "dist"

app.mount("/static", StaticFiles(directory=str(FRONTEND / "public")), name="static")

if SPA_DIST.exists():
    assets_dir = SPA_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", response_class=FileResponse)
    async def spa(full_path: str):
        # SPA fallback: serve the built file if it exists, otherwise index.html
        # so client-side routes like /app survive a refresh / direct visit.
        candidate = (SPA_DIST / full_path).resolve()
        if candidate.is_relative_to(SPA_DIST.resolve()) and candidate.is_file():
            return candidate
        return FileResponse(SPA_DIST / "index.html")
else:
    @app.get("/", response_class=FileResponse)
    async def serve_ui():
        return FileResponse(FRONTEND / "index.html")
