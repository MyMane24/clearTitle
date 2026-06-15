"""
Pipeline Router
POST /api/upload          — accept PDF files for a case
POST /api/process/{case_id} — run full OCR + structuring pipeline
GET  /api/status/{case_id}  — poll job status
POST /api/retry/{case_id}   — retry failed documents only
GET  /api/case/{case_id}/bundle — all structured JSONs for verification
"""

import os
import uuid
import json
import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks

from backend.services.preprocessor   import preprocess_pdf
from backend.services.sarvam_ocr     import run_sarvam_ocr
from backend.services.ocr_merger     import merge_chunked_outputs
from backend.services.gemini_structurer import structure_document_with_gemini
from backend.services.doc_classifier import classify_document
from backend.services.ec_parser import EC_DOC_TYPE, normalize_ec_document, with_document_type_name
from backend.services.property_tax_assessment_parser import (
    PROPERTY_TAX_ASSESSMENT_DOC_TYPE,
    normalize_property_tax_assessment,
)
from backend.services.mysql_store import (
    init_case,
    init_document,
    update_document_status,
    get_case_documents,
    get_case_bundle,
    get_failed_documents,
    update_case_status,
    increment_retry,
)
from backend.utils.file_utils        import (
    get_case_dir, save_upload, cleanup_temp, write_json, read_json
)

router = APIRouter()

# ── In-memory job store (for progress polling) ─────────────────────────────────
JOBS: dict = {}

# ── Config ──────────────────────────────────────────────────────────────────────
DEFAULT_DOC_WORKERS = 5
OCR_MAX_RETRIES = 3
OCR_RETRY_DELAY_SEC = 5


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

    JOBS[case_id] = {
        "case_id":   case_id,
        "status":    "uploaded",
        "files":     saved,
        "results":   [],
        "errors":    [],
        "progress":  0,
        "log":       [f"Case {case_id} created — {len(saved)} file(s) uploaded"],
    }

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
        JOBS[case_id]["log"].append(f"⚠ DB init failed (non-fatal): {e}")

    return {"case_id": case_id, "files": saved}


# ── 2. Process endpoint ────────────────────────────────────────────────────────
@router.post("/process/{case_id}")
async def process_case(case_id: str, background_tasks: BackgroundTasks):
    if case_id not in JOBS:
        raise HTTPException(status_code=404, detail="Case not found")
    if JOBS[case_id]["status"] == "processing":
        raise HTTPException(status_code=409, detail="Already processing")

    JOBS[case_id]["status"] = "processing"
    background_tasks.add_task(_run_pipeline, case_id)
    return {"case_id": case_id, "status": "processing"}


# ── 3. Status / poll endpoint ──────────────────────────────────────────────────
@router.get("/status/{case_id}")
async def get_status(case_id: str):
    if case_id not in JOBS:
        raise HTTPException(status_code=404, detail="Case not found")
    return JOBS[case_id]


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
async def retry_failed(case_id: str, background_tasks: BackgroundTasks):
    if case_id not in JOBS:
        raise HTTPException(status_code=404, detail="Case not found")
    if JOBS[case_id]["status"] == "processing":
        raise HTTPException(status_code=409, detail="Already processing")

    failed = get_failed_documents(case_id)
    if not failed:
        raise HTTPException(status_code=400, detail="No failed documents to retry")

    JOBS[case_id]["status"] = "processing"
    JOBS[case_id]["log"].append(f"Retrying {len(failed)} failed document(s)")

    # Reset failed doc statuses
    for doc in failed:
        update_document_status(
            case_id=case_id,
            doc_id=doc["doc_id"],
            status="pending_retry",
        )

    background_tasks.add_task(_run_pipeline, case_id, retry_only=True)
    return {"case_id": case_id, "retrying": len(failed)}


# ── Background pipeline ────────────────────────────────────────────────────────

def _get_doc_workers(total_docs: int) -> int:
    try:
        configured = int(os.getenv("PIPELINE_DOC_WORKERS", DEFAULT_DOC_WORKERS))
    except ValueError:
        configured = DEFAULT_DOC_WORKERS
    return max(1, min(configured, total_docs))


def _safe_doc_type(doc_type: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())


def _structured_output_path(case_dir: Path, doc_id: str, doc_type: str) -> Path:
    return case_dir / "structured" / f"{doc_id}_{_safe_doc_type(doc_type)}.json"


