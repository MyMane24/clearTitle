"""
Celery application for distributed document processing.
Run worker:   celery -A backend.celery_app worker --loglevel=info --concurrency=4
Monitor:      celery -A backend.celery_app flower --port=5555
"""

from celery import Celery

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
