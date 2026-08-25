"""
Case-level endpoints: upload, process, retry, status, replace/skip, delete.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.celery_app import celery_app
from backend.config import PIPELINE_LOCK_ENABLED
from backend.database.repositories.case_repo import (
    delete_case as db_delete_case,
)
from backend.database.repositories.case_repo import (
    get_case_owner,
    init_case,
    list_cases,
    set_case_owner,
)
from backend.database.repositories.document_repo import (
    get_classification_failed_documents,
    get_failed_documents,
    init_document,
    replace_document,
    skip_document,
    update_document_status,
)
from backend.integrations.redis.state_store import (
    add_files_to_case,
    append_log,
    get_case_job,
    reset_for_retry,
    set_case_status,
)
from backend.integrations.redis.state_store import (
    case_exists as redis_case_exists,
)
from backend.integrations.redis.state_store import (
    delete_case as redis_delete_case,
)
from backend.integrations.redis.state_store import (
    init_case as redis_init_case,
)
from backend.integrations.storage.file_utils import delete_case_dir, get_case_dir, save_upload
from backend.logger import get_logger
from backend.services.auth import get_current_user, get_optional_user
from backend.services.orchestrator import (
    start_case_pipeline,
    start_retry_pipeline,
)
from backend.shared.constants import (
    ENCUMBRANCE_CERTIFICATE,
    SALE_DEED,
    STATUS_FAILED,
    STATUS_PENDING_RETRY,
    STATUS_PROCESSING,
)

SLOT_EXPECTED_TYPE = {
    "sale_deed": SALE_DEED,
    "ec": ENCUMBRANCE_CERTIFICATE,
}

router = APIRouter()
logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)


def _require_owner(case_id: str, user: dict) -> None:
    """403 unless the case belongs to the authenticated user."""
    owner = get_case_owner(case_id)
    if owner and owner != user["id"]:
        raise HTTPException(status_code=403, detail="Not your case")


def _enforce_access(case_id: str, user: dict | None) -> None:
    """Anonymous cases (user_id NULL) are open to anyone with the case id;
    owned cases require the owner to be authenticated."""
    owner = get_case_owner(case_id)
    if owner and (user is None or owner != user["id"]):
        raise HTTPException(status_code=403, detail="Not your case")


@router.get("/cases")
async def get_all_cases(limit: int = 50, offset: int = 0, user: dict = Depends(get_current_user)):
    """List the authenticated user's historical cases."""
    import asyncio
    try:
        db_cases = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: list_cases(user_id=user["id"], limit=limit, offset=offset)
        )
        for case in db_cases:
            case["source"] = "v2"
    except Exception as e:
        logger.warning("Failed to list cases: %s", e)
        db_cases = []
    return {"cases": db_cases, "total": len(db_cases)}


