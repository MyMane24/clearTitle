"""
Celery tasks for the document processing pipeline.
Each document is processed by its own task, running in parallel across workers.
A chord callback finalizes the case once all documents are done.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from backend.celery_app import celery_app
from backend.constants import (
    STATUS_PROCESSING, STATUS_PREPROCESSING, STATUS_PREPROCESSED,
    STATUS_OCR_IN_PROGRESS, STATUS_OCR_DONE, STATUS_MERGING, STATUS_MERGED,
    STATUS_CLASSIFYING, STATUS_CLASSIFICATION_FAILED,
    STATUS_STRUCTURING, STATUS_STRUCTURED,
    STATUS_FAILED, STATUS_COMPLETE, STATUS_PARTIAL,
    STEP_PIPELINE, STEP_PREPROCESSING, STEP_OCR, STEP_MERGE,
    STEP_CLASSIFY, STEP_STRUCTURE, STEP_DONE,
    UNKNOWN_DOC,
)
from backend.logger import get_logger
from backend.services.preprocessor import preprocess_pdf
from backend.services.sarvam_ocr import run_sarvam_ocr
from backend.services.ocr_merger import merge_chunked_outputs
from backend.services.groq_structurer import structure_document as structure_document_with_groq
from backend.services.gemini_structurer import structure_document_with_gemini
from backend.services.doc_classifier import classify_document, VALID_DOC_TYPES
from backend.services.ec_parser import (
    EC_DOC_TYPE,
    normalize_ec_document,
    with_document_type_name,
)
from backend.services.property_tax_assessment_parser import (
    PROPERTY_TAX_ASSESSMENT_DOC_TYPE,
    normalize_property_tax_assessment,
)
from backend.services.mysql_store import (
    update_document_status,
    get_failed_documents,
    update_case_status as mysql_update_case_status,
    increment_retry,
)
from backend.services.redis_store import (
    get_doc_file_path, get_doc_filename,
    set_doc_status, add_result, add_error, increment_done_count,
    get_case_errors, set_case_status,
    remove_error_for_doc, get_case_log, append_log,
)
from backend.utils.file_utils import get_case_dir, write_json

logger = get_logger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────────

OCR_MAX_RETRIES = 3
OCR_RETRY_DELAY_SEC = 5
STRUCTURE_MAX_RETRIES = 3
STRUCTURE_RETRY_DELAY_SEC = 5
# ── Doc type helpers ──────────────────────────────────────────────────────────────

def _safe_doc_type(doc_type: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())


def _structured_output_path(case_dir: Path, doc_id: str, doc_type: str) -> Path:
    return case_dir / "structured" / f"{doc_id}_{_safe_doc_type(doc_type)}.json"


def _is_transient_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(x in msg for x in ["503", "429", "500", "unavailable", "rate limit", "too many requests"])


# ── OCR retry wrapper ─────────────────────────────────────────────────────────────

def _run_ocr_with_retry(pdf_path: Path, output_dir: Path) -> list:
    last_error = None
    for attempt in range(1, OCR_MAX_RETRIES + 1):
        try:
            return run_sarvam_ocr(pdf_path, output_dir)
        except Exception as e:
            last_error = e
            if attempt < OCR_MAX_RETRIES:
                time.sleep(OCR_RETRY_DELAY_SEC * attempt)
    raise last_error


# ── Gemini retry wrapper ──────────────────────────────────────────────────────────

def _run_structure_with_retry(merged: dict, doc_type: str) -> dict:
    # Try Groq first (cheaper, faster, often handles large text well)
    try:
        result = structure_document_with_groq(merged, doc_type)
        return with_document_type_name(result, doc_type)
    except Exception as e:
        pass  # fall through to Gemini

    # Fall back to Gemini with retries
    last_error = None
    for attempt in range(1, STRUCTURE_MAX_RETRIES + 1):
        try:
            result = structure_document_with_gemini(merged, doc_type)
            return with_document_type_name(result, doc_type)
        except Exception as e:
            last_error = e
            if _is_transient_error(e) and attempt < STRUCTURE_MAX_RETRIES:
                time.sleep(STRUCTURE_RETRY_DELAY_SEC * attempt)
            else:
                raise
    raise last_error


# ── Structure dispatcher ──────────────────────────────────────────────────────────

def _structure_document_for_type(merged: dict, doc_type: str, filename: str) -> dict:
    if doc_type == EC_DOC_TYPE:
        return normalize_ec_document(merged, filename)
    if doc_type == PROPERTY_TAX_ASSESSMENT_DOC_TYPE:
        return normalize_property_tax_assessment(merged, filename)
    structured = _run_structure_with_retry(merged, doc_type)
    return structured


# ── Celery logger helper ──────────────────────────────────────────────────────────

def _log(case_id: str, msg: str) -> None:
    append_log(case_id, msg)


# ── Individual document task ──────────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=0, ignore_result=False)
def process_document_task(self, case_id: str, doc_id: str) -> dict:
    """
    Process a single document end-to-end:
    preprocess → OCR → merge → classify → structure → save.
    Returns a result dict (never raises) for the chord callback.
    """
    filename = get_doc_filename(case_id, doc_id) or doc_id
    pdf_path_str = get_doc_file_path(case_id, doc_id)
    if not pdf_path_str:
        err_msg = f"No file path found for {doc_id}"
        _log(case_id, f"[{doc_id}] ✗ {err_msg}")
        add_error(case_id, {"doc_id": doc_id, "step": STEP_PIPELINE, "error": err_msg})
        set_doc_status(case_id, doc_id, status=STATUS_FAILED, step=STEP_PIPELINE, error=err_msg, doc_type="", filename=filename)
        increment_done_count(case_id)
        return {"doc_id": doc_id, "status": STATUS_FAILED, "step": STEP_PIPELINE, "error": err_msg, "filename": filename}

    pdf_path = Path(pdf_path_str)
    case_dir = get_case_dir(case_id)
    (case_dir / "structured").mkdir(exist_ok=True)
    (case_dir / "ocr_raw").mkdir(exist_ok=True)
    (case_dir / "preprocessed").mkdir(exist_ok=True)

    try:
        _log(case_id, f"── [{doc_id}] {pdf_path.name} ─────────────────")

        # ── Step 1: Preprocess ───────────────────────────────────────────────
        update_document_status(case_id=case_id, doc_id=doc_id,     status=STATUS_PREPROCESSING)
        _log(case_id, f"[{doc_id}] Step 1: Preprocessing (contrast/denoise/deskew)")
        set_doc_status(case_id, doc_id, status=STATUS_PROCESSING, step=STEP_PREPROCESSING, filename=filename)
        try:
            preprocessed_pdf = preprocess_pdf(pdf_path, case_dir / "preprocessed" / f"{doc_id}_prep.pdf")
            _log(case_id, f"[{doc_id}] ✓ Preprocessing complete → {preprocessed_pdf.name}")
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_PREPROCESSED,
                file_paths={"preprocessed": str(preprocessed_pdf)},
            )
        except Exception as e:
            _log(case_id, f"[{doc_id}] ⚠ Preprocessing failed ({e}), using original")
            preprocessed_pdf = pdf_path

        # ── Step 2: OCR ──────────────────────────────────────────────────────
        _log(case_id, f"[{doc_id}] Step 2: Running Sarvam OCR")
        update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_OCR_IN_PROGRESS)
        set_doc_status(case_id, doc_id, step="ocr")
        try:
            ocr_results = _run_ocr_with_retry(preprocessed_pdf, case_dir / "ocr_raw" / doc_id)
            write_json(
                case_dir / "ocr_raw" / f"{doc_id}_chunks.json",
                {"chunks": [asdict(chunk) for chunk in ocr_results]},
            )

            complete_chunks = [c for c in ocr_results if c.status == "complete"]
            failed_chunks = [c for c in ocr_results if c.status != "complete"]
            _log(
                case_id,
                f"[{doc_id}] ✓ OCR done — {len(complete_chunks)}/{len(ocr_results)} chunk(s) complete",
            )

            if not complete_chunks:
                chunk_errors = "; ".join(
                    f"chunk {c.chunk_index}: {c.error or c.status}"
                    for c in failed_chunks
                )
                raise RuntimeError(f"All Sarvam OCR chunks failed. {chunk_errors}")

            for c in failed_chunks:
                _log(case_id, f"[{doc_id}] ⚠ OCR chunk {c.chunk_index} failed: {c.error}")

            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_OCR_DONE,
                file_paths={"ocr_chunks": str(case_dir / "ocr_raw" / doc_id)},
            )
        except Exception as e:
            _log(case_id, f"[{doc_id}] ✗ OCR failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            add_error(case_id, {"doc_id": doc_id, "step": STEP_OCR, "error": str(e)})
            set_doc_status(case_id, doc_id, status=STATUS_FAILED, step=STEP_OCR, error=str(e))
            increment_done_count(case_id)
            return {"doc_id": doc_id, "status": STATUS_FAILED, "step": STEP_OCR, "error": str(e), "filename": filename}

        # ── Step 3: Merge OCR chunks ─────────────────────────────────────────
        _log(case_id, f"[{doc_id}] Step 3: Merging OCR chunks")
        update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_MERGING)
        set_doc_status(case_id, doc_id, step=STEP_MERGE)
        try:
            merged = merge_chunked_outputs(ocr_results)
            write_json(case_dir / "ocr_raw" / f"{doc_id}_merged.json", merged)
            _log(
                case_id,
                f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, {len(merged['full_text'])} chars",
            )
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_MERGED,
                file_paths={"merged_ocr": str(case_dir / "ocr_raw" / f"{doc_id}_merged.json")},
            )
        except Exception as e:
            _log(case_id, f"[{doc_id}] ✗ Merge failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            add_error(case_id, {"doc_id": doc_id, "step": STEP_MERGE, "error": str(e)})
            set_doc_status(case_id, doc_id, status=STATUS_FAILED, step=STEP_MERGE, error=str(e))
            increment_done_count(case_id)
            return {"doc_id": doc_id, "status": STATUS_FAILED, "step": STEP_MERGE, "error": str(e), "filename": filename}

        # ── Step 4: Classify ─────────────────────────────────────────────────
        doc_type = classify_document(pdf_path.name, merged["full_text"][:500])
        _log(case_id, f"[{doc_id}] Step 4: Classified → {doc_type}")

        if doc_type == UNKNOWN_DOC:
            _log(case_id, f"[{doc_id}] ✗ Unknown document type — needs user action")
            err_msg = (
                "Unrecognised document type. "
                f"Supported: {', '.join(sorted(VALID_DOC_TYPES))}. "
                "Upload a replacement via POST /api/case/{case_id}/doc/{doc_id}/replace, "
                "or skip via POST /api/case/{case_id}/doc/{doc_id}/skip"
            )
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_CLASSIFICATION_FAILED,
                document_type=doc_type,
                error=err_msg,
            )
            add_error(case_id, {
                "doc_id": doc_id, "step": STEP_CLASSIFY,
                "error": "Unrecognised document type. ",
                "action_required": "replace_or_skip",
            })
            set_doc_status(case_id, doc_id, status=STATUS_CLASSIFICATION_FAILED, step=STEP_CLASSIFY,
                           error=err_msg, doc_type=UNKNOWN_DOC)
            increment_done_count(case_id)
            return {"doc_id": doc_id, "status": STATUS_CLASSIFICATION_FAILED, "step": STEP_CLASSIFY,
                    "error": err_msg, "doc_type": UNKNOWN_DOC, "filename": filename, "action_required": "replace_or_skip"}

        update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_CLASSIFYING, document_type=doc_type)
        set_doc_status(case_id, doc_id, step=STEP_STRUCTURE, doc_type=doc_type)

        if doc_type == EC_DOC_TYPE:
            _log(case_id, f"[{doc_id}] Step 5: Parsing EC table deterministically")
        elif doc_type == PROPERTY_TAX_ASSESSMENT_DOC_TYPE:
            _log(case_id, f"[{doc_id}] Step 5: Parsing property tax assessment table deterministically")
        else:
            _log(case_id, f"[{doc_id}] Step 5: Structuring with Groq LLM")

        # ── Step 5: Structure ────────────────────────────────────────────────
        update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_STRUCTURING)
        try:
            structured = _structure_document_for_type(
                merged, doc_type, pdf_path.name,
            )
            out_path = _structured_output_path(case_dir, doc_id, doc_type)
            write_json(out_path, structured)
            _log(case_id, f"[{doc_id}] ✓ Structured → {out_path.name}")

            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_STRUCTURED,
                structured=structured,
                file_paths={"structured": str(out_path)},
            )
            _log(case_id, f"[{doc_id}] ✓ Saved to DB case_documents")

            result = {
                "doc_id": doc_id,
                "filename": pdf_path.name,
                "doc_type": doc_type,
                "status": STATUS_COMPLETE,
                "structured": structured,
                "result_file": out_path.name,
                "total_pages": merged["total_pages"],
                "chunks_used": len(ocr_results),
            }
            add_result(case_id, result)
            set_doc_status(case_id, doc_id, status=STATUS_COMPLETE, step=STEP_DONE, doc_type=doc_type)
            increment_done_count(case_id)
            return {"doc_id": doc_id, "status": STATUS_COMPLETE, "doc_type": doc_type, "filename": pdf_path.name}
        except Exception as e:
            _log(case_id, f"[{doc_id}] ✗ Structuring failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            add_error(case_id, {"doc_id": doc_id, "step": STEP_STRUCTURE, "error": str(e)})
            set_doc_status(case_id, doc_id, status=STATUS_FAILED, step=STEP_STRUCTURE, error=str(e), doc_type=doc_type)
            increment_done_count(case_id)
            return {"doc_id": doc_id, "status": STATUS_FAILED, "step": STEP_STRUCTURE, "error": str(e), "filename": pdf_path.name}

    except Exception as e:
        err_msg = f"Unexpected error in task: {e}"
        _log(case_id, f"[{doc_id}] ✗ {err_msg}")
        try:
            increment_retry(case_id=case_id, doc_id=doc_id, error=err_msg)
        except Exception as e:
            logger.warning("Failed to increment retry for %s/%s: %s", case_id, doc_id, e)
        add_error(case_id, {"doc_id": doc_id, "step": STEP_PIPELINE, "error": err_msg})
        set_doc_status(case_id, doc_id, status=STATUS_FAILED, step=STEP_PIPELINE, error=err_msg)
        increment_done_count(case_id)
        return {"doc_id": doc_id, "status": STATUS_FAILED, "step": STEP_PIPELINE, "error": err_msg, "filename": filename}


# ── Case finalization task (chord callback) ───────────────────────────────────────

@celery_app.task(ignore_result=True)
def finalize_case_task(results: list, case_id: str):
    """Runs once after ALL documents in the case have been processed."""
    success_ids = {
        r["doc_id"] for r in results
        if isinstance(r, dict) and r.get("status") == STATUS_COMPLETE
    }

    # Clean up errors for docs that just succeeded
    for doc_id in success_ids:
        try:
            remove_error_for_doc(case_id, doc_id)
        except Exception as e:
            logger.warning("Failed to remove error for %s/%s: %s", case_id, doc_id, e)

    # Determine final status
    failed_count = sum(
        1 for r in results
        if isinstance(r, dict) and r.get("status") in (STATUS_FAILED, STATUS_CLASSIFICATION_FAILED)
    )
    case_status = STATUS_COMPLETE if failed_count == 0 else STATUS_PARTIAL
    set_case_status(case_id, case_status)

    # Update MySQL
    try:
        mysql_update_case_status(case_id=case_id)
    except Exception as e:
        append_log(case_id, f"⚠ Case status DB update failed: {e}")

    total = len(results)
    append_log(case_id, f"── Pipeline done: {total - failed_count} complete, {failed_count} failed ──")
