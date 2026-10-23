"""Case-level analysis task: the ClearTitle verification agent.

The agent *is* the verification — it replaces the old separate title-chain build
and verification LLM passes. It is idempotent and resumable: re-running it
resumes from `case_memory` instead of rebuilding.
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True)
def run_case_analysis_task(case_id: str):
    """Build Phase A if needed and verify transactions directly from the saved chain."""
    from backend.integrations.redis.state_store import append_log
    from backend.services.cleartitle_agent import run_agent

    logger.info("Running ClearTitle agent for case %s", case_id)
    try:
        outcome = run_agent(case_id)
    except Exception as e:  # noqa: BLE001 - record failure, don't crash the worker
        logger.error("ClearTitle agent failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Verification failed: {e}")
        return {"case_id": case_id, "status": "error", "error": str(e)}

    status = outcome.get("status")
    if status == "done":
        append_log(case_id, "✓ Transaction verification pass complete")
    elif status == "paused":
        append_log(case_id, "⚠ Verification paused — a document is required to continue.")
    elif status == "error":
        append_log(case_id, f"✗ Verification failed: {outcome.get('error') or outcome.get('reason') or 'unknown error'}")
    return outcome
