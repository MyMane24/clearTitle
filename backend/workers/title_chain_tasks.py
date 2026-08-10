"""Case-level analysis tasks: title-chain build + verification (chained after finalize)."""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True, autoretry_for=(Exception,), max_retries=2,
                 retry_backoff=True, acks_late=True)
def build_title_chain_task(case_id: str):
    from backend.integrations.redis.state_store import append_log
    from backend.services.title_chain import build_title_chain

    logger.info("Building title chain for case %s", case_id)
    try:
        result = build_title_chain(case_id)
        status = result.get("status")
        if status == "complete":
            append_log(case_id, f"── Title chain built: {len(result.get('chain', []))} entry(s) ──")
        elif status == "no_transactions":
            append_log(case_id, "⚠ No transactions exist for this property in EC — please upload a valid EC.")
        else:
            append_log(case_id, f"── Title chain: {status} (partial or no EC/SD) ──")
    except Exception as e:
        logger.error("Title chain build failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Title chain build failed: {e}")
        raise
    return {"case_id": case_id}


@celery_app.task(ignore_result=True, autoretry_for=(Exception,), max_retries=2,
                 retry_backoff=True, acks_late=True)
def verify_case_task(case_id: str):
    from backend.integrations.redis.state_store import append_log
    from backend.services.verify import verify_case

    logger.info("Verifying case %s", case_id)
    try:
        result = verify_case(case_id)
        verdict = result.get("verdict", "N/A")
        append_log(case_id, f"── Verification complete: {verdict} ──")
    except Exception as e:
        logger.error("Verification failed for case %s: %s", case_id, e)
        append_log(case_id, f"✗ Verification failed: {e}")
        raise
    return {"case_id": case_id}
