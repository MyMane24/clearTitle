"""
Pipeline Router
POST /api/upload          — accept PDF files for a case
POST /api/process/{case_id} — enqueue Celery chord for all docs
GET  /api/status/{case_id}  — poll job status (reads from Redis)
POST /api/retry/{case_id}   — enqueue Celery chord for failed docs only
GET  /api/case/{case_id}/bundle — all structured JSONs for verification
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.services.mysql_store import (
    init_case,
    init_document,
    update_document_status,
    get_case_documents,
    get_case_bundle,
    get_failed_documents,
    get_classification_failed_documents,
    update_case_status,
    replace_document as db_replace_document,
    skip_document as db_skip_document,
)
from backend.utils.file_utils import get_case_dir, save_upload, read_json
from backend.services.redis_store import (
    case_exists as redis_case_exists,
    init_case as redis_init_case,
    get_case_job,
    update_file_in_case,
    remove_error_for_doc,
    append_log,
    set_case_status,
    reset_for_retry,
)
from backend.tasks.pipeline_tasks import start_case_pipeline, start_retry_pipeline

router = APIRouter()


# ── 1. Upload endpoint ─────────────────────────────────────────────────────────
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

    # Init Redis state
    redis_init_case(case_id, saved)

    # Init DB
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


# ── 2. Process endpoint ────────────────────────────────────────────────────────
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


# ── 3. Status / poll endpoint ──────────────────────────────────────────────────
@router.get("/status/{case_id}")
async def get_status(case_id: str):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    job = get_case_job(case_id)

    # Add a dedicated needs_action field for classification_failed docs
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


# ── 4. Result endpoint (single doc) ────────────────────────────────────────────
@router.get("/result/{case_id}/{doc_id}")
async def get_result(case_id: str, doc_id: str):
    case_dir = get_case_dir(case_id)
    matches = sorted((case_dir / "structured").glob(f"{doc_id}_*.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="Result not ready")
    return read_json(matches[0])


# ── 5. Case bundle endpoint (all JSONs for verification) ───────────────────────
@router.get("/case/{case_id}/bundle")
async def get_case_bundle_endpoint(case_id: str):
    docs = get_case_bundle(case_id)
    if not docs:
        raise HTTPException(status_code=404, detail="No structured results found")
    return {
        "case_id": case_id,
        "total_docs": len(docs),
        "documents": docs,
    }


# ── 6. Retry endpoint ──────────────────────────────────────────────────────────
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

    # Reset failed doc statuses in DB
    for doc in failed:
        update_document_status(
            case_id=case_id,
            doc_id=doc["doc_id"],
            status="pending_retry",
        )

    # Reset Redis state for retry
    reset_for_retry(case_id)
    append_log(case_id, f"Retrying {len(failed)} failed document(s)")

    try:
        start_retry_pipeline(case_id)
    except Exception as e:
        set_case_status(case_id, "failed")
        append_log(case_id, f"FATAL: Failed to start retry pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "retrying": len(failed)}


# ── 7. Replace document endpoint ───────────────────────────────────────────────
@router.post("/case/{case_id}/doc/{doc_id}/replace")
async def replace_doc(case_id: str, doc_id: str, file: UploadFile = File(...)):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Replacement must be a PDF")

    docs = get_case_documents(case_id)
    if not any(d["doc_id"] == doc_id for d in docs):
        raise HTTPException(status_code=404, detail="Document not found in this case")

    case_dir = get_case_dir(case_id)
    dest = await save_upload(file, case_dir / "raw", doc_id=doc_id)

    # Update Redis file info
    update_file_in_case(case_id, doc_id, str(dest), file.filename)

    # Update DB
    db_replace_document(
        case_id=case_id,
        doc_id=doc_id,
        filename=file.filename,
        file_paths={"raw": str(dest)},
    )

    # Clean up errors for this doc
    remove_error_for_doc(case_id, doc_id)

    append_log(case_id, f"[{doc_id}] Replaced with {file.filename} — ready for retry")

    return {
        "case_id": case_id,
        "doc_id": doc_id,
        "filename": file.filename,
        "message": "Document replaced. Call POST /api/retry/{case_id} to process it.",
    }


# ── 8. Skip document endpoint ────────────────────────────────────────────────
@router.post("/case/{case_id}/doc/{doc_id}/skip")
async def skip_doc(case_id: str, doc_id: str):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    docs = get_case_documents(case_id)
    doc = next((d for d in docs if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in this case")
    if doc["status"] != "classification_failed":
        raise HTTPException(
            status_code=400,
            detail=f"Document status is '{doc['status']}', not 'classification_failed'. "
                   "Only classification-failed documents can be skipped.",
        )

    db_skip_document(case_id=case_id, doc_id=doc_id)
    update_case_status(case_id=case_id)

    # Clean up Redis error for this doc
    remove_error_for_doc(case_id, doc_id)

    append_log(case_id, f"[{doc_id}] Skipped — removed from case")

    return {
        "case_id": case_id,
        "doc_id": doc_id,
        "message": "Document skipped. Case will proceed without it.",
    }
