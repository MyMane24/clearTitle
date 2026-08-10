"""Gemini client + per-doc-type context-cache management (plan §4.3)."""
import time

from google import genai
from google.genai import types

from backend.config import (
    GEMINI_API_KEY,
    GEMINI_CACHE_TTL,
    GEMINI_MODEL,
)
from backend.logger import get_logger
from backend.services.extraction_prompts import _build_static_content

logger = get_logger(__name__)

CACHE_TTL_SECONDS = GEMINI_CACHE_TTL
# ── Context cache (per doc_type) ───────────────────────────────────────────
# Keys: doc_type -> {"cache_name": str, "cache_id": str, "created_at": float}

_context_caches: dict[str, dict] = {}
_cache_client = None


def _get_cache_client():
    global _cache_client
    if _cache_client is None:
        _cache_client = genai.Client(api_key=GEMINI_API_KEY)
    return _cache_client
def _ensure_context_cache(doc_type: str) -> str | None:
    """
    Create or refresh a Gemini context cache for the static content of this doc_type.
    Returns the cache name (e.g. "cachedContents/abc123") or None if caching fails.
    """
    try:
        import hashlib
        static_content = _build_static_content(doc_type)
        content_hash = hashlib.md5(static_content.encode("utf-8")).hexdigest()
        cache_client = _get_cache_client()

        existing = _context_caches.get(doc_type)
        if existing:
            if existing.get("hash") == content_hash:
                try:
                    # Refresh TTL on existing cache
                    cache_client.caches.update(
                        name=existing["cache_name"],
                        config={"ttl": f"{CACHE_TTL_SECONDS}s"},
                    )
                    return existing["cache_name"]
                except Exception:
                    pass
            else:
                # Delete stale cache on server
                try:
                    cache_client.caches.delete(name=existing["cache_name"])
                except Exception:
                    pass

        # Create new cache — SDK expects Content objects; wrap appropriately
        response = cache_client.caches.create(
            model=GEMINI_MODEL,
            config=types.CreateCachedContentConfig(
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=static_content)]
                    )
                ],
                ttl=f"{CACHE_TTL_SECONDS}s",
            ),
        )
        cache_name = response.name
        _context_caches[doc_type] = {
            "cache_name": cache_name,
            "hash": content_hash,
            "created_at": time.time(),
        }
        logger.info("Created context cache for %s: %s", doc_type, cache_name)
        return cache_name

    except Exception as e:
        logger.warning("Failed to create/refresh context cache for %s: %s", doc_type, e)
        return None
