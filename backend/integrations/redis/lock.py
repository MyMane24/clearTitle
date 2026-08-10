import threading
import uuid

from backend.integrations.redis.client import get_redis
from backend.logger import get_logger

logger = get_logger(__name__)

# Lua script to release lock atomically check token
_RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Lua script to refresh lock atomically check token
_REFRESH_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class RedisLock:
    def __init__(self, key: str, ttl_ms: int = 1800000):
        self.key = key
        self.ttl_ms = ttl_ms
        self.token = str(uuid.uuid4())
        self.r = get_redis()
        self._refresh_timer = None
        self._is_held = False
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        # SET key token NX PX ttl_ms
        success = self.r.set(self.key, self.token, nx=True, px=self.ttl_ms)
        if success:
            with self._lock:
                self._is_held = True
                self._start_refresh_timer()
            return True
        return False

    def release(self) -> None:
        with self._lock:
            if not self._is_held:
                return
            self._is_held = False
            self._stop_refresh_timer()

        try:
            self.r.eval(_RELEASE_LUA, 1, self.key, self.token)
        except Exception as e:
            logger.error("Failed to release Redis lock %s: %s", self.key, e)

    def force_release(self) -> None:
        with self._lock:
            self._is_held = False
            self._stop_refresh_timer()
        try:
            self.r.delete(self.key)
        except Exception as e:
            logger.error("Failed to force release Redis lock %s: %s", self.key, e)

    def refresh(self) -> bool:
        with self._lock:
            if not self._is_held:
                return False
        try:
            res = self.r.eval(_REFRESH_LUA, 1, self.key, self.token, self.ttl_ms)
            success = bool(res)
            if not success:
                logger.warning("Lock %s refresh failed (token mismatch or expired)", self.key)
                with self._lock:
                    self._is_held = False
                    self._stop_refresh_timer()
            return success
        except Exception as e:
            logger.error("Error refreshing lock %s: %s", self.key, e)
            return False

    def _start_refresh_timer(self):
        # Refresh lock at 1/3 of TTL to ensure it remains active
        # TTL is 30 mins (1800s) -> refresh every 10 mins (600s).
        # We can also do 5 mins (300s) as requested.
        if not self._is_held:
            return
        self._refresh_timer = threading.Timer(300.0, self._timer_callback)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _stop_refresh_timer(self):
        if self._refresh_timer:
            self._refresh_timer.cancel()
            self._refresh_timer = None

    def _timer_callback(self):
        if self.refresh():
            with self._lock:
                self._start_refresh_timer()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock: {self.key}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
