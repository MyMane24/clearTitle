"""
Case-level endpoints: upload, process, retry, status
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.services.mysql_store import (
    init_case,
    init_document,
    update_document_status,
    get_failed_documents,
    get_classification_failed_documents,
)
from backend.utils.file_utils import get_case_dir, save_upload
from backend.services.redis_store import (
    case_exists as redis_case_exists,
    init_case as redis_init_case,
    get_case_job,
    append_log,
    set_case_status,
    reset_for_retry,
    flush_all_cases,
)
from backend.celery_app import celery_app
from backend.services.pipeline_orchestrator import (
    start_case_pipeline,
    start_retry_pipeline,
)

router = APIRouter()


@router.post("/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
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
    if meta["status"] == "processing":
        raise HTTPException(status_code=409, detail="Already processing")

    set_case_status(case_id, "processing")
    append_log(case_id, "Starting Celery pipeline")

    try:
        start_case_pipeline(case_id)
    except Exception as e:
        set_case_status(case_id, "failed")
        append_log(case_id, f"FATAL: Failed to start pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "status": "processing", "mode": "celery"}


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
        except Exception:
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
    if meta["status"] == "processing":
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
        update_document_status(
            case_id=case_id,
            doc_id=doc["doc_id"],
            status="pending_retry",
        )

    reset_for_retry(case_id)
    append_log(case_id, f"Retrying {len(failed)} failed document(s)")

    try:
        start_retry_pipeline(case_id)
    except Exception as e:
        set_case_status(case_id, "failed")
        append_log(case_id, f"FATAL: Failed to start retry pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "retrying": len(failed)}


@router.post("/clear")
async def clear_all_data():
    """Flush Redis case keys and purge Celery queue for a fresh start."""
    redis_deleted = flush_all_cases()
    try:
        purged = celery_app.control.purge()
    except Exception:
        purged = 0
    return {
        "redis_keys_deleted": redis_deleted,
        "celery_tasks_purged": purged,
        "message": "All data cleared. You can now upload fresh documents.",
    }
