"""Concrete pipeline stages (plan §4.3, §5.1).

Each stage wraps the logic formerly in `backend.pipeline.tasks` verbatim behind
`invoke(ctx, input_data)`. Celery/idempotency/tracing live in `workers/tasks.py`
via the `workers/stage_adapter.py` bridge.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from backend.database.repositories.document_repo import (
    increment_retry,
    load_document_paths,
    update_document_status,
)
from backend.integrations.llm.model_router import resolve_model
from backend.integrations.ocr.ocr_merger import merge_chunked_outputs
from backend.integrations.ocr.preprocessor import preprocess_pdf
from backend.integrations.ocr.sarvam_client import ChunkResult
from backend.integrations.redis.state_store import append_log
from backend.integrations.storage.file_utils import get_case_dir, write_json
from backend.logger import get_logger
from backend.services.classifier import VALID_DOC_TYPES, classify_document
from backend.services.extract import (
    run_ocr_with_retry as _run_ocr_with_retry,
)
from backend.services.extract import (
    structure_document as _structure_document,
)
from backend.services.extract import (
    structured_output_path as _structured_output_path,
)
from backend.shared.constants import (
    ENCUMBRANCE_CERTIFICATE,
    SALE_DEED,
    STATUS_CLASSIFICATION_FAILED,
    STATUS_CLASSIFYING,
    STATUS_FAILED,
    STATUS_MERGED,
    STATUS_OCR_DONE,
    STATUS_PREPROCESSED,
    STATUS_STRUCTURED,
    STATUS_STRUCTURING,
    UNKNOWN_DOC,
)
from backend.workers.context import StageContext
from backend.workers.stage_base import ExtractionStage

logger = get_logger(__name__)


def _log(case_id: str, msg: str) -> None:
    append_log(case_id, msg)


class ClassificationFailed(Exception):
    """Exception raised when document classification yields UNKNOWN."""
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
        _log(case_id, f"── [{doc_id}] {pdf_path.name} ─────────────────")
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

            merged_path = case_dir / "ocr_raw" / f"{doc_id}_merged.json"
            write_json(merged_path, merged)

            _log(case_id, f"[{doc_id}] ✓ Merged — {merged['total_pages']} pages, {len(merged['full_text'])} chars")
            update_document_status(
                case_id=case_id, doc_id=doc_id, status=STATUS_MERGED,
                file_paths={"merged_ocr": str(merged_path)},
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
        raw_path_str = paths.get("raw")
        if not raw_path_str:
            raise ValueError(f"No raw path found for doc_id {doc_id}")
        pdf_name = Path(raw_path_str).name

        merged_path_str = paths.get("merged_ocr")
        if not merged_path_str:
            raise ValueError(f"No merged OCR path found for doc_id {doc_id}")

        try:
            with open(merged_path_str, encoding="utf-8") as f:
                merged = json.load(f)

            doc_type = classify_document(pdf_name, merged["full_text"][:2000])

            if doc_type == UNKNOWN_DOC:
                expected = ctx.state.get_expected_type(case_id, doc_id)
                if expected in (SALE_DEED, ENCUMBRANCE_CERTIFICATE):
                    _log(case_id, f"[{doc_id}] ⚠ Classifier unsure; using declared upload slot → {expected}")
                    doc_type = expected

            logger.info("Document classified as %s for doc_id %s", doc_type, doc_id)

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
                raise ClassificationFailed(err_msg)

            _log(case_id, f"[{doc_id}] ✓ Classified → {doc_type}")
            update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_CLASSIFYING, document_type=doc_type)
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
        paths = load_document_paths(case_id, doc_id)
        merged_path_str = paths.get("merged_ocr")
        if not merged_path_str:
            raise ValueError(f"No merged OCR path found for doc_id {doc_id}")

        with open(merged_path_str, encoding="utf-8") as f:
            merged = json.load(f)

        # Read doc_type from MySQL via the state port
        doc_type = ctx.state.get_document_type(case_id, doc_id)

        if not doc_type:
            raise ValueError(f"No document type found in DB for doc_id {doc_id}")

        try:
            # Log which model is being used based on routing
            provider, model = resolve_model(doc_type)
            _log(case_id, f"[{doc_id}] Step 5: Structuring with {provider}/{model}")

            # LLM Structuring call
            llm_result = _structure_document(merged, doc_type)

            case_dir = get_case_dir(case_id)
            (case_dir / "structured").mkdir(exist_ok=True)
            out_path = _structured_output_path(case_dir, doc_id, doc_type)

            # Write temporary on-disk JSON file for decoupled processing
            temp_out_path = case_dir / "structured" / f"{doc_id}_temp.json"
            write_json(temp_out_path, llm_result)

            _log(case_id, f"[{doc_id}] ✓ Structured document using {provider}/{model}")
            # Keep status as structuring
            update_document_status(case_id=case_id, doc_id=doc_id, status=STATUS_STRUCTURING)
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

        temp_out_path = case_dir / "structured" / f"{doc_id}_temp.json"
        if not temp_out_path.exists():
            raise FileNotFoundError(f"Structured temp result file not found: {temp_out_path}")

        with open(temp_out_path, encoding="utf-8") as f:
            llm_result = json.load(f)

        structured_data = llm_result["structured_data"]
        analytics = llm_result.get("_analytics", {})

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

        out_path = _structured_output_path(case_dir, doc_id, doc_type)
        write_json(out_path, structured_data)

        # Merge file paths
        file_paths = ctx.state.load_document_paths(case_id, doc_id) or {}
        file_paths["structured"] = str(out_path)

        update_document_status(
            case_id=case_id, doc_id=doc_id,
            status=STATUS_STRUCTURED,
            document_type=doc_type,
            structured_data=structured_data,
            file_paths=file_paths,
            page_count=total_pages,
            input_tokens=analytics.get("input_tokens", 0),
            output_tokens=analytics.get("output_tokens", 0),
            latency_ms=analytics.get("latency_ms", 0),
            cost_usd=analytics.get("cost_usd", 0),
            model_used=analytics.get("model", ""),
            error="",
        )

        _log(case_id, f"[{doc_id}] ✓ Saved to DB ({analytics.get('model', '')} {analytics.get('input_tokens', 0)} in / {analytics.get('output_tokens', 0)} out tokens, ${analytics.get('cost_usd', 0):.6f})")

        # Clean up temp file
        try:
            temp_out_path.unlink(missing_ok=True)
        except Exception:
            pass

        return {"status": "success"}
