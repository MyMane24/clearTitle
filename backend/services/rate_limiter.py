"""
Redis-backed sliding-window rate limiter for LLM API calls.
Coordinates across all Celery workers via Redis.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass

from backend.logger import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_redis():
    try:
        import redis as redis_module
    except ImportError as exc:
        raise RuntimeError("redis-py not installed") from exc
    return redis_module.from_url(REDIS_URL, decode_responses=True)


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 30
    tokens_per_minute: int = 4_000_000
    burst_size: int = 5


GEMINI_LIMITS = RateLimitConfig(
    requests_per_minute=int(os.getenv("GEMINI_RPM", "30")),
    tokens_per_minute=int(os.getenv("GEMINI_TPM", "4000000")),
    burst_size=int(os.getenv("GEMINI_BURST", "5")),
)

GROQ_LIMITS = RateLimitConfig(
    requests_per_minute=int(os.getenv("GROQ_RPM", "60")),
    tokens_per_minute=int(os.getenv("GROQ_TPM", "15000000")),
    burst_size=int(os.getenv("GROQ_BURST", "10")),
)


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
        """Returns (allowed, wait_seconds)."""
        r = _get_redis()
        now = time.time()
        window = 60.0

        request_key = self._request_key()
        window_key = self._window_key()
        tokens_key = self._tokens_key()
        refill_key = self._refill_key()

        pipe = r.pipeline()
        pipe.time()
        results = pipe.execute()
        now = results[0][0] + results[0][1] / 1_000_000

        window_start = now - window

        pipe = r.pipeline()
        pipe.zremrangebyscore(request_key, 0, window_start)
        pipe.zcard(request_key)
        pipe.get(tokens_key)
        pipe.get(refill_key)
        results = pipe.execute()
        recent_count = results[1] or 0
        current_tokens = float(results[2]) if results[2] else float(self.config.burst_size)
        last_refill = float(results[3]) if results[3] else now

        elapsed = now - last_refill
        refill_rate = self.config.tokens_per_minute / 60.0
        current_tokens = min(
            current_tokens + elapsed * refill_rate,
            float(self.config.burst_size),
        )

        rpm_exceeded = recent_count >= self.config.requests_per_minute
        tpm_exceeded = current_tokens < tokens

        if rpm_exceeded or tpm_exceeded:
            pipe.set(tokens_key, str(current_tokens))
            pipe.set(refill_key, str(now))
            pipe.execute()
            return False, 1.0

        current_tokens -= tokens
        pipe.zadd(request_key, {str(random.random()): now})
        pipe.set(tokens_key, str(current_tokens))
        pipe.set(refill_key, str(now))
        pipe.execute()
        return True, 0

    def wait_and_acquire(self, tokens: int = 1, max_retries: int = 30):
        """Blocking acquire with retry."""
        for attempt in range(max_retries):
            allowed, _ = self._try_acquire(tokens)
            if allowed:
                return True
            backoff = min(2 ** attempt + random.uniform(0, 1), 15.0)
            time.sleep(backoff)
        return False


gemini_limiter = TokenBucketRateLimiter("gemini", GEMINI_LIMITS)
groq_limiter = TokenBucketRateLimiter("groq", GROQ_LIMITS)


class LLMCallTracker:
    """Logs per-call LLM metrics to a Redis list for cost/usage dashboards."""

    @staticmethod
    def record(provider: str, model: str, doc_type: str, input_tokens: int,
               output_tokens: int, cached_tokens: int, latency_ms: int,
               cost_usd: float, retry_count: int, status: str):
        from datetime import datetime
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": provider,
            "model": model,
            "doc_type": doc_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "latency_ms": latency_ms,
            "cost_usd": round(cost_usd, 8),
            "retry_count": retry_count,
            "status": status,
        }
        try:
            r = _get_redis()
            key = "llm_call_log"
            r.lpush(key, json.dumps(entry))
            r.ltrim(key, 0, 9999)
        except Exception as e:
            logger.warning("Failed to record LLM call metric: %s", e)
        # Also persist to MySQL for queryable dashboard
        try:
            from backend.services.mysql_store_v2 import log_llm_call
            log_llm_call(
                case_id=entry.get("case_id", ""), doc_id=entry.get("doc_id", ""),
                provider=provider, model=model, doc_type=doc_type,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cached_tokens=cached_tokens, latency_ms=latency_ms,
                cost_usd=cost_usd, retry_count=retry_count, status=status,
            )
        except Exception as e:
            logger.warning("Failed to persist LLM call to MySQL: %s", e)

        return entry

    @staticmethod
    def get_recent(minutes: int = 60) -> list[dict]:
        r = _get_redis()
        items = r.lrange("llm_call_log", 0, -1)
        results = []
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        for item in items:
            try:
                entry = json.loads(item)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= cutoff:
                    results.append(entry)
            except Exception:
                pass
        return results
