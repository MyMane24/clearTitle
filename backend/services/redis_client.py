"""
Shared Redis client singleton for the entire application.
Both redis_store and rate_limiter import from here so every module in
the same worker process shares a single connection pool instead of
opening separate pools to the same Redis URL.
"""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis

_client = None
_client_lock = threading.Lock()


def get_redis() -> "Redis":
    """
    Return the process-wide Redis client (lazy singleton).
    Reading REDIS_URL inside the function (not at import time) ensures
    load_dotenv() has already run before the connection is created.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
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
