"""Case finalization task (chord callback) — moved from `backend.tasks.pipeline_tasks`.

Only the `finalize_case_task` chord callback lives here.
All per-document pipeline logic is in `backend.workers.tasks` + `backend.workers.stages`.
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


def _should_start_agent(docs: list[dict], memory: dict) -> bool:
    has_structured_documents = any(doc.get("status") == "structured" for doc in docs)
    has_pending_verification = bool(
        memory.get("paused_transaction") or memory.get("pending_tx_ids")
        or memory.get("evidence_retry_tx_id")
        or (memory.get("status") == "PENDING_NOT_VERIFIED" and memory.get("current_tx_id"))
    )
    return has_structured_documents or has_pending_verification


# -- Case finalization task (chord callback) -----------------------------------

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
            f"-- Pipeline done: {success_count} complete, {failed_count} failed --"
        )
    except Exception as e:
        logger.error("Failed to log pipeline completion to DB: %s", e)

    # 3. Release pipeline lock
    try:
        from backend.integrations.redis.lock import RedisLock
        RedisLock(f"case:{case_id}:pipeline_lock").force_release()
    except Exception as e:
        logger.error("Failed to release pipeline lock for case %s: %s", case_id, e)

    # Start title-chain construction and verification once document processing
    # finishes. Pending cases resume only after new evidence is fully processed.
    try:
        from backend.database.repositories import agent_repo
        memory = agent_repo.get_agent_memory(case_id) or {}
        if _should_start_agent(get_case_documents(case_id), memory):
            from backend.workers.title_chain_tasks import run_case_analysis_task
            retry_skipped_tx_id = memory.get("evidence_retry_tx_id")
            paused_tx_id = memory.get("paused_transaction") or (
                memory.get("current_tx_id")
                if memory.get("current_stage") == "paused"
                and memory.get("status") == "PENDING_NOT_VERIFIED"
                else None
            )
            resume_paused = bool(paused_tx_id) and not retry_skipped_tx_id
            run_case_analysis_task.delay(case_id, resume_paused, retry_skipped_tx_id)
            action = "Retrying selected skipped transaction" if retry_skipped_tx_id else (
                "Resuming the paused transaction" if resume_paused
                else "Starting title-chain construction and transaction verification"
            )
            append_pipeline_log(case_id, f"-- {action} --")
    except Exception as e:
        logger.error("Failed to queue title-chain analysis for %s: %s", case_id, e)
