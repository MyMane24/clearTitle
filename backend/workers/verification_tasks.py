"""Verification task: a thin Celery wrapper around the verification runner."""

from __future__ import annotations

import asyncio

from backend.celery_app import celery_app
from backend.config import PIPELINE_LOCK_ENABLED
from backend.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(ignore_result=True)
def run_verification_task(case_id: str, kind: str = "full", fresh: bool = False):
    """Run title verification for a case under the case's agent lock.

    The same lock guards the title-chain builder, so the chain never changes
    under a running verification. ``fresh`` examines every document again.
    """
    from backend.integrations.redis.state_store import append_log
    from backend.services.verification import runner
    from backend.services.verification.store import DbStore

    lock = None
    if PIPELINE_LOCK_ENABLED:
        try:
            from backend.integrations.redis.lock import RedisLock

            lock = RedisLock(f"case:{case_id}:agent_lock")
            if not lock.acquire():
                logger.info("verification skipped: case %s is busy", case_id)
                return {"case_id": case_id, "status": "busy"}
        except Exception as e:  # degrade to no-lock rather than fail
            logger.warning("agent lock unavailable for %s: %s", case_id, e)
            lock = None
    try:
        outcome = asyncio.run(
            runner.run(
                case_id, store=DbStore(), models=runner.default_models(), kind=kind, fresh=fresh
            )
        )
    finally:
        if lock is not None:
            lock.release()
    status = outcome.get("status")
    if status == "done":
        append_log(case_id, f"✓ Title verification done — report v{outcome.get('report_version')}")
    else:
        append_log(
            case_id,
            f"⚠ Title verification {status}: {outcome.get('error') or outcome.get('reason') or ''}",
        )
    return outcome
