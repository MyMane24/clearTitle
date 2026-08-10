"""
Redis-backed sliding-window rate limiter for LLM API calls.
Coordinates across all Celery workers via Redis.

Extracted verbatim from `backend/services/rate_limiter.py`.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from backend.config import (
    GEMINI_BURST,
    GEMINI_RPM,
    GEMINI_TPM,
    GROQ_BURST,
    GROQ_RPM,
    GROQ_TPM,
)
from backend.integrations.redis.client import get_redis as _get_redis
from backend.logger import get_logger

logger = get_logger(__name__)


# ── Rate limit config ─────────────────────────────────────────────────────────

@dataclass
class RateLimitConfig:
    requests_per_minute: int = 30
    tokens_per_minute: int = 4_000_000
    burst_size: int = 5


GEMINI_LIMITS = RateLimitConfig(
    requests_per_minute=GEMINI_RPM,
    tokens_per_minute=GEMINI_TPM,
    burst_size=GEMINI_BURST,
)

GROQ_LIMITS = RateLimitConfig(
    requests_per_minute=GROQ_RPM,
    tokens_per_minute=GROQ_TPM,
    burst_size=GROQ_BURST,
)


# ── Lua script for atomic token-bucket acquire ────────────────────────────────
#
# All three pipeline calls in the old _try_acquire (TIME, read-state,
# write-state) are collapsed into ONE Lua script that Redis executes
# atomically.  No other command can interleave between the read and the
# write, so two concurrent workers can never both see "allowed" for the
# same token slot.
#
# KEYS[1] = ratelimit:<prefix>:requests  (sorted set of request timestamps)
# KEYS[2] = ratelimit:<prefix>:tokens    (string: current token count)
# KEYS[3] = ratelimit:<prefix>:refill    (string: last refill timestamp)
# ARGV[1] = window_seconds  (60.0)
# ARGV[2] = burst_size      (max tokens in the bucket)
# ARGV[3] = tokens_per_minute
# ARGV[4] = requests_per_minute
# ARGV[5] = tokens_needed   (1)
# ARGV[6] = unique sorted-set member (random string to avoid collisions)
#
# Returns: 1 = acquired, 0 = rate-limited

_ACQUIRE_LUA = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000.0
local window_start = now - tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, window_start)
local recent = tonumber(redis.call('ZCARD', KEYS[1]))
local tokens_raw  = redis.call('GET', KEYS[2])
local refill_raw  = redis.call('GET', KEYS[3])
local burst  = tonumber(ARGV[2])
local tpm    = tonumber(ARGV[3])
local rpm    = tonumber(ARGV[4])
local needed = tonumber(ARGV[5])
local cur = burst
if tokens_raw then cur = tonumber(tokens_raw) end
local last_refill = now
if refill_raw then last_refill = tonumber(refill_raw) end
cur = math.min(cur + (now - last_refill) * (tpm / 60.0), burst)
if recent >= rpm or cur < needed then
    redis.call('SET', KEYS[2], tostring(cur))
    redis.call('SET', KEYS[3], tostring(now))
    return 0
end
cur = cur - needed
redis.call('ZADD', KEYS[1], tostring(now), ARGV[6])
redis.call('SET', KEYS[2], tostring(cur))
redis.call('SET', KEYS[3], tostring(now))
return 1
"""


# ── Rate limiter class ────────────────────────────────────────────────────────

class TokenBucketRateLimiter:
    """Redis-based token bucket limiter shared across workers."""

    def __init__(self, key_prefix: str, config: RateLimitConfig):
        self.prefix = key_prefix
        self.config = config

    def _tokens_key(self) -> str:
        return f"ratelimit:{self.prefix}:tokens"

    def _refill_key(self) -> str:
        return f"ratelimit:{self.prefix}:refill"

    def _request_key(self) -> str:
        return f"ratelimit:{self.prefix}:requests"

    def _window_key(self) -> str:
        return f"ratelimit:{self.prefix}:window"

    def acquire(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """
        Try to acquire `tokens` from the bucket. Blocks up to `timeout` seconds.
        Returns True if acquired, False if timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            allowed, wait = self._try_acquire(tokens)
            if allowed:
                return True
            if wait > 0:
                sleep_time = min(wait + random.uniform(0, 0.5), 1.0)
                time.sleep(sleep_time)
            else:
                time.sleep(0.1)
        return False

    def _try_acquire(self, tokens: int = 1) -> tuple[bool, float]:
        """
        Returns (allowed, wait_seconds).
        Implemented as a single atomic Lua script — no race between
        reading the bucket state and committing the deduction.
        """
        r: Any = _get_redis()
        result = r.eval(
            _ACQUIRE_LUA,
            3,                                          # numkeys
            self._request_key(),
            self._tokens_key(),
            self._refill_key(),
            60.0,                                       # window seconds
            float(self.config.burst_size),
            float(self.config.tokens_per_minute),
            float(self.config.requests_per_minute),
            float(tokens),
            str(random.random()),                       # unique sorted-set member
        )
        allowed = bool(result)
        return allowed, 0.0 if allowed else 1.0

    def wait_and_acquire(self, tokens: int = 1, max_retries: int = 10) -> bool:
        """
        Blocking acquire with exponential backoff.
        Default max_retries=10 (~105 s max wait) instead of the previous
        30 (~7.5 min), so a rate-limited Celery worker fails fast rather
        than freezing for minutes.
        """
        for attempt in range(max_retries):
            allowed, _ = self._try_acquire(tokens)
            if allowed:
                return True
            backoff = min(2 ** attempt + random.uniform(0, 1), 15.0)
            time.sleep(backoff)
        return False


gemini_limiter = TokenBucketRateLimiter("gemini", GEMINI_LIMITS)
groq_limiter   = TokenBucketRateLimiter("groq",   GROQ_LIMITS)


# ── LLM call tracker ─────────────────────────────────────────────────────────

class LLMCallTracker:
    """Logs per-call LLM metrics to a Redis list for cost/usage dashboards."""

    @staticmethod
    def record(provider: str, model: str, doc_type: str, input_tokens: int,
               output_tokens: int, cached_tokens: int, latency_ms: int,
               cost_usd: float, retry_count: int, status: str) -> dict[str, Any]:
        entry = {
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "provider":     provider,
            "model":        model,
            "doc_type":     doc_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "latency_ms":   latency_ms,
            "cost_usd":     round(cost_usd, 8),
            "retry_count":  retry_count,
            "status":       status,
        }
        # Pipeline lpush + ltrim into a single round-trip (was 2 separate calls)
        try:
            r = _get_redis()
            pipe = r.pipeline()
            pipe.lpush("llm_call_log", json.dumps(entry))
            pipe.ltrim("llm_call_log", 0, 9999)
            pipe.execute()
        except Exception as e:
            logger.warning("Failed to record LLM call metric: %s", e)

        return entry

    @staticmethod
    def get_recent(minutes: int = 60) -> list[dict]:
        r = _get_redis()
        raw_items = r.lrange("llm_call_log", 0, -1)
        items: list[Any] = cast(list[Any], raw_items)
        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        for item in items:
            try:
                entry = json.loads(item)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    results.append(entry)
            except Exception:
                pass
        return results
