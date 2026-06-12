"""
Pipeline Router
POST /api/upload   — accept PDF files for a case
POST /api/process  — run full OCR + structuring pipeline
GET  /api/status/{case_id} — poll job status
"""

import os
import uuid
import json
import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from backend.services.preprocessor   import preprocess_pdf
from backend.services.sarvam_ocr     import run_sarvam_ocr
from backend.services.ocr_merger     import merge_chunked_outputs
from backend.services.gemini_structurer import structure_document_with_gemini
from backend.services.doc_classifier import classify_document
from backend.services.ec_parser import EC_DOC_TYPE, normalize_ec_document, with_document_type_name
from backend.services.mysql_store import store_structured_result
from backend.utils.file_utils        import (
    get_case_dir, save_upload, cleanup_temp, write_json, read_json
)

router = APIRouter()

# ── In-memory job store (replace with Redis/DB for production) ─────────────────
JOBS: dict = {}   # case_id → job state dict


# ── 1. Upload endpoint ─────────────────────────────────────────────────────────
@router.post("/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """Accept multiple PDF uploads, assign a case_id, return it."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    case_id = str(uuid.uuid4())[:8].upper()
    case_dir = get_case_dir(case_id)

    saved = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400,
                                detail=f"{f.filename} is not a PDF")
        dest = await save_upload(f, case_dir / "raw")
        saved.append({
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

    return {"case_id": case_id, "files": saved}


# ── 2. Process endpoint ────────────────────────────────────────────────────────
@router.post("/process/{case_id}")
async def process_case(case_id: str, background_tasks: BackgroundTasks):
    """Kick off the pipeline for an uploaded case (runs in background)."""
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


# ── 4. Result endpoint ─────────────────────────────────────────────────────────
@router.get("/result/{case_id}/{doc_id}")
async def get_result(case_id: str, doc_id: str):
    case_dir = get_case_dir(case_id)
    result_file = case_dir / "structured" / f"{doc_id}.json"
    if not result_file.exists():
        matches = sorted((case_dir / "structured").glob(f"{doc_id}_*.json"))
        result_file = matches[0] if matches else result_file
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Result not ready")
    return read_json(result_file)


# ── Background pipeline ────────────────────────────────────────────────────────
DEFAULT_DOC_WORKERS = 2


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


async def _structure_document_for_type(merged: dict, doc_type: str, filename: str) -> dict:
    if doc_type == EC_DOC_TYPE:
        return await asyncio.to_thread(normalize_ec_document, merged, filename)
    structured = await asyncio.to_thread(structure_document_with_gemini, merged, doc_type)
    return with_document_type_name(structured, doc_type)


async def _save_to_mysql(
    *,
    case_id: str,
    doc_id: str,
    filename: str,
    doc_type: str,
    structured: dict,
    result_path: Path,
) -> tuple[bool, str | None]:
    try:
        await asyncio.to_thread(
            store_structured_result,
            case_id=case_id,
            doc_id=doc_id,
            filename=filename,
            document_type=doc_type,
            structured=structured,
            result_path=result_path,
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


async def _run_pipeline_serial(case_id: str):
    job  = JOBS[case_id]
    files = job["files"]
    total = len(files)

    def log(msg: str):
        job["log"].append(msg)
        safe_msg = f"[{case_id}] {msg}".encode("ascii", "backslashreplace").decode("ascii")
        print(safe_msg)

    try:
        case_dir = get_case_dir(case_id)
        (case_dir / "structured").mkdir(exist_ok=True)
        (case_dir / "ocr_raw").mkdir(exist_ok=True)
        (case_dir / "preprocessed").mkdir(exist_ok=True)

        for i, file_info in enumerate(files):
            pdf_path  = Path(file_info["saved_path"])
            doc_id    = f"DOC_{str(i+1).zfill(3)}"
            doc_name  = pdf_path.stem

            job["progress"] = int((i / total) * 90)
            log(f"── [{doc_id}] {pdf_path.name} ──────────────────")

            # ── STEP 1: Preprocess ─────────────────────────────────────────
            log(f"[{doc_id}] Step 1: Preprocessing (contrast/denoise/deskew)")
            try:
                preprocessed_pdf = await asyncio.to_thread(
                    preprocess_pdf, pdf_path,
                    case_dir / "preprocessed" / f"{doc_id}_prep.pdf"
                )
                log(f"[{doc_id}] ✓ Preprocessing complete → {preprocessed_pdf.name}")
            except Exception as e:
                log(f"[{doc_id}] ⚠ Preprocessing failed ({e}), using original")
                preprocessed_pdf = pdf_path

            # ── STEP 2: Sarvam OCR (with chunking) ────────────────────────
            log(f"[{doc_id}] Step 2: Running Sarvam OCR")
            try:
                ocr_results = await asyncio.to_thread(
                    run_sarvam_ocr,
                    preprocessed_pdf,
                    case_dir / "ocr_raw" / doc_id
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
                    raise RuntimeError(
                        f"All Sarvam OCR chunks failed. {chunk_errors}"
                    )

                for c in failed_chunks:
                    log(f"[{doc_id}] ⚠ OCR chunk {c.chunk_index} failed: {c.error}")
            except Exception as e:
                log(f"[{doc_id}] ✗ OCR failed: {e}")
                job["errors"].append({"doc_id": doc_id, "step": "ocr", "error": str(e)})
                continue

            # ── STEP 3: Merge chunked outputs ──────────────────────────────
            log(f"[{doc_id}] Step 3: Merging OCR chunks")
            try:
                merged = await asyncio.to_thread(
                    merge_chunked_outputs, ocr_results
                )
                # Save raw merged OCR
                write_json(case_dir / "ocr_raw" / f"{doc_id}_merged.json", merged)
                log(f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, "
                    f"{len(merged['full_text'])} chars")
            except Exception as e:
                log(f"[{doc_id}] ✗ Merge failed: {e}")
                job["errors"].append({"doc_id": doc_id, "step": "merge", "error": str(e)})
                continue

            # ── STEP 4: Classify document ──────────────────────────────────
            doc_type = classify_document(pdf_path.name, merged["full_text"][:500])
            log(f"[{doc_id}] Step 4: Classified → {doc_type}")

            # ── STEP 5: Structure document ────────────────────────────────
            if doc_type == EC_DOC_TYPE:
                log(f"[{doc_id}] Step 5: Parsing EC table deterministically")
            else:
                log(f"[{doc_id}] Step 5: Structuring with Gemini LLM")
            try:
                structured = await _structure_document_for_type(
                    merged, doc_type, pdf_path.name
                )
                out_path = _structured_output_path(case_dir, doc_id, doc_type)
                write_json(out_path, structured)
                log(f"[{doc_id}] ✓ Structured → {out_path.name}")

                mysql_saved, mysql_error = await _save_to_mysql(
                    case_id=case_id,
                    doc_id=doc_id,
                    filename=pdf_path.name,
                    doc_type=doc_type,
                    structured=structured,
                    result_path=out_path,
                )
                if mysql_saved:
                    log(f"[{doc_id}] ✓ Saved to MySQL document_results")
                else:
                    log(f"[{doc_id}] ⚠ MySQL save failed: {mysql_error}")

                job["results"].append({
                    "doc_id":       doc_id,
                    "filename":     pdf_path.name,
                    "doc_type":     doc_type,
                    "status":       "complete",
                    "structured":   structured,
                    "result_file":  out_path.name,
                    "mysql_saved":  mysql_saved,
                    "mysql_error":  mysql_error,
                    "total_pages":  merged["total_pages"],
                    "chunks_used":  len(ocr_results),
                })
            except Exception as e:
                log(f"[{doc_id}] ✗ Structuring failed: {e}")
                job["errors"].append({"doc_id": doc_id, "step": "structure", "error": str(e)})

        job["progress"] = 100
        job["status"]   = "complete" if not job["errors"] else "partial"
        log(f"── Pipeline done: {len(job['results'])} complete, "
            f"{len(job['errors'])} failed ──")

    except Exception as e:
        job["status"] = "failed"
        error = str(e)
        job["log"].append(f"FATAL: {error}")
        job["errors"].append({"doc_id": "CASE", "step": "pipeline", "error": error})


async def _run_pipeline(case_id: str):
    job = JOBS[case_id]
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
            job["progress"] = int((completed_docs / total) * 90)

    async def process_document(case_dir: Path, i: int, file_info: dict):
        pdf_path = Path(file_info["saved_path"])
        doc_id = f"DOC_{str(i + 1).zfill(3)}"

        try:
            log(f"── [{doc_id}] {pdf_path.name} ─────────────────")

            log(f"[{doc_id}] Step 1: Preprocessing (contrast/denoise/deskew)")
            try:
                preprocessed_pdf = await asyncio.to_thread(
                    preprocess_pdf,
                    pdf_path,
                    case_dir / "preprocessed" / f"{doc_id}_prep.pdf",
                )
                log(f"[{doc_id}] ✓ Preprocessing complete → {preprocessed_pdf.name}")
            except Exception as e:
                log(f"[{doc_id}] ⚠ Preprocessing failed ({e}), using original")
                preprocessed_pdf = pdf_path

            log(f"[{doc_id}] Step 2: Running Sarvam OCR")
            try:
                ocr_results = await asyncio.to_thread(
                    run_sarvam_ocr,
                    preprocessed_pdf,
                    case_dir / "ocr_raw" / doc_id,
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
                    raise RuntimeError(
                        f"All Sarvam OCR chunks failed. {chunk_errors}"
                    )

                for c in failed_chunks:
                    log(f"[{doc_id}] ⚠ OCR chunk {c.chunk_index} failed: {c.error}")
            except Exception as e:
                log(f"[{doc_id}] ✗ OCR failed: {e}")
                job["errors"].append({"doc_id": doc_id, "step": "ocr", "error": str(e)})
                return

            log(f"[{doc_id}] Step 3: Merging OCR chunks")
            try:
                merged = await asyncio.to_thread(merge_chunked_outputs, ocr_results)
                write_json(case_dir / "ocr_raw" / f"{doc_id}_merged.json", merged)
                log(
                    f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, "
                    f"{len(merged['full_text'])} chars"
                )
            except Exception as e:
                log(f"[{doc_id}] ✗ Merge failed: {e}")
                job["errors"].append({"doc_id": doc_id, "step": "merge", "error": str(e)})
                return

            doc_type = classify_document(pdf_path.name, merged["full_text"][:500])
            log(f"[{doc_id}] Step 4: Classified → {doc_type}")

            if doc_type == EC_DOC_TYPE:
                log(f"[{doc_id}] Step 5: Parsing EC table deterministically")
            else:
                log(f"[{doc_id}] Step 5: Structuring with Gemini LLM")
            try:
                structured = await _structure_document_for_type(
                    merged,
                    doc_type,
                    pdf_path.name,
                )
                out_path = _structured_output_path(case_dir, doc_id, doc_type)
                write_json(out_path, structured)
                log(f"[{doc_id}] ✓ Structured → {out_path.name}")

                mysql_saved, mysql_error = await _save_to_mysql(
                    case_id=case_id,
                    doc_id=doc_id,
                    filename=pdf_path.name,
                    doc_type=doc_type,
                    structured=structured,
                    result_path=out_path,
                )
                if mysql_saved:
                    log(f"[{doc_id}] ✓ Saved to MySQL document_results")
                else:
                    log(f"[{doc_id}] ⚠ MySQL save failed: {mysql_error}")

                job["results"].append({
                    "doc_id": doc_id,
                    "filename": pdf_path.name,
                    "doc_type": doc_type,
                    "status": "complete",
                    "structured": structured,
                    "result_file": out_path.name,
                    "mysql_saved": mysql_saved,
                    "mysql_error": mysql_error,
                    "total_pages": merged["total_pages"],
                    "chunks_used": len(ocr_results),
                })
            except Exception as e:
                log(f"[{doc_id}] ✗ Structuring failed: {e}")
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
        log(
            f"── Pipeline done: {len(job['results'])} complete, "
            f"{len(job['errors'])} failed ──"
        )

    except Exception as e:
        job["status"] = "failed"
        error = str(e)
        job["log"].append(f"FATAL: {error}")
        job["errors"].append({"doc_id": "CASE", "step": "pipeline", "error": error})
