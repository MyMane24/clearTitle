"""
Orchestrator functions for firing Celery chords.
Thin layer between the API router and Celery tasks.
"""

import os
from celery import chord, chain

from backend.tasks.pipeline_tasks import process_document_task, finalize_case_task
from backend.services.redis_store import get_case_files
from backend.services.mysql_store import get_failed_documents, get_case_documents

# Import V2 tasks
from backend.pipeline.tasks import (
    preprocess_document_task,
    ocr_document_task,
    merge_ocr_task,
    classify_document_task,
    structure_document_task,
    persist_document_task,
)


def build_document_chain(case_id: str, doc_id: str):
    """Build the 6-stage chain for a single document."""
    return chain(
        preprocess_document_task.si(case_id, doc_id),
        ocr_document_task.si(case_id, doc_id),
        merge_ocr_task.si(case_id, doc_id),
        classify_document_task.si(case_id, doc_id),
        structure_document_task.si(case_id, doc_id),
        persist_document_task.si(case_id, doc_id),
    )


def start_case_pipeline(case_id: str):
    """Fire individual doc tasks/chains as a Celery chord for unprocessed docs only."""
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
    
    if not todo_files:
        # If no documents need processing, trigger the callback immediately
        finalize_case_task.delay([], case_id)
        return

    # Check if PIPELINE_V2_ENABLED is active
    v2_enabled = os.getenv("PIPELINE_V2_ENABLED", "true").lower() == "true"
    
    if v2_enabled:
        doc_tasks = [build_document_chain(case_id, f["doc_id"]) for f in todo_files]
    else:
        doc_tasks = [process_document_task.s(case_id, f["doc_id"]) for f in todo_files]
        
    chord(doc_tasks)(callback)


def start_retry_pipeline(case_id: str):
    """Fire tasks for failed docs only, as a Celery chord."""
    failed = get_failed_documents(case_id)
    if not failed:
        raise ValueError(f"No failed documents for case {case_id}")

    failed_ids = {d["doc_id"] for d in failed}
    files_data = get_case_files(case_id)
    todo_files = [f for f in files_data if f["doc_id"] in failed_ids]
    
    if not todo_files:
        raise ValueError(f"No file info found for failed docs in case {case_id}")

    callback = finalize_case_task.s(case_id)
    
    # Check if PIPELINE_V2_ENABLED is active
    v2_enabled = os.getenv("PIPELINE_V2_ENABLED", "true").lower() == "true"
    
    if v2_enabled:
        doc_tasks = [build_document_chain(case_id, f["doc_id"]) for f in todo_files]
    else:
        doc_tasks = [process_document_task.s(case_id, f["doc_id"]) for f in todo_files]
        
    chord(doc_tasks)(callback)
