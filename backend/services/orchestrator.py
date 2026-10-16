"""Orchestrator functions for firing Celery chords — moved from
`backend.services.pipeline_orchestrator`. Thin layer between the API router and
Celery tasks.
"""

from celery import chain, chord

from backend.database.repositories.document_repo import (
    get_case_documents,
    get_document_resume_state,
    get_failed_documents,
)
from backend.integrations.redis.state_store import get_case_files
from backend.workers.finalize import finalize_case_task
from backend.workers.tasks import (
    classify_document_task,
    merge_ocr_task,
    ocr_document_task,
    persist_document_task,
    preprocess_document_task,
    structure_document_task,
)


def _resume_stage(checkpoint: dict) -> str:
    paths = checkpoint.get("file_paths") or {}
    if isinstance(paths, str):
        try:
            import json
            paths = json.loads(paths)
        except (TypeError, ValueError):
            paths = {}
    structured = checkpoint.get("structured_data")
    if isinstance(structured, str):
        try:
            import json
            structured = json.loads(structured)
        except (TypeError, ValueError):
            structured = None
    if structured and checkpoint.get("document_type"):
        return "persist"
    if checkpoint.get("document_type") and (checkpoint.get("merged_ocr_text") or paths.get("merged_ocr")):
        return "structure"
    if checkpoint.get("merged_ocr_text") or paths.get("merged_ocr"):
        return "classify"
    return "preprocess"


def build_document_chain(case_id: str, doc_id: str, *, resume_from: str = "preprocess"):
    """Build a pipeline suffix from the last durable checkpoint."""
    stages = {
        "preprocess": preprocess_document_task.si(case_id, doc_id),
        "ocr": ocr_document_task.si(case_id, doc_id),
        "merge": merge_ocr_task.si(case_id, doc_id),
        "classify": classify_document_task.si(case_id, doc_id),
        "structure": structure_document_task.si(case_id, doc_id),
        "persist": persist_document_task.si(case_id, doc_id),
    }
    order = list(stages)
    return chain(*(stages[name] for name in order[order.index(resume_from):]))


def start_case_pipeline(case_id: str):
    """Fire individual doc chains as a Celery chord for unprocessed docs only."""
    files_data = get_case_files(case_id)
    if not files_data:
        raise ValueError(f"No files found for case {case_id}")

    try:
        db_docs = get_case_documents(case_id)
        status_by_id = {d["doc_id"]: d["status"] for d in db_docs}
    except Exception:
        status_by_id = {}

    todo_files = [
        f for f in files_data
        if status_by_id.get(f["doc_id"]) not in ("structured", "skipped")
    ]

    callback = finalize_case_task.s(case_id)

    if not todo_files:
        finalize_case_task.delay([], case_id)
        return

    doc_tasks = [build_document_chain(case_id, f["doc_id"]) for f in todo_files]
    chord(doc_tasks)(callback)


def start_retry_pipeline(case_id: str):
    """Fire tasks for failed docs only, as a Celery chord."""
    failed = get_failed_documents(case_id)
    if not failed:
        raise ValueError(f"No failed documents for case {case_id}")

    files_data = get_case_files(case_id)
    files_by_id = {f["doc_id"]: f for f in files_data}
    todo_files = []
    for item in failed:
        doc_id = item["doc_id"]
        doc = get_document_resume_state(case_id, doc_id)
        resume_from = _resume_stage(doc)
        file_info = files_by_id.get(doc_id)
        if file_info:
            todo_files.append((file_info, resume_from))

    if len(todo_files) != len(failed):
        raise ValueError(f"No file info found for failed docs in case {case_id}")

    callback = finalize_case_task.s(case_id)

    doc_tasks = [build_document_chain(case_id, f["doc_id"], resume_from=resume_from) for f, resume_from in todo_files]
    chord(doc_tasks)(callback)
