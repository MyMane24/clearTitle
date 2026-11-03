"""Celery tasks for the ClearTitle single-agent workflow."""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True)
def skip_cleartitle_transaction_task(case_id: str, tx_id: str):
    """Mark a paused transaction as skipped, then continue the agent."""
    from backend.services.cleartitle_agent import skip_transaction

    logger.info("ClearTitle agent skip %s for case %s", tx_id, case_id)
    return skip_transaction(case_id, tx_id)
