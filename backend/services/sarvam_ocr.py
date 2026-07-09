"""
Sarvam OCR Service
- Detects page count
- If <= 10 pages: single API call
- If > 10 pages: splits into overlapping 10-page chunks, processes in parallel
- Returns list of ChunkResult dicts
"""

import os
import json
import time
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List

import fitz                        # PyMuPDF
from sarvamai import SarvamAI
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY  = os.getenv("SARVAM_API_KEY", "")
CHUNK_SIZE      = 10               # Sarvam hard limit
CHUNK_OVERLAP   = 1                # overlap pages between chunks
MAX_WORKERS     = 3                # parallel Sarvam calls
MAX_RETRIES     = 3
RETRY_DELAYS    = [5, 15, 30]
OUTPUT_LANGUAGE = "kn-IN"          # Kannada + English
OUTPUT_FORMAT   = "md"


@dataclass
class ChunkResult:
    chunk_index: int
    page_start:  int
    page_end:    int
    status:      str  = "pending"
    md_text:     str  = ""
    json_data:   dict = field(default_factory=dict)
    error:       str  = ""


_sarvam_client = None

def _get_sarvam_client():
    global _sarvam_client
    if _sarvam_client is None:
        if not SARVAM_API_KEY:
            raise ValueError("SARVAM_API_KEY not set in .env")
        client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
        if not hasattr(client, "document_intelligence"):
            raise RuntimeError(
                "Installed sarvamai SDK does not include document_intelligence. "
                "Install sarvamai>=0.1.28."
            )
        _sarvam_client = client
    return _sarvam_client


