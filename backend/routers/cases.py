"""
Case-level endpoints: upload, process, retry, status
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.celery_app import celery_app
from backend.constants import (
    STATUS_FAILED,
    STATUS_PENDING_RETRY,
    STATUS_PROCESSING,
)
from backend.logger import get_logger
from backend.services.file_service import list_output_cases
from backend.services.mysql_store import (
    delete_case as db_delete_case,
    get_classification_failed_documents,
    get_failed_documents,
    init_case,
    init_document,
    list_cases,
    update_document_status,
)
from backend.services.pipeline_orchestrator import (
    start_case_pipeline,
    start_retry_pipeline,
)
from backend.services.redis_store import (
    append_log,
    delete_case as redis_delete_case,
    flush_all_cases,
    get_case_job,
    reset_for_retry,
    set_case_status,
    add_files_to_case,
)
from backend.services.redis_store import (
    case_exists as redis_case_exists,
)
from backend.services.redis_store import (
    init_case as redis_init_case,
)
from backend.utils.file_utils import delete_case_dir, get_case_dir, save_upload

router = APIRouter()
logger = get_logger(__name__)


@router.get("/cases")
async def get_all_cases(limit: int = 50, offset: int = 0):
    """List historical cases from database plus output folders."""
    seen = set()
    merged = []

    # Try database
    try:
        db_cases = list_cases(limit=limit, offset=offset)
        for case in db_cases:
            case["source"] = "v2"
            case["db_version"] = "v2"
            seen.add(case["id"])
            merged.append(case)
    except Exception as e:
        logger.warning("Failed to list cases: %s", e)

    # Add file-system only cases (no DB record)
    output_cases = [c for c in list_output_cases() if c["id"] not in seen]
    merged.extend(output_cases)

    # Sort by created_at DESC (handle datetime, str, and None)
    def _sort_key(c):
        v = c.get("created_at")
        if isinstance(v, datetime):
            return v.timestamp()
        if isinstance(v, (int, float)):
            return v
        return 0

    merged.sort(key=_sort_key, reverse=True)
    return {"cases": merged, "total": len(merged)}


@router.delete("/case/{case_id}")
async def delete_case(case_id: str):
    """Delete everything related to a case: Redis, MySQL, and files on disk."""
    # Revoke active Celery tasks for this case
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            for worker, tasks in active.items():
                for task in tasks:
                    args = task.get("args", [])
                    if case_id in str(args):
                        celery_app.control.revoke(task["id"], terminate=True)
    except Exception as e:
        logger.warning("Failed to revoke Celery tasks for %s: %s", case_id, e)

    # Delete from Redis
    redis_deleted = 0
    try:
        redis_deleted = redis_delete_case(case_id)
    except Exception as e:
        logger.warning("Failed to delete Redis data for %s: %s", case_id, e)

    # Delete from MySQL
    try:
        db_delete_case(case_id)
    except Exception as e:
        logger.warning("Failed to delete DB records for %s: %s", case_id, e)

    # Delete files on disk
    fs_deleted = delete_case_dir(case_id)

    return {
        "case_id": case_id,
        "redis_keys_deleted": redis_deleted,
        "filesystem_deleted": fs_deleted,
        "message": f"Case {case_id} and all associated data deleted successfully.",
    }


@router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    case_id = str(uuid.uuid4())[:8].upper()
    case_dir = get_case_dir(case_id)

    saved = []
    for i, f in enumerate(files):
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail=f"{f.filename} is not a PDF")
        dest = await save_upload(f, case_dir / "raw")
        doc_id = f"DOC_{str(i+1).zfill(3)}"
        saved.append({
            "doc_id":        doc_id,
            "original_name": f.filename,
            "saved_path":    str(dest),
            "size_kb":       round(dest.stat().st_size / 1024, 1),
        })

    redis_init_case(case_id, saved)

    # Init in database
    try:
        init_case(case_id=case_id, total_docs=len(saved))
        for s in saved:
            init_document(
                case_id=case_id,
                doc_id=s["doc_id"],
                doc_index=int(s["doc_id"].split("_")[1]),
                filename=s["original_name"],
                file_paths={"raw": s["saved_path"]},
            )
    except Exception as e:
        append_log(case_id, f"⚠ DB init failed (non-fatal): {e}")

    return {"case_id": case_id, "files": saved}


@router.post("/process/{case_id}")
async def process_case(case_id: str):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    meta = get_case_job(case_id)
    if meta["status"] == STATUS_PROCESSING:
        raise HTTPException(status_code=409, detail="Already processing")

    set_case_status(case_id, STATUS_PROCESSING)
    append_log(case_id, "Starting Celery pipeline")

    try:
        start_case_pipeline(case_id)
    except Exception as e:
        set_case_status(case_id, STATUS_FAILED)
        append_log(case_id, f"FATAL: Failed to start pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "status": STATUS_PROCESSING, "mode": "celery"}


@router.get("/status/{case_id}")
async def get_status(case_id: str):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    job = get_case_job(case_id)

    action_errors = [
        e for e in job.get("errors", [])
        if e.get("action_required") == "replace_or_skip"
    ]
    needs_action = []
    if action_errors:
        file_info = {f["doc_id"]: f["original_name"] for f in job.get("files", [])}
        for e in action_errors:
            needs_action.append({
                "doc_id": e["doc_id"],
                "filename": file_info.get(e["doc_id"], e["doc_id"]),
            })
    else:
        try:
            needs_action = get_classification_failed_documents(case_id)
        except Exception as e:
            logger.warning("Failed to get classification_failed docs: %s", e)
            needs_action = []

    job["needs_action"] = [
        {
            "doc_id": d["doc_id"],
            "filename": d["filename"],
            "message": (
                f"'{d['filename']}' — document type not recognised. Choices:"
            ),
            "choices": [
                {"action": "skip", "method": "POST",
                 "url": f"/api/case/{case_id}/doc/{d['doc_id']}/skip",
                 "label": "Continue without this document"},
                {"action": "replace", "method": "POST",
                 "url": f"/api/case/{case_id}/doc/{d['doc_id']}/replace",
                 "label": "Upload a replacement document"},
            ],
        }
        for d in needs_action
    ]

    return job


@router.post("/retry/{case_id}")
async def retry_failed(case_id: str):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    meta = get_case_job(case_id)
    if meta["status"] == STATUS_PROCESSING:
        raise HTTPException(status_code=409, detail="Already processing")

    failed = get_failed_documents(case_id)
    classification_failed = get_classification_failed_documents(case_id)

    if not failed:
        msg = "No failed documents to retry."
        if classification_failed:
            doc_list = ", ".join(d["doc_id"] for d in classification_failed)
            msg += (f" {len(classification_failed)} document(s) have unrecognised types "
                    f"({doc_list}). Use POST /api/case/{case_id}/doc/<doc_id>/replace "
                    f"to upload a valid document, or /skip to proceed without it.")
        raise HTTPException(status_code=400, detail=msg)

    for doc in failed:
        try:
            update_document_status(
                case_id=case_id,
                doc_id=doc["doc_id"],
                status=STATUS_PENDING_RETRY,
            )
        except Exception as e:
            logger.warning("Failed to update status: %s", e)

    reset_for_retry(case_id)
    append_log(case_id, f"Retrying {len(failed)} failed document(s)")

    try:
        start_retry_pipeline(case_id)
    except Exception as e:
        set_case_status(case_id, STATUS_FAILED)
        append_log(case_id, f"FATAL: Failed to start retry pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "retrying": len(failed)}


@router.post("/case/{case_id}/upload")
async def upload_more_documents(case_id: str, files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    # Get case details to determine next doc index
    meta = get_case_job(case_id)
    existing_files = meta.get("files", [])
    start_idx = len(existing_files)

    case_dir = get_case_dir(case_id)

    saved = []
    for i, f in enumerate(files):
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail=f"{f.filename} is not a PDF")
        dest = await save_upload(f, case_dir / "raw")
        doc_id = f"DOC_{str(start_idx + i + 1).zfill(3)}"
        saved.append({
            "doc_id":        doc_id,
            "original_name": f.filename,
            "saved_path":    str(dest),
            "size_kb":       round(dest.stat().st_size / 1024, 1),
        })

    # Update total count in database
    new_total = start_idx + len(saved)

    try:
        from backend.services.mysql_store import _get_conn
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE cases SET total_docs = %s, status = 'uploaded', "
                "verification_status = NULL, verdict = NULL WHERE id = %s",
                (new_total, case_id)
            )
            # Delete stale cross-document verification report
            cursor.execute("DELETE FROM cross_doc_verifications WHERE case_id = %s", (case_id,))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to update cases total_docs: %s", e)

    # Initialize new documents in database
    try:
        for s in saved:
            init_document(
                case_id=case_id,
                doc_id=s["doc_id"],
                doc_index=int(s["doc_id"].split("_")[1]),
                filename=s["original_name"],
                file_paths={"raw": s["saved_path"]},
            )
    except Exception as e:
        logger.warning("Failed to init documents in MySQL: %s", e)

    # Sync to Redis cache
    add_files_to_case(case_id, saved)
    append_log(case_id, f"Uploaded {len(saved)} additional file(s) — total docs is now {new_total}")

    return {"case_id": case_id, "files": saved, "total_docs": new_total}


@router.post("/clear")
async def clear_all_data():
    """Flush Redis, stop active Celery tasks, and purge Celery queue."""
    # 1. Stop active Celery tasks
    revoked_count = 0
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            for worker, tasks in active.items():
                for task in tasks:
                    task_id = task.get("id")
                    if task_id:
                        celery_app.control.revoke(task_id, terminate=True)
                        revoked_count += 1
    except Exception as e:
        logger.warning("Failed to revoke active Celery tasks: %s", e)

    # 2. Flush Redis
    redis_deleted = flush_all_cases()

    # 3. Purge Celery Queue
    try:
        purged = celery_app.control.purge()
    except Exception as e:
        logger.warning("Failed to purge Celery queue: %s", e)
        purged = 0

    return {
        "redis_keys_deleted": redis_deleted,
        "celery_tasks_purged": purged,
        "celery_tasks_revoked": revoked_count,
        "message": "Redis state cleared and active/pending Celery tasks revoked successfully.",
    }
