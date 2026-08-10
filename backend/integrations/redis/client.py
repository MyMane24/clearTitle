"""
Shared Redis client singleton for the entire application.
Both state_store and rate_limiter import from here so every module in
the same worker process shares a single connection pool instead of
opening separate pools to the same Redis URL.

Extracted verbatim from `backend/services/redis_client.py`.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from backend.config import REDIS_URL

if TYPE_CHECKING:
    from redis import Redis

_client = None
_client_lock = threading.Lock()


def get_redis() -> Redis:
    """
    Return the process-wide Redis client (lazy singleton).
    REDIS_URL comes from `app.config`, which loads `.env` at import.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                redis_url = REDIS_URL
                try:
                    import redis as redis_module
                except ImportError as exc:
                    raise RuntimeError(
                        "redis-py is not installed. Run: pip install redis"
                    ) from exc
                _client = redis_module.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=20,
                )
    return _client
