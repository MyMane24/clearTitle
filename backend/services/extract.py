"""OCR with retries."""

from __future__ import annotations

import time
from pathlib import Path

OCR_MAX_RETRIES = 3
OCR_RETRY_DELAY_SEC = 5


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
