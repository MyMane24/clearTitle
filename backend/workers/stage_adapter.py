"""Task → stage.invoke adapter.

This is the ONLY place where a Celery task meets a stage: build a `StageContext`
and invoke the stage.
"""

from __future__ import annotations

from backend.database.repositories import document_repo as state_port
from backend.workers.context import StageContext


def build_context(case_id: str, doc_id: str) -> StageContext:
    """Build a StageContext over the repository state port."""
    return StageContext(case_id=case_id, doc_id=doc_id, state=state_port)


def run_stage(stage, *, task_name: str, case_id: str, doc_id: str) -> dict:
    """Run a stage through its invoke contract, wrapped by the worker adapter."""
    return stage.invoke(build_context(case_id, doc_id))


__all__ = ["StageContext", "build_context", "run_stage"]
