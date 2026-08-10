"""Single env/config loader (Phase 4 — P6 fix).

All `os.getenv` reads in the project live here. Every other module imports its
settings from this module instead of touching the environment. Env var names
and defaults are preserved exactly (no renaming, per plan §10).

Loads `.env` once at import; also scrubs the dead local proxy (127.0.0.1:9)
that Codex/sandbox launches can inject, so consumers no longer duplicate that
logic.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _scrub_dead_proxies() -> None:
    """Remove injected dead-proxy env vars (Sarvam/Groq SDKs honor them via httpx)."""
    for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
            os.environ.pop(proxy_var, None)


_scrub_dead_proxies()

# ── Redis ──────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── MySQL ──────────────────────────────────────────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", os.getenv("MYSQL_DATABASE_V2", "property_ocr_v2"))

# ── API keys ───────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Gemini ─────────────────────────────────────────────────────────────────────
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_CONTEXT_CHARS = int(os.getenv("GEMINI_MAX_CONTEXT_CHARS", "800000"))
GEMINI_CACHE_TTL = int(os.getenv("GEMINI_CACHE_TTL", "3600"))

# ── Rate limits ────────────────────────────────────────────────────────────────
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "30"))
GEMINI_TPM = int(os.getenv("GEMINI_TPM", "4000000"))
GEMINI_BURST = int(os.getenv("GEMINI_BURST", "5"))
GROQ_RPM = int(os.getenv("GROQ_RPM", "60"))
GROQ_TPM = int(os.getenv("GROQ_TPM", "6000"))
GROQ_BURST = int(os.getenv("GROQ_BURST", "10"))

# ── Model routing ──────────────────────────────────────────────────────────────
MODEL_ROUTING_MAP = os.getenv("MODEL_ROUTING_MAP", "")

# ── Uploads ────────────────────────────────────────────────────────────────────
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

# ── Auth / JWT ─────────────────────────────────────────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "cleartitle-secret-key-production-change-me-12345")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

# ── API / app ──────────────────────────────────────────────────────────────────
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
).split(",")
PIPELINE_LOCK_ENABLED = os.getenv("PIPELINE_LOCK_ENABLED", "true").lower() == "true"
