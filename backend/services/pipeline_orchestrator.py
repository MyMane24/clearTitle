"""
Orchestrator functions for firing Celery chords.
Thin layer between the API router and Celery tasks.
"""

from celery import chord

from backend.tasks.pipeline_tasks import process_document_task, finalize_case_task
from backend.services.redis_store import get_case_files
from backend.services.mysql_store import get_failed_documents, get_case_documents


def start_case_pipeline(case_id: str):
    """Fire individual doc tasks as a Celery chord for unprocessed docs only."""
    files_data = get_case_files(case_id)
    if not files_data:
        raise ValueError(f"No files found for case {case_id}")

    # Fetch document statuses from MySQL
    try:
        db_docs = get_case_documents(case_id)
        status_by_id = {d["doc_id"]: d["status"] for d in db_docs}
    except Exception:
        status_by_id = {}

    # Filter documents that are NOT structured and NOT skipped
    todo_files = [
        f for f in files_data
        if status_by_id.get(f["doc_id"]) not in ("structured", "skipped")
    ]

    callback = finalize_case_task.s(case_id)
    if todo_files:
        doc_tasks = [process_document_task.s(case_id, f["doc_id"]) for f in todo_files]
        chord(doc_tasks)(callback)
    else:
        # If no documents need processing, trigger the callback immediately
        finalize_case_task.delay([], case_id)


def start_retry_pipeline(case_id: str):
    """Fire tasks for failed docs only, as a Celery chord."""
    failed = get_failed_documents(case_id)
    if not failed:
        raise ValueError(f"No failed documents for case {case_id}")

    failed_ids = {d["doc_id"] for d in failed}
    files_data = get_case_files(case_id)
    tasks = [process_document_task.s(case_id, f["doc_id"]) for f in files_data if f["doc_id"] in failed_ids]
    if not tasks:
        raise ValueError(f"No file info found for failed docs in case {case_id}")

    callback = finalize_case_task.s(case_id)
    chord(tasks)(callback)
