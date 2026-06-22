"""
Document-level endpoints: replace, skip, result, bundle, ocr-raw, files
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.services.file_service import (
    get_case_ocr_raw,
    list_case_ocr_raw,
    list_case_outputs,
)
from backend.services.mysql_store import (
    get_case_bundle,
    get_case_documents,
    update_case_status,
)
from backend.services.mysql_store import (
    replace_document as db_replace_document,
)
from backend.services.mysql_store import (
    skip_document as db_skip_document,
)
from backend.services.redis_store import (
    append_log,
    remove_error_for_doc,
    update_file_in_case,
)
from backend.services.redis_store import (
    case_exists as redis_case_exists,
)
from backend.utils.file_utils import get_case_dir, read_json, save_upload

router = APIRouter()


@router.get("/result/{case_id}/{doc_id}")
async def get_result(case_id: str, doc_id: str):
    case_dir = get_case_dir(case_id)
    matches = sorted((case_dir / "structured").glob(f"{doc_id}_*.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="Result not ready")
    return read_json(matches[0])


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

    update_file_in_case(case_id, doc_id, str(dest), file.filename)

    db_replace_document(
        case_id=case_id,
        doc_id=doc_id,
        filename=file.filename,
        file_paths={"raw": str(dest)},
    )

    remove_error_for_doc(case_id, doc_id)

    append_log(case_id, f"[{doc_id}] Replaced with {file.filename} — ready for retry")

    return {
        "case_id": case_id,
        "doc_id": doc_id,
        "filename": file.filename,
        "message": "Document replaced. Call POST /api/retry/{case_id} to process it.",
    }


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

    remove_error_for_doc(case_id, doc_id)

    append_log(case_id, f"[{doc_id}] Skipped — removed from case")

    return {
        "case_id": case_id,
        "doc_id": doc_id,
        "message": "Document skipped. Case will proceed without it.",
    }


@router.get("/case/{case_id}/doc/{doc_id}/ocr-raw")
async def get_ocr_raw(case_id: str, doc_id: str):
    """Return the merged OCR full text for a document."""
    result = get_case_ocr_raw(case_id, doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail="OCR raw output not found")
    return result


@router.get("/case/{case_id}/ocr-raw")
async def list_ocr_raw(case_id: str):
    """List merged OCR files available for a case."""
    return {"case_id": case_id, "documents": list_case_ocr_raw(case_id)}


@router.get("/case/{case_id}/files")
async def get_case_files_endpoint(case_id: str):
    """List the output directory tree for a case."""
    entries = list_case_outputs(case_id)
    return {"case_id": case_id, "entries": entries}
