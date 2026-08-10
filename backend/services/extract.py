"""
Extraction helpers: OCR retry + model routing for per-document structuring.
"""

from __future__ import annotations

import time
from pathlib import Path

from backend.logger import get_logger

logger = get_logger(__name__)

OCR_MAX_RETRIES = 3
OCR_RETRY_DELAY_SEC = 5
STRUCTURE_MAX_RETRIES = 3
STRUCTURE_RETRY_DELAY_SEC = 5
MAX_RATE_LIMIT_RETRIES = 5


def safe_doc_type(doc_type: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())


def structured_output_path(case_dir: Path, doc_id: str, doc_type: str) -> Path:
    return case_dir / "structured" / f"{doc_id}_{safe_doc_type(doc_type)}.json"


def is_transient_error(e: Exception) -> bool:
    if "jsondecodeerror" in e.__class__.__name__.lower() or "json decode" in str(e).lower() or "json.decoder" in str(e).lower():
        return True
    msg = str(e).lower()
    if "quota" in msg or "exhausted" in msg or "billing" in msg:
        return False
    return any(x in msg for x in ["503", "429", "500", "413", "unavailable", "rate limit", "rate_limit", "too many requests"])


def is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(x in msg for x in ["429", "413", "quota", "exhausted", "resource_exhausted", "rate limit", "rate_limit", "too many requests"])


def run_ocr_with_retry(pdf_path: Path, output_dir: Path) -> list:
    from backend.integrations.ocr.sarvam_client import run_sarvam_ocr
    last_error: Exception | None = None
    for attempt in range(1, OCR_MAX_RETRIES + 1):
        try:
            return run_sarvam_ocr(pdf_path, output_dir)
        except Exception as e:
            last_error = e
            if attempt < OCR_MAX_RETRIES:
                time.sleep(OCR_RETRY_DELAY_SEC * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("OCR failed after all retries")


def structure_document(merged: dict, doc_type: str) -> dict:
    """Route document to the cheapest adequate model with rate-limit-aware retry + fallback."""
    from backend.integrations.llm.gemini_executor import structure_document_with_gemini
    from backend.integrations.llm.groq_executor import (
        structure_document as structure_document_with_groq,
    )
    from backend.integrations.llm.model_router import get_fallback_chain, resolve_model
    from backend.integrations.llm.rate_limiter import gemini_limiter, groq_limiter

    primary_provider, primary_model = resolve_model(doc_type)
    chain = get_fallback_chain(doc_type)
    logger.info("Routing %s → %s/%s", doc_type, primary_provider, primary_model)

    last_error = None

    for provider, model in chain:
        for attempt in range(1, STRUCTURE_MAX_RETRIES + 1):
            try:
                limiter = gemini_limiter if provider == "gemini" else groq_limiter
                acquired = limiter.wait_and_acquire(tokens=1, max_retries=MAX_RATE_LIMIT_RETRIES)
                if not acquired:
                    logger.warning("Rate limit timeout for %s/%s, trying next model", provider, model)
                    break

                if provider == "groq":
                    return structure_document_with_groq(
                        merged, doc_type,
                        model_override=model if model != "llama-3.1-8b-instant" else None,
                        retry_count=attempt - 1,
                    )
                else:
                    return structure_document_with_gemini(
                        merged, doc_type,
                        retry_count=attempt - 1,
                    )

            except Exception as e:
                last_error = e
                logger.warning("%s/%s attempt %d failed for %s: %s",
                               provider, model, attempt, doc_type, e)

                if is_transient_error(e) and attempt < STRUCTURE_MAX_RETRIES:
                    backoff = (STRUCTURE_RETRY_DELAY_SEC * attempt) + (0.5 * attempt)
                    time.sleep(backoff)
                elif is_rate_limit_error(e):
                    logger.info("Rate limited on %s/%s, falling back to next model", provider, model)
                    break
                else:
                    break

    if last_error:
        raise last_error
    raise RuntimeError(f"All models failed for {doc_type}")