def run_sarvam_ocr(pdf_path: Path, out_dir: Path) -> List[ChunkResult]:
    """
    Main entry point.
    Returns list of ChunkResult (one per chunk).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    client = _get_sarvam_client()

    # Detect page count
    doc        = fitz.open(str(pdf_path))
    page_count = doc.page_count
    doc.close()

    # Build chunk ranges
    chunks = _build_chunk_ranges(page_count)

    if len(chunks) == 1:
        # Short document — single call, send PDF directly
        result = _process_single_pdf(client, pdf_path, 0,
                                      1, page_count, out_dir)
        return [result]
    else:
        # Long document — convert to PNGs, zip each chunk, parallel calls
        return _process_chunked(client, pdf_path, chunks, out_dir)


def _build_chunk_ranges(total_pages: int) -> List[tuple]:
    """Returns list of (chunk_idx, start_page_1based, end_page_1based)."""
    if total_pages <= CHUNK_SIZE:
        return [(0, 1, total_pages)]

    step    = CHUNK_SIZE - CHUNK_OVERLAP
    chunks  = []
    idx     = 0
    start   = 0                     # 0-based
    while start < total_pages:
        end = min(start + CHUNK_SIZE, total_pages)
        chunks.append((idx, start + 1, end))  # store 1-based
        idx  += 1
        start += step
    return chunks


def _process_single_pdf(client, pdf_path: Path, chunk_idx: int,
                          page_start: int, page_end: int,
                          out_dir: Path) -> ChunkResult:
    """Send a PDF file directly to Sarvam."""
    cr = ChunkResult(chunk_index=chunk_idx,
                     page_start=page_start,
                     page_end=page_end)
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            job = client.document_intelligence.create_job(
                language=OUTPUT_LANGUAGE, output_format=OUTPUT_FORMAT)
            job.upload_file(str(pdf_path))
            job.start()
            status = job.wait_until_complete()

            if not _is_success_status(status):
                raise RuntimeError(_describe_status(status))

            out_zip = out_dir / f"chunk_{chunk_idx:02d}_response.zip"
            job.download_output(str(out_zip))
            cr.md_text, cr.json_data = _extract_zip(out_zip)
            cr.status = "complete"
            if status.job_state == "PartiallyCompleted":
                cr.error = _describe_status(status)
            return cr

        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

    cr.status = "failed"
    cr.error  = str(last_err)
    return cr


def _process_chunked(client, pdf_path: Path,
                      chunks: List[tuple], out_dir: Path) -> List[ChunkResult]:
    """Convert PDF pages to PNG zips and process each chunk in parallel."""
    png_dir = out_dir / "pages"
    png_dir.mkdir(exist_ok=True)

    # Render all pages to PNG
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(200 / 72, 200 / 72)   # 200 DPI
    for i, page in enumerate(doc):
        pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        pix.save(str(png_dir / f"page_{i+1:04d}.png"))
    doc.close()

    # Build one zip per chunk
    zip_paths = []
    for chunk_idx, p_start, p_end in chunks:
        zp = out_dir / f"chunk_{chunk_idx:02d}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for page_num in range(p_start, p_end + 1):
                src = png_dir / f"page_{page_num:04d}.png"
                if src.exists():
                    # re-index from 001 inside zip so Sarvam orders correctly
                    zf.write(src, f"page_{(page_num - p_start + 1):04d}.png")
        zip_paths.append((chunk_idx, p_start, p_end, zp))

    # Send all zips in parallel
    results: List[ChunkResult] = []

    def send_chunk(args):
        cidx, ps, pe, zp = args
        return _send_zip(client, zp, cidx, ps, pe, out_dir)

    try:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(zip_paths))) as ex:
            futures = {ex.submit(send_chunk, a): a for a in zip_paths}
            for f in as_completed(futures):
                results.append(f.result())
    finally:
        # Clean up temp PNGs and input zips — response zips are kept for the merger
        import shutil
        shutil.rmtree(png_dir, ignore_errors=True)
        for _, _, _, zp in zip_paths:
            try:
                zp.unlink(missing_ok=True)
            except Exception:
                pass

    return sorted(results, key=lambda r: r.chunk_index)


def _send_zip(client, zip_path: Path, chunk_idx: int,
               page_start: int, page_end: int, out_dir: Path) -> ChunkResult:
    """Send a ZIP of PNG pages to Sarvam."""
    cr = ChunkResult(chunk_index=chunk_idx,
                     page_start=page_start,
                     page_end=page_end)
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            job = client.document_intelligence.create_job(
                language=OUTPUT_LANGUAGE, output_format=OUTPUT_FORMAT)
            job.upload_file(str(zip_path))
            job.start()
            status = job.wait_until_complete()

            if not _is_success_status(status):
                raise RuntimeError(_describe_status(status))

            out_zip = out_dir / f"chunk_{chunk_idx:02d}_response.zip"
            job.download_output(str(out_zip))
            cr.md_text, cr.json_data = _extract_zip(out_zip)
            cr.status = "complete"
            if status.job_state == "PartiallyCompleted":
                cr.error = _describe_status(status)
            return cr

        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

    cr.status = "failed"
    cr.error  = str(last_err)
    return cr


def _is_success_status(status) -> bool:
    return getattr(status, "job_state", None) in {"Completed", "PartiallyCompleted"}


def _describe_status(status) -> str:
    """Build a compact, user-readable Sarvam job status/error summary."""
    parts = [f"Job state: {getattr(status, 'job_state', 'unknown')}"]
    error_message = getattr(status, "error_message", None)
    if error_message:
        parts.append(str(error_message))

    for detail in getattr(status, "job_details", None) or []:
        metrics = []
        for name in ("total_pages", "pages_processed", "pages_succeeded", "pages_failed"):
            value = getattr(detail, name, None)
            if value is not None:
                metrics.append(f"{name}={value}")

        detail_parts = []
        state = getattr(detail, "state", None)
        if state:
            detail_parts.append(f"state={state}")
        if metrics:
            detail_parts.append(", ".join(metrics))
        if getattr(detail, "error_code", None):
            detail_parts.append(f"error_code={detail.error_code}")
        if getattr(detail, "error_message", None):
            detail_parts.append(str(detail.error_message))

        if detail_parts:
            parts.append("; ".join(detail_parts))

    return " | ".join(parts)


def _extract_zip(zip_path: Path) -> tuple[str, dict]:
    """Extract .md text and .json data from Sarvam response zip."""
    md_text   = ""
    json_data = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".md"):
                md_text = zf.read(name).decode("utf-8")
            elif name.endswith(".json"):
                json_data = json.loads(zf.read(name).decode("utf-8"))
    return md_text, json_data
