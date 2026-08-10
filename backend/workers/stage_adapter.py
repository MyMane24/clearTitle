"""Task → stage.invoke adapter.

This is the ONLY place where a Celery task meets a stage: build a `StageContext`,
load input, invoke the stage, persist the result.
"""

from __future__ import annotations

from backend.database.repositories import document_repo as state_port
from backend.integrations.llm import model_router as llm_port
from backend.integrations.redis import state_store as cache_port
from backend.integrations.storage import file_utils as storage_port
from backend.logger import get_logger
from backend.workers.context import StageContext

logger = get_logger(__name__)


def build_context(case_id: str, doc_id: str) -> StageContext:
    """Build a StageContext wiring today's singleton modules as ports."""
    return StageContext(
        case_id=case_id,
        doc_id=doc_id,
        config=None,
        llm=llm_port,
        cache=cache_port,
        storage=storage_port,
        state=state_port,
    )


def load_input(ctx: StageContext) -> dict:
    """Stage input payload.

    Stages load their own paths/state via `ctx.state` today, so input is just
    the identity of the document being processed.
    """
    return {"case_id": ctx.case_id, "doc_id": ctx.doc_id}


def persist(ctx: StageContext, result: dict) -> dict:
    """Persist a stage result.

    Stages write state themselves today; this is the Phase 3 hook where result
    persistence becomes an explicit repo call.
    """
    return result


def run_stage(stage, *, task_name: str, case_id: str, doc_id: str) -> dict:
    """Run a stage through its invoke contract, wrapped by the worker adapter."""
    ctx = build_context(case_id, doc_id)
    input_data = load_input(ctx)
    result = stage.invoke(ctx, input_data)
    return persist(ctx, result)


__all__ = ["StageContext", "build_context", "load_input", "persist", "run_stage"]
