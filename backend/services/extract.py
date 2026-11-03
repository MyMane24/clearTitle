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
def safe_doc_type(doc_type: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())


def structured_output_path(case_dir: Path, doc_id: str, doc_type: str) -> Path:
    return case_dir / "structured" / f"{doc_id}_{safe_doc_type(doc_type)}.json"


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
