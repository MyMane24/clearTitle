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
    """Remove injected dead-proxy env vars that can block outbound HTTP calls."""
    for proxy_var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
            os.environ.pop(proxy_var, None)


_scrub_dead_proxies()

# -- Redis ----------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# -- MySQL ----------------------------------------------------------------------
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", os.getenv("MYSQL_DATABASE_V2", "property_ocr_v2"))

# -- API keys -------------------------------------------------------------------
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# -- Optional Gemini verification-agent rate limits ------------------------------
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "30"))
GEMINI_TPM = int(os.getenv("GEMINI_TPM", "4000000"))
GEMINI_BURST = int(os.getenv("GEMINI_BURST", "5"))

# -- Uploads --------------------------------------------------------------------
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100"))

# -- Auth / JWT -----------------------------------------------------------------
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "cleartitle-secret-key-production-change-me-12345")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

# -- Google OAuth ---------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
GOOGLE_FRONTEND_REDIRECT_URI = os.getenv(
    "GOOGLE_FRONTEND_REDIRECT_URI", "http://localhost:8000/login"
)

# -- ClearTitle models ----------------------------------------------------------
# Provider-agnostic. Production uses GPT-6 Luna via OpenAI.
CLEARTITLE_AGENT_PROVIDER = os.getenv("CLEARTITLE_AGENT_PROVIDER", "openai")
CLEARTITLE_AGENT_MODEL = os.getenv("CLEARTITLE_AGENT_MODEL", "GPT-6 Luna")
# Model calls the title-chain builder may spend reading history documents and saving.
CLEARTITLE_CHAIN_MODEL_CALL_BUDGET = max(
    3, int(os.getenv("CLEARTITLE_CHAIN_MODEL_CALL_BUDGET", "16"))
)
CLEARTITLE_AGENT_MAX_ATTEMPTS = max(1, int(os.getenv("CLEARTITLE_AGENT_MAX_ATTEMPTS", "5")))

# -- Verification agent --------------------------------------------------------
# Model per role; each defaults to CLEARTITLE_AGENT_MODEL on the same provider.
VERIFY_LEAD_MODEL = os.getenv("VERIFY_LEAD_MODEL", "") or CLEARTITLE_AGENT_MODEL
VERIFY_EXAMINER_MODEL = os.getenv("VERIFY_EXAMINER_MODEL", "") or CLEARTITLE_AGENT_MODEL
VERIFY_REPORT_MODEL = os.getenv("VERIFY_REPORT_MODEL", "") or CLEARTITLE_AGENT_MODEL
# Model calls the Lead may make in one run (the Document Examiner makes one call per document).
VERIFY_LEAD_CALL_BUDGET = max(5, int(os.getenv("VERIFY_LEAD_CALL_BUDGET", "100")))
VERIFY_REPORT_CALL_BUDGET = max(1, int(os.getenv("VERIFY_REPORT_CALL_BUDGET", "6")))
# Lead history stays append-only (cache-friendly) until its tool traffic passes this many
# characters; then older tool results and long arguments are cleared in one go.
VERIFY_COMPACT_AT_CHARS = max(10000, int(os.getenv("VERIFY_COMPACT_AT_CHARS", "30000")))
# A run stops (status incomplete, progress saved) once its estimated model cost passes this.
VERIFY_RUN_COST_LIMIT_USD = float(os.getenv("VERIFY_RUN_COST_LIMIT_USD", "0.50"))

# Separate override for the single-call OCR classification/extraction stage.
DOCUMENT_PROCESSOR_MODEL = os.getenv("DOCUMENT_PROCESSOR_MODEL", CLEARTITLE_AGENT_MODEL)
DOCUMENT_CLASSIFICATION_TOKEN_BUDGET = int(
    os.getenv("DOCUMENT_CLASSIFICATION_TOKEN_BUDGET", "3000")
)

# OpenAI / Azure OpenAI settings
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-02-15-preview")

# -- API / app ------------------------------------------------------------------
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
).split(",")
PIPELINE_LOCK_ENABLED = os.getenv("PIPELINE_LOCK_ENABLED", "true").lower() == "true"