# ── Retry wrapper for Sarvam OCR ────────────────────────────────────────────────
def _run_ocr_with_retry(pdf_path: Path, output_dir: Path, max_retries: int = OCR_MAX_RETRIES):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return run_sarvam_ocr(pdf_path, output_dir)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(OCR_RETRY_DELAY_SEC * attempt)
    raise last_error


# ── Structure helper ────────────────────────────────────────────────────────────
async def _structure_document_for_type(merged: dict, doc_type: str, filename: str) -> dict:
    if doc_type == EC_DOC_TYPE:
        return await asyncio.to_thread(normalize_ec_document, merged, filename)
    if doc_type == PROPERTY_TAX_ASSESSMENT_DOC_TYPE:
        return await asyncio.to_thread(normalize_property_tax_assessment, merged, filename)
    structured = await asyncio.to_thread(structure_document_with_gemini, merged, doc_type)
    return with_document_type_name(structured, doc_type)


# ── Main pipeline ───────────────────────────────────────────────────────────────
async def _run_pipeline(case_id: str, retry_only: bool = False):
    job = JOBS[case_id]

    if retry_only:
        files = [_f for _f in job["files"] if _f["doc_id"] in
                 {d["doc_id"] for d in get_failed_documents(case_id)}]
    else:
        files = job["files"]

    total = len(files)
    completed_docs = 0
    progress_lock = asyncio.Lock()

    def log(msg: str):
        job["log"].append(msg)
        safe_msg = f"[{case_id}] {msg}".encode("ascii", "backslashreplace").decode("ascii")
        print(safe_msg)

    async def mark_doc_done():
        nonlocal completed_docs
        async with progress_lock:
            completed_docs += 1
            if retry_only:
                job["progress"] = min(100, int((completed_docs / total) * 100))
            else:
                job["progress"] = int((completed_docs / total) * 90)

    async def process_document(case_dir: Path, i: int, file_info: dict):
        pdf_path = Path(file_info["saved_path"])
        doc_id = file_info["doc_id"]

        try:
            log(f"── [{doc_id}] {pdf_path.name} ─────────────────")

            update_document_status(case_id=case_id, doc_id=doc_id, status="preprocessing")
            log(f"[{doc_id}] Step 1: Preprocessing (contrast/denoise/deskew)")
            try:
                preprocessed_pdf = await asyncio.to_thread(
                    preprocess_pdf,
                    pdf_path,
                    case_dir / "preprocessed" / f"{doc_id}_prep.pdf",
                )
                log(f"[{doc_id}] ✓ Preprocessing complete → {preprocessed_pdf.name}")
                update_document_status(
                    case_id=case_id, doc_id=doc_id, status="preprocessed",
                    file_paths={"preprocessed": str(preprocessed_pdf)},
                )
            except Exception as e:
                log(f"[{doc_id}] ⚠ Preprocessing failed ({e}), using original")
                preprocessed_pdf = pdf_path

            log(f"[{doc_id}] Step 2: Running Sarvam OCR")
            update_document_status(case_id=case_id, doc_id=doc_id, status="ocr_in_progress")
            try:
                ocr_results = await asyncio.to_thread(
                    _run_ocr_with_retry, preprocessed_pdf, case_dir / "ocr_raw" / doc_id
                )
                write_json(
                    case_dir / "ocr_raw" / f"{doc_id}_chunks.json",
                    {"chunks": [asdict(chunk) for chunk in ocr_results]},
                )

                complete_chunks = [c for c in ocr_results if c.status == "complete"]
                failed_chunks = [c for c in ocr_results if c.status != "complete"]
                log(
                    f"[{doc_id}] ✓ OCR done — {len(complete_chunks)}/"
                    f"{len(ocr_results)} chunk(s) complete"
                )

                if not complete_chunks:
                    chunk_errors = "; ".join(
                        f"chunk {c.chunk_index}: {c.error or c.status}"
                        for c in failed_chunks
                    )
                    raise RuntimeError(f"All Sarvam OCR chunks failed. {chunk_errors}")

                for c in failed_chunks:
                    log(f"[{doc_id}] ⚠ OCR chunk {c.chunk_index} failed: {c.error}")

                update_document_status(
                    case_id=case_id, doc_id=doc_id, status="ocr_done",
                    file_paths={"ocr_chunks": str(case_dir / "ocr_raw" / doc_id)},
                )
            except Exception as e:
                log(f"[{doc_id}] ✗ OCR failed: {e}")
                increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
                job["errors"].append({"doc_id": doc_id, "step": "ocr", "error": str(e)})
                return

            log(f"[{doc_id}] Step 3: Merging OCR chunks")
            update_document_status(case_id=case_id, doc_id=doc_id, status="merging")
            try:
                merged = await asyncio.to_thread(merge_chunked_outputs, ocr_results)
                write_json(case_dir / "ocr_raw" / f"{doc_id}_merged.json", merged)
                log(
                    f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, "
                    f"{len(merged['full_text'])} chars"
                )
                update_document_status(
                    case_id=case_id, doc_id=doc_id, status="merged",
                    file_paths={"merged_ocr": str(case_dir / "ocr_raw" / f"{doc_id}_merged.json")},
                )
            except Exception as e:
                log(f"[{doc_id}] ✗ Merge failed: {e}")
                increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
                job["errors"].append({"doc_id": doc_id, "step": "merge", "error": str(e)})
                return

            doc_type = classify_document(pdf_path.name, merged["full_text"][:500])
            log(f"[{doc_id}] Step 4: Classified → {doc_type}")
            update_document_status(
                case_id=case_id, doc_id=doc_id, status="classifying",
                document_type=doc_type,
            )

            if doc_type == EC_DOC_TYPE:
                log(f"[{doc_id}] Step 5: Parsing EC table deterministically")
            elif doc_type == PROPERTY_TAX_ASSESSMENT_DOC_TYPE:
                log(f"[{doc_id}] Step 5: Parsing property tax assessment table deterministically")
            else:
                log(f"[{doc_id}] Step 5: Structuring with Gemini LLM")

            update_document_status(case_id=case_id, doc_id=doc_id, status="structuring")
            try:
                structured = await _structure_document_for_type(
                    merged, doc_type, pdf_path.name,
                )
                out_path = _structured_output_path(case_dir, doc_id, doc_type)
                write_json(out_path, structured)
                log(f"[{doc_id}] ✓ Structured → {out_path.name}")

                update_document_status(
                    case_id=case_id, doc_id=doc_id, status="structured",
                    structured=structured,
                    file_paths={"structured": str(out_path)},
                )
                log(f"[{doc_id}] ✓ Saved to DB case_documents")

                job["results"].append({
                    "doc_id":       doc_id,
                    "filename":     pdf_path.name,
                    "doc_type":     doc_type,
                    "status":       "complete",
                    "structured":   structured,
                    "result_file":  out_path.name,
                    "total_pages":  merged["total_pages"],
                    "chunks_used":  len(ocr_results),
                })
            except Exception as e:
                log(f"[{doc_id}] ✗ Structuring failed: {e}")
                increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
                job["errors"].append({"doc_id": doc_id, "step": "structure", "error": str(e)})
        finally:
            await mark_doc_done()

    async def worker(case_dir: Path, item: tuple[int, dict]):
        async with semaphore:
            await process_document(case_dir, *item)

    try:
        case_dir = get_case_dir(case_id)
        (case_dir / "structured").mkdir(exist_ok=True)
        (case_dir / "ocr_raw").mkdir(exist_ok=True)
        (case_dir / "preprocessed").mkdir(exist_ok=True)

        doc_workers = _get_doc_workers(total)
        semaphore = asyncio.Semaphore(doc_workers)
        log(f"Processing {total} document(s) with {doc_workers} parallel worker(s)")

        await asyncio.gather(
            *(worker(case_dir, item) for item in enumerate(files))
        )

        job["results"].sort(key=lambda r: r["doc_id"])
        job["errors"].sort(key=lambda e: e["doc_id"])
        job["progress"] = 100
        job["status"] = "complete" if not job["errors"] else "partial"

        # Update DB case status
        try:
            update_case_status(case_id=case_id)
        except Exception as e:
            log(f"⚠ Case status DB update failed: {e}")

        log(
            f"── Pipeline done: {len(job['results'])} complete, "
            f"{len(job['errors'])} failed ──"
        )

    except Exception as e:
        job["status"] = "failed"
        error = str(e)
        job["log"].append(f"FATAL: {error}")
        job["errors"].append({"doc_id": "CASE", "step": "pipeline", "error": error})


# ── Keep legacy alias for backward compat if any external caller references it ──
_run_pipeline_serial = _run_pipeline
