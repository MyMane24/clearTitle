from celery import Celery

from backend.config import REDIS_URL

celery_app = Celery(
    "property_ocr",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "backend.workers.finalize",
        "backend.workers.tasks",
        "backend.workers.title_chain_tasks",
    ],
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

