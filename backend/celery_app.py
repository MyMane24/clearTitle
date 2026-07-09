import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Codex/sandbox launches can inject a dead local proxy (127.0.0.1:9).
# The Sarvam and Groq SDKs use httpx, which honors these env vars by default.
# If left in place, external API calls fail with WinError 10061 or Lookup timed out.
for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
        os.environ.pop(proxy_var, None)


_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "property_ocr",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=["backend.tasks.pipeline_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # visibility_timeout must be > task_time_limit so a crashed-worker task
    # reappears in the queue after the hard kill (7200 s) plus a small buffer,
    # not after 6 hours (the old value of 21600).
    broker_transport_options={"visibility_timeout": 7500},
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=3600,
    task_time_limit=7200,
    result_expires=86400,
    # Chord join timeout must be <= result_expires so Celery does not wait
    # forever for a task result that already expired from Redis.
    result_backend_transport_options={
        "result_chord_join_timeout": 7200,   # match task_time_limit
        "retry_policy": {"timeout": 5.0},
    },
)

