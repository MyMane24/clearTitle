"""Case title-chain task (Phase A).

Builds or reuses the case's title chain after document processing finishes. It is
idempotent: an existing chain is kept unless a history document or deed it did
not use has arrived.
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True)
def run_case_analysis_task(case_id: str, force: bool = False):
    """Build the case's title chain, or pause until its history document arrives.

    ``force`` rebuilds an existing chain even when no new chain document arrived
    (the dashboard's manual rebuild).
    """
    from backend.integrations.redis.state_store import append_log
    from backend.services.cleartitle_agent import run_case_analysis

    logger.info("Building title chain for case %s", case_id)
    try:
        outcome = run_case_analysis(case_id, force=force)
    except Exception as e:
        logger.error("Title-chain build failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Title-chain build failed: {e}")
        return {"case_id": case_id, "status": "error", "error": str(e)}

    status = outcome.get("status")
    if status == "done":
        append_log(case_id, f"✓ Title chain ready — {outcome.get('links', 0)} links")
    elif status == "paused":
        append_log(case_id, "⚠ Title chain paused — upload the Encumbrance Certificate to continue.")
    elif status == "error":
        append_log(case_id, f"✗ Title-chain build failed: {outcome.get('error') or outcome.get('reason') or 'unknown error'}")
    return outcome
