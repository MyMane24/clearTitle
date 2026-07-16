"""
Shared Celery tasks for the document processing pipeline.
Only the finalize_case_task chord callback lives here.
All per-document pipeline logic is in backend.pipeline.tasks (V2).
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


# ── Case finalization task (chord callback) ───────────────────────────────────

@celery_app.task(ignore_result=True)
def finalize_case_task(results: list, case_id: str):
    """Runs once after ALL documents in the case have been processed."""
    from backend.services.mysql_store import (
        update_case_status as mysql_update_case_status,
        append_pipeline_log,
        get_case_documents,
    )

    # 1. Update MySQL database case status (counts completed and failed documents)
    try:
        mysql_update_case_status(case_id=case_id)
    except Exception as e:
        logger.error("Failed to recompute case status in DB: %s", e)

    # 2. Re-read statuses from MySQL to compile logs
    try:
        docs = get_case_documents(case_id)
        failed_count = sum(
            1 for d in docs
            if d.get("status") in ("failed", "classification_failed")
        )
        success_count = sum(1 for d in docs if d.get("status") == "structured")

        append_pipeline_log(
            case_id,
            f"── Pipeline done: {success_count} complete, {failed_count} failed ──"
        )
    except Exception as e:
        logger.error("Failed to log pipeline completion to DB: %s", e)

    # 3. Release pipeline lock
    try:
        from backend.locking.redis_lock import RedisLock
        RedisLock(f"case:{case_id}:pipeline_lock").force_release()
    except Exception as e:
        logger.error("Failed to release pipeline lock for case %s: %s", case_id, e)
