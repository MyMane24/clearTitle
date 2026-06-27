import os
from celery import Celery

# Codex/sandbox launches can inject a dead local proxy (127.0.0.1:9).
# The Sarvam and Groq SDKs use httpx, which honors these env vars by default.
# If left in place, external API calls fail with WinError 10061 or Lookup timed out.
for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    if os.getenv(proxy_var, "").startswith("http://127.0.0.1:9"):
        os.environ.pop(proxy_var, None)


celery_app = Celery(
    "property_ocr",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
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
    broker_transport_options={"visibility_timeout": 21600},
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=3600,
    task_time_limit=7200,
    result_expires=86400,
)
