"""Concrete pipeline stages (plan §4.3, §5.1).

Each stage wraps the logic formerly in `backend.pipeline.tasks` verbatim behind
`invoke(ctx, input_data)`. Celery/idempotency/tracing live in `workers/tasks.py`
via the `workers/stage_adapter.py` bridge.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from backend.config import DOCUMENT_PROCESSOR_MODEL
from backend.database.repositories.document_repo import (
    increment_retry,
    load_document_paths,
    update_document_status,
)
from backend.integrations.ocr.ocr_merger import merge_chunked_outputs
from backend.integrations.ocr.preprocessor import preprocess_pdf
from backend.integrations.ocr.sarvam_client import ChunkResult
from backend.integrations.redis.state_store import append_log
from backend.integrations.storage.file_utils import get_case_dir, write_json
from backend.logger import get_logger
from backend.services.document_processor import (
    UnsupportedDocumentError,
    classify_document,
    extract_document,
    retrieve_schema,
)
from backend.services.extract import (
    run_ocr_with_retry as _run_ocr_with_retry,
)
from backend.services.extract import (
    structured_output_path as _structured_output_path,
)
from backend.shared.constants import (
    ENCUMBRANCE_CERTIFICATE,
    STATUS_CLASSIFICATION_FAILED,
    STATUS_FAILED,
    STATUS_MERGED,
    STATUS_OCR_DONE,
    STATUS_PREPROCESSED,
    STATUS_STRUCTURED,
    STATUS_STRUCTURING,
)
from backend.shared.ec_ledger import normalize_ec_structured
from backend.workers.context import StageContext
from backend.workers.stage_base import ExtractionStage

logger = get_logger(__name__)


def _read_merged_ocr(ctx: StageContext, paths: dict) -> tuple[str, int]:
    """Prefer canonical DB OCR, with the merged JSON artifact as a legacy fallback."""
    text = ctx.state.get_document_ocr_text(ctx.case_id, ctx.doc_id)
    page_count = 0
    merged_path = paths.get("merged_ocr")
    merged = {}
    if merged_path:
        try:
            with open(merged_path, encoding="utf-8") as f:
                merged = json.load(f)
        except (OSError, json.JSONDecodeError):
            merged = {}
    if not text:
        text = merged.get("full_text") or ""
    page_count = int(merged.get("total_pages") or 0)
    if not text.strip():
        raise ValueError(f"Merged OCR text is missing for {ctx.case_id}/{ctx.doc_id}")
    return text, page_count


def _log(case_id: str, msg: str) -> None:
    append_log(case_id, msg)


class ClassificationFailed(Exception):
    """Exception raised when document classification yields UNKNOWN."""
    pass


class OcrInsufficientCredits(Exception):
    """Non-retryable OCR provider billing/quota error."""
    pass


class PreprocessStage(ExtractionStage):
    name = "preprocess"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Starting preprocessing for case %s, doc %s", case_id, doc_id)
        paths = load_document_paths(case_id, doc_id)
        raw_path = paths.get("raw")
        if not raw_path:
            raise ValueError(f"No raw path found for doc_id {doc_id}")

        pdf_path = Path(raw_path)
        _log(case_id, f"-- [{doc_id}] {pdf_path.name} -----------------")
        _log(case_id, f"[{doc_id}] Step 1: Preprocessing (contrast/denoise/deskew)")
        case_dir = get_case_dir(case_id)
        (case_dir / "preprocessed").mkdir(exist_ok=True)

        out_pdf_path = case_dir / "preprocessed" / f"{doc_id}_prep.pdf"
        try:
            preprocessed_pdf = preprocess_pdf(pdf_path, out_pdf_path)
            logger.info("Preprocessing complete for %s, output: %s", doc_id, preprocessed_pdf)
            _log(case_id, f"[{doc_id}] ✓ Preprocessing complete → {preprocessed_pdf.name}")
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_PREPROCESSED,
                file_paths={"preprocessed": str(preprocessed_pdf)},
            )
        except Exception as e:
            logger.warning("Preprocessing failed for %s (%s), using original PDF", doc_id, e)
            _log(case_id, f"[{doc_id}] ⚠ Preprocessing failed ({e}), using original")
            # Non-fatal: write raw as preprocessed path
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_PREPROCESSED,
                file_paths={"preprocessed": str(pdf_path)},
            )
        return {"status": "success"}


class OcrStage(ExtractionStage):
    name = "ocr"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Starting OCR for case %s, doc %s", case_id, doc_id)
        _log(case_id, f"[{doc_id}] Step 2: Running Sarvam OCR")
        paths = load_document_paths(case_id, doc_id)
        pdf_path_str = paths.get("preprocessed") or paths.get("raw")
        if not pdf_path_str:
            raise ValueError(f"No PDF path found for doc_id {doc_id}")

        pdf_path = Path(pdf_path_str)
        case_dir = get_case_dir(case_id)
        (case_dir / "ocr_raw").mkdir(exist_ok=True)

        try:
            ocr_results = _run_ocr_with_retry(pdf_path, case_dir / "ocr_raw" / doc_id)
            write_json(
                case_dir / "ocr_raw" / f"{doc_id}_chunks.json",
                {"chunks": [asdict(chunk) for chunk in ocr_results]},
            )

            complete_chunks = [c for c in ocr_results if c.status == "complete"]
            failed_chunks = [c for c in ocr_results if c.status != "complete"]
            _log(case_id, f"[{doc_id}] ✓ OCR done — {len(complete_chunks)}/{len(ocr_results)} chunk(s) complete")

            if any("insufficient credits" in (c.error or "").casefold() for c in failed_chunks):
                raise OcrInsufficientCredits(
                    "OCR unavailable: Sarvam reports insufficient credits. Add credits to the Sarvam account, "
                    "then retry this document."
                )

            if not complete_chunks:
                failed_chunks = [c for c in ocr_results if c.status != "complete"]
                chunk_errors = "; ".join(f"chunk {c.chunk_index}: {c.error or c.status}" for c in failed_chunks)
                raise RuntimeError(f"All Sarvam OCR chunks failed. {chunk_errors}")

            for c in failed_chunks:
                _log(case_id, f"[{doc_id}] ⚠ OCR chunk {c.chunk_index} failed: {c.error}")

            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_OCR_DONE,
                file_paths={"ocr_chunks": str(case_dir / "ocr_raw" / doc_id)},
                error="",
            )
        except Exception as e:
            logger.error("OCR failed for case %s, doc %s: %s", case_id, doc_id, e)
            _log(case_id, f"[{doc_id}] ✗ OCR failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            raise e
        return {"status": "success"}


class MergeStage(ExtractionStage):
    name = "merge"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Merging OCR chunks for case %s, doc %s", case_id, doc_id)
        _log(case_id, f"[{doc_id}] Step 3: Merging OCR chunks")
        case_dir = get_case_dir(case_id)
        chunks_path = case_dir / "ocr_raw" / f"{doc_id}_chunks.json"
        if not chunks_path.exists():
            raise FileNotFoundError(f"OCR chunks file not found: {chunks_path}")

        try:
            with open(chunks_path, encoding="utf-8") as f:
                data = json.load(f)

            ocr_results = [ChunkResult(**c) for c in data.get("chunks", [])]
            merged = merge_chunked_outputs(ocr_results)

            # OCR engines may emit printed page labels (or hallucinated page
            # numbers) in their page records. The displayed count must reflect
            # the physical PDF, not the maximum OCR-reported label.
            paths = load_document_paths(case_id, doc_id)
            source_pdf = paths.get("preprocessed") or paths.get("raw")
            if source_pdf:
                try:
                    import fitz

                    with fitz.open(source_pdf) as pdf:
                        merged["total_pages"] = pdf.page_count
                except Exception as page_count_error:
                    logger.warning(
                        "Could not determine physical PDF page count for %s/%s: %s",
                        case_id, doc_id, page_count_error,
                    )

            merged_path = case_dir / "ocr_raw" / f"{doc_id}_merged.json"
            write_json(merged_path, merged)

            _log(case_id, f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, {len(merged['full_text'])} chars")
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_MERGED,
                file_paths={"merged_ocr": str(merged_path)},
                merged_ocr_text=merged.get("full_text", ""),
                page_count=merged.get("total_pages", 0),
                error="",
            )
        except Exception as e:
            logger.error("Merging failed for case %s, doc %s: %s", case_id, doc_id, e)
            _log(case_id, f"[{doc_id}] ✗ Merge failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            raise e
        return {"status": "success"}


class ClassifyStage(ExtractionStage):
    name = "classify"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Classifying document for case %s, doc %s", case_id, doc_id)
        _log(case_id, f"[{doc_id}] Step 4: Classifying document")
        paths = load_document_paths(case_id, doc_id)
        try:
            ocr_text, page_count = _read_merged_ocr(ctx, paths)
            classification = classify_document(ocr_text)
            doc_type = classification["document_type"]
            analytics = classification.get("analytics", {})
            update_document_status(
                case_id=case_id, doc_id=doc_id, status="classified",
                document_type=doc_type,
                page_count=page_count,
                input_tokens=int(analytics.get("input_tokens") or 0),
                output_tokens=int(analytics.get("output_tokens") or 0),
                latency_ms=int(analytics.get("latency_ms") or 0),
                cost_usd=float(analytics.get("cost_usd") or 0),
                model_used=str(analytics.get("model") or ""), error="",
            )
            logger.info("Document classified and extracted as %s for doc_id %s", doc_type, doc_id)
            _log(case_id, f"[{doc_id}] ✓ Classification complete → {doc_type}; matching schema lookup complete")
        except UnsupportedDocumentError as e:
            message = str(e)
            _log(case_id, f"[{doc_id}] ⚠ Document needs user action: {message}")
            update_document_status(
                case_id=case_id, doc_id=doc_id,
                status=STATUS_CLASSIFICATION_FAILED, document_type=e.document_type,
                error=str(e),
            )
            raise ClassificationFailed(e.user_message) from e
        except Exception as e:
            if isinstance(e, ClassificationFailed):
                raise e
            logger.error("Classification failed for case %s, doc %s: %s", case_id, doc_id, e)
            _log(case_id, f"[{doc_id}] ✗ Classification failed: {e}")
            increment_retry(case_id=case_id, doc_id=doc_id, error=str(e))
            raise e
        return {"status": "success", "doc_type": doc_type}


class StructureStage(ExtractionStage):
    name = "structure"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Structuring document for case %s, doc %s", case_id, doc_id)
        # Read doc_type from MySQL via the state port
        doc_type = ctx.state.get_document_type(case_id, doc_id)

        if not doc_type:
            raise ValueError(f"No document type found in DB for doc_id {doc_id}")

        try:
            paths = load_document_paths(case_id, doc_id)
            ocr_text, _ = _read_merged_ocr(ctx, paths)
            canonical_type, schema = retrieve_schema(doc_type)
            output = extract_document(ocr_text, canonical_type or doc_type, schema)
            analytics = output.get("analytics", {})
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_STRUCTURING,
                document_type=canonical_type or doc_type,
                structured_data=output["structured_data"],
                summary=output["summary"],
                input_tokens=int(analytics.get("input_tokens") or 0),
                output_tokens=int(analytics.get("output_tokens") or 0),
                latency_ms=int(analytics.get("latency_ms") or 0),
                cost_usd=float(analytics.get("cost_usd") or 0),
                model_used=DOCUMENT_PROCESSOR_MODEL, error="",
            )
            _log(case_id, f"[{doc_id}] ✓ Full-text extraction and document summary saved using {'one retrieved schema' if schema else 'no schema (new property type)'}")
        except Exception as e:
            logger.error("LLM structuring failed for case %s, doc %s: %s", case_id, doc_id, e)
            _log(case_id, f"[{doc_id}] ✗ LLM structuring failed: {e}")
            update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_FAILED, error=str(e), document_type=doc_type)
            raise e
        return {"status": "success"}


class PersistStage(ExtractionStage):
    name = "persist"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        case_id = ctx.case_id
        doc_id = ctx.doc_id
        logger.info("Persisting document for case %s, doc %s", case_id, doc_id)
        _log(case_id, f"[{doc_id}] Step 6: Persisting structured data")
        case_dir = get_case_dir(case_id)

        # Read doc_type + file_paths from MySQL via the state port
        doc_type = ctx.state.get_document_type(case_id, doc_id)

        if not doc_type:
            raise ValueError(f"No document type found in DB for doc_id {doc_id}")

        structured_data = ctx.state.get_document_structured_data(case_id, doc_id)
        if not isinstance(structured_data, dict):
            raise ValueError(f"Structured JSON not found in the database for {doc_id}")

        if doc_type == ENCUMBRANCE_CERTIFICATE:
            structured_data = normalize_ec_structured(structured_data)

        # Read merged_ocr info to get total page count

        merged_path = case_dir / "ocr_raw" / f"{doc_id}_merged.json"
        total_pages = 0
        if merged_path.exists():
            try:
                with open(merged_path, encoding="utf-8") as f:
                    merged_data = json.load(f)
                    total_pages = merged_data.get("total_pages", 0)
            except Exception:
                pass

        file_paths = ctx.state.load_document_paths(case_id, doc_id) or {}
        try:
            out_path = _structured_output_path(case_dir, doc_id, doc_type)
            write_json(out_path, structured_data)
            file_paths["structured"] = str(out_path)
        except OSError as e:
            # MySQL is canonical; a full disk must not discard a valid extraction.
            logger.warning("Could not write structured artifact for %s/%s: %s", case_id, doc_id, e)
            _log(case_id, f"[{doc_id}] ⚠ Structured JSON saved in database; disk artifact unavailable")

        update_document_status(
            case_id=case_id, doc_id=doc_id,
            status=STATUS_STRUCTURED,
            document_type=doc_type,
            structured_data=structured_data,
            file_paths=file_paths,
            page_count=total_pages,
            error="",
        )

        _log(case_id, f"[{doc_id}] ✓ Document type and structured JSON saved to MySQL")

        return {"status": "success"}
