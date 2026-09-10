"""Case-level analysis tasks: title-chain build + verification (chained after finalize)."""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True)
def run_case_analysis_task(case_id: str):
    """Title chain + verification as ONE orchestrator, always both.

    The old pattern chained verify behind build via Celery `link`, which only
    fires when the parent SUCCEEDS — so a title-chain failure silently killed
    verification and vice versa. Each phase here logs its own outcome and runs
    regardless of the other; both services already persist an 'error' row
    (rather than raising) when the LLM call fails.
    """
    from backend.integrations.redis.state_store import append_log
    from backend.services.title_chain import build_title_chain
    from backend.services.verify import verify_case

    logger.info("Running title chain + verification for case %s", case_id)

    try:
        tc = build_title_chain(case_id)
        tc_status = tc.get("status")
        if tc_status == "complete":
            append_log(case_id, f"── Title chain built: {len(tc.get('chain', []))} entry(s) ──")
        elif tc_status == "no_transactions":
            append_log(case_id, "⚠ No transactions exist for this property in EC — please upload a valid EC.")
        else:
            append_log(case_id, f"── Title chain: {tc_status} ──")
    except Exception as e:
        logger.error("Title chain build failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Title chain build failed: {e}")

    try:
        vf = verify_case(case_id)
        append_log(case_id, f"── Verification complete: {vf.get('verdict', 'N/A')} ──")
    except Exception as e:
        logger.error("Verification failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Verification failed: {e}")

    return {"case_id": case_id}
