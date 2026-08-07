"""Case finalization task (chord callback) — moved from `backend.tasks.pipeline_tasks`.

Only the `finalize_case_task` chord callback lives here.
All per-document pipeline logic is in `backend.workers.tasks` + `backend.workers.stages`.
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


# ── Case finalization task (chord callback) ───────────────────────────────────

@celery_app.task(ignore_result=True)
def finalize_case_task(results: list, case_id: str):
    """Runs once after ALL documents in the case have been processed."""
    from backend.database.repositories.case_repo import (
        recompute_case_status,
    )
    from backend.database.repositories.document_repo import get_case_documents
    from backend.database.repositories.verification_repo import append_pipeline_log

    # 1. Recompute MySQL case status (counts completed and failed documents)
    try:
        recompute_case_status(case_id)
    except Exception as e:
        logger.error("Failed to recompute case status in DB: %s", e)

    # 2. Re-read statuses from MySQL to compile logs
    new_status = "processing"
    try:
        docs = get_case_documents(case_id)
        failed_count = sum(
            1 for d in docs
            if d.get("status") in ("failed", "classification_failed")
        )
        success_count = sum(1 for d in docs if d.get("status") == "structured")

        new_status = "failed" if (success_count == 0 and failed_count > 0) else ("complete" if failed_count == 0 else "partial")
        from backend.integrations.redis.state_store import set_case_status
        set_case_status(case_id, new_status)

        append_pipeline_log(
            case_id,
            f"── Pipeline done: {success_count} complete, {failed_count} failed ──"
        )
    except Exception as e:
        logger.error("Failed to log pipeline completion to DB: %s", e)

    # 3. Release pipeline lock
    try:
        from backend.integrations.redis.lock import RedisLock
        RedisLock(f"case:{case_id}:pipeline_lock").force_release()
    except Exception as e:
        logger.error("Failed to release pipeline lock for case %s: %s", case_id, e)

    # 4. Follow-on analysis: title chain → verification (only when all docs structured)
    if new_status == "complete":
        from backend.workers.title_chain_tasks import build_title_chain_task, verify_case_task
        try:
            build_title_chain_task.apply_async(
                args=[case_id], link=verify_case_task.si(case_id)
            )
            logger.info("Queued title-chain + verification for case %s", case_id)
        except Exception as e:
            logger.error("Failed to queue title-chain + verification for case %s: %s", case_id, e)