@router.delete("/case/{case_id}")
async def delete_case(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Delete everything related to a case: Redis, MySQL, and files on disk."""
    _enforce_access(case_id, user)

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

    redis_deleted = 0
    try:
        redis_deleted = redis_delete_case(case_id)
    except Exception as e:
        logger.warning("Failed to delete Redis data for %s: %s", case_id, e)

    try:
        db_delete_case(case_id)
    except Exception as e:
        logger.warning("Failed to delete DB records for %s: %s", case_id, e)

    fs_deleted = delete_case_dir(case_id)

    return {
        "case_id": case_id,
        "redis_keys_deleted": redis_deleted,
        "filesystem_deleted": fs_deleted,
        "message": f"Case {case_id} and all associated data deleted successfully.",
    }


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    slots: list[str] = Form(default=[]),
    user: dict | None = Depends(get_optional_user),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    case_id = str(uuid.uuid4())[:8].upper()
    case_dir = get_case_dir(case_id)

    saved = []
    for i, f in enumerate(files):
        filename = f.filename or ""
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail=f"{f.filename or 'Uploaded file'} is not a PDF")
        dest = await save_upload(f, case_dir / "raw")
        doc_id = f"DOC_{str(i + 1).zfill(3)}"
        slot = slots[i] if i < len(slots) else ""
        saved.append({
            "doc_id":        doc_id,
            "original_name": filename,
            "saved_path":    str(dest),
            "size_kb":       round(dest.stat().st_size / 1024, 1),
            "slot":          slot,
        })

    redis_init_case(case_id, saved)

    try:
        init_case(case_id=case_id, total_docs=len(saved), user_id=user["id"] if user else None)
        for s in saved:
            init_document(
                case_id=case_id,
                doc_id=s["doc_id"],
                doc_index=int(s["doc_id"].split("_")[1]),
                filename=s["original_name"],
                file_paths={"raw": s["saved_path"]},
                expected_type=SLOT_EXPECTED_TYPE.get(s["slot"]),
            )
    except Exception as e:
        append_log(case_id, f"⚠ DB init failed (non-fatal): {e}")

    return {"case_id": case_id, "files": saved}


@router.post("/process/{case_id}")
async def process_case(case_id: str, user: dict | None = Depends(get_optional_user)):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    lock_enabled = PIPELINE_LOCK_ENABLED
    lock = None
    if lock_enabled:
        from backend.integrations.redis.lock import RedisLock
        lock = RedisLock(f"case:{case_id}:pipeline_lock")
        if not lock.acquire():
            raise HTTPException(status_code=409, detail={"error": "Pipeline already running"})

    meta = get_case_job(case_id)
    if meta["status"] == STATUS_PROCESSING:
        if lock:
            lock.release()
        raise HTTPException(status_code=409, detail="Already processing")

    set_case_status(case_id, STATUS_PROCESSING)
    append_log(case_id, "Starting Celery pipeline")

    try:
        start_case_pipeline(case_id)
    except Exception as e:
        if lock:
            lock.release()
        set_case_status(case_id, STATUS_FAILED)
        append_log(case_id, f"FATAL: Failed to start pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "status": STATUS_PROCESSING, "mode": "celery"}


@router.get("/status/{case_id}")
async def get_status(case_id: str, user: dict | None = Depends(get_optional_user)):
    import asyncio
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    from backend.database.repositories.case_repo import get_case_status_payload
    try:
        job = await asyncio.get_event_loop().run_in_executor(
            _executor, get_case_status_payload, case_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    except Exception as e:
        logger.error("Failed to retrieve status from DB: %s", e)
        job = get_case_job(case_id)

    try:
        needs_action = get_classification_failed_documents(case_id)
    except Exception as e:
        logger.warning("Failed to get classification_failed docs: %s", e)
        needs_action = []

    job["needs_action"] = [
        {
            "doc_id": d["doc_id"],
            "filename": d["filename"],
            "message": f"'{d['filename']}' — document type not recognised.",
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
async def retry_failed(case_id: str, user: dict | None = Depends(get_optional_user)):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    lock_enabled = PIPELINE_LOCK_ENABLED
    lock = None
    if lock_enabled:
        from backend.integrations.redis.lock import RedisLock
        lock = RedisLock(f"case:{case_id}:pipeline_lock")
        if not lock.acquire():
            raise HTTPException(status_code=409, detail={"error": "Pipeline already running"})

    meta = get_case_job(case_id)
    if meta["status"] == STATUS_PROCESSING:
        from backend.database.repositories.document_repo import get_case_documents
        db_docs = get_case_documents(case_id)
        actively_processing = any(
            d.get("status") in ("processing", "pending", "preprocessing", "ocr", "structuring")
            for d in db_docs
        )
        if actively_processing:
            if lock:
                lock.release()
            raise HTTPException(status_code=409, detail="Already processing")

    failed = get_failed_documents(case_id)
    classification_failed = get_classification_failed_documents(case_id)

    if not failed:
        if lock:
            lock.release()
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
        if lock:
            lock.release()
        set_case_status(case_id, STATUS_FAILED)
        append_log(case_id, f"FATAL: Failed to start retry pipeline — {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"case_id": case_id, "retrying": len(failed)}


@router.post("/case/{case_id}/link")
async def link_case(case_id: str, user: dict = Depends(get_current_user)):
    """Attach an anonymous case (user_id NULL) to the authenticated user."""
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    owner = get_case_owner(case_id)
    if owner:
        if owner == user["id"]:
            return {"case_id": case_id, "linked": True, "already": True}
        raise HTTPException(status_code=403, detail="Case is linked to another account")
    set_case_owner(case_id=case_id, user_id=user["id"])
    append_log(case_id, "── Case linked to account ──")
    return {"case_id": case_id, "linked": True, "already": False}


@router.post("/case/{case_id}/upload")
async def upload_more_documents(
    case_id: str,
    files: list[UploadFile] = File(...),
    user: dict | None = Depends(get_optional_user),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    meta = get_case_job(case_id)
    existing_files = meta.get("files", [])
    start_idx = len(existing_files)

    case_dir = get_case_dir(case_id)

    saved = []
    for i, f in enumerate(files):
        filename = f.filename or ""
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail=f"{f.filename or 'Uploaded file'} is not a PDF")
        dest = await save_upload(f, case_dir / "raw")
        doc_id = f"DOC_{str(start_idx + i + 1).zfill(3)}"
        saved.append({
            "doc_id":        doc_id,
            "original_name": filename,
            "saved_path":    str(dest),
            "size_kb":       round(dest.stat().st_size / 1024, 1),
        })

    new_total = start_idx + len(saved)

    try:
        from backend.database.repositories.case_repo import upload_docs_reset
        upload_docs_reset(case_id=case_id, new_total=new_total)
    except Exception as e:
        logger.warning("Failed to update cases total_docs: %s", e)

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

    add_files_to_case(case_id, saved)
    append_log(case_id, f"Uploaded {len(saved)} additional file(s) — total docs is now {new_total}")

    return {"case_id": case_id, "files": saved, "total_docs": new_total}


@router.post("/case/{case_id}/doc/{doc_id}/replace")
async def replace_document_endpoint(
    case_id: str,
    doc_id: str,
    file: UploadFile = File(...),
    user: dict | None = Depends(get_optional_user),
):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    filename = file.filename
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"{file.filename or 'Uploaded file'} is not a PDF")

    case_dir = get_case_dir(case_id)
    dest = await save_upload(file, case_dir / "raw", doc_id=doc_id)

    replace_document(
        case_id=case_id,
        doc_id=doc_id,
        filename=filename,
        file_paths={"raw": str(dest)},
    )
    append_log(case_id, f"[{doc_id}] Document replaced — pending retry")
    return {"case_id": case_id, "doc_id": doc_id, "status": "replaced"}


@router.post("/case/{case_id}/doc/{doc_id}/skip")
async def skip_document_endpoint(
    case_id: str,
    doc_id: str,
    user: dict | None = Depends(get_optional_user),
):
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_access(case_id, user)

    skip_document(case_id=case_id, doc_id=doc_id)
    append_log(case_id, f"[{doc_id}] Document skipped")
    return {"case_id": case_id, "doc_id": doc_id, "status": "skipped"}


@router.get("/case/{case_id}/doc/{doc_id}/pdf")
async def get_doc_pdf(case_id: str, doc_id: str, user: dict | None = Depends(get_optional_user)):
    """Serve the original uploaded PDF for a document."""
    _enforce_access(case_id, user)
    from backend.database.repositories.document_repo import get_case_documents
    docs = get_case_documents(case_id)
    doc = next((d for d in docs if d["doc_id"] == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    paths = doc.get("file_paths") or {}
    raw_path = paths.get("raw")
    if not raw_path:
        raise HTTPException(status_code=404, detail="PDF file not found")
    from pathlib import Path
    pdf = Path(raw_path)
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    return FileResponse(str(pdf), media_type="application/pdf", filename=doc.get("filename", f"{doc_id}.pdf"))
