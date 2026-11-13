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
    for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
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
GOOGLE_FRONTEND_REDIRECT_URI = os.getenv("GOOGLE_FRONTEND_REDIRECT_URI", "http://localhost:8000/login")

# -- ClearTitle agent -----------------------------------------------------------
# The single ClearTitle agent is provider-agnostic. Production uses GPT-6 Luna via OpenAI.
CLEARTITLE_AGENT_PROVIDER = os.getenv("CLEARTITLE_AGENT_PROVIDER", "openai")
CLEARTITLE_AGENT_MODEL = os.getenv("CLEARTITLE_AGENT_MODEL", "GPT-6 Luna")
CLEARTITLE_AGENT_MAX_RAW_CHARS = int(os.getenv("CLEARTITLE_AGENT_MAX_RAW_CHARS", "60000"))
CLEARTITLE_VERIFY_MODEL_CALL_MAX = max(16, min(24, int(os.getenv("CLEARTITLE_VERIFY_MODEL_CALL_MAX", "24"))))
CLEARTITLE_VERIFY_MODEL_CALL_BUDGET = max(
    3, min(CLEARTITLE_VERIFY_MODEL_CALL_MAX, int(os.getenv("CLEARTITLE_VERIFY_MODEL_CALL_BUDGET", "16")))
)
# Character budget for the case memory (progress ledger + previous-link handoffs)
# replayed into each transaction's fresh session.
CLEARTITLE_MEMORY_CHAR_BUDGET = max(4000, int(os.getenv("CLEARTITLE_MEMORY_CHAR_BUDGET", "24000")))
# Corrective nudges allowed when the model ends a turn without a tool call.
CLEARTITLE_MAX_NUDGES = max(0, min(5, int(os.getenv("CLEARTITLE_MAX_NUDGES", "2"))))
# Newest OCR tool results kept verbatim in a transaction session; older ones are
# replaced by a stub once the model has recorded observations for that document.
CLEARTITLE_KEEP_OCR_RESULTS = max(1, int(os.getenv("CLEARTITLE_KEEP_OCR_RESULTS", "2")))
# Newest OCR tool results kept verbatim in a transaction session; older ones are
# replaced by a stub once the model has recorded observations for that document.
CLEARTITLE_KEEP_OCR_RESULTS = max(1, int(os.getenv("CLEARTITLE_KEEP_OCR_RESULTS", "2")))
CLEARTITLE_AGENT_MAX_ATTEMPTS = max(1, int(os.getenv("CLEARTITLE_AGENT_MAX_ATTEMPTS", "5")))

# Separate override for the single-call OCR classification/extraction stage.
DOCUMENT_PROCESSOR_MODEL = os.getenv("DOCUMENT_PROCESSOR_MODEL", CLEARTITLE_AGENT_MODEL)
DOCUMENT_CLASSIFICATION_TOKEN_BUDGET = int(os.getenv("DOCUMENT_CLASSIFICATION_TOKEN_BUDGET", "3000"))

# OpenAI / Azure OpenAI settings
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-02-15-preview")

# -- API / app ------------------------------------------------------------------
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
).split(",")
PIPELINE_LOCK_ENABLED = os.getenv("PIPELINE_LOCK_ENABLED", "true").lower() == "true"
