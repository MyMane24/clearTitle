"""Minimal Bodhan AI Indic-OCR client over plain HTTP (mirrors sarvam probe).

Endpoint (console.bodhan.ai/api-docs):
  POST /v1/chat/completions  model=indic-ocr, one page image per request
PNG/JPEG only, no PDF, no language field (script is inferred). We render each
PDF page to PNG with PyMuPDF and fire one request per page.
"""
import base64
import json
import sys
import time
from pathlib import Path

import fitz
import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # repo root, for backend.config

from backend.config import BODHAN_API_KEY  # noqa: E402

BASE_URL = "https://api.bodhan.ai/v1/chat/completions"
PAGE_SLEEP_SECONDS = 0.5


IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def _ocr_one(data_uri: str, table_format: str, max_tokens: int) -> tuple:
    last = None
    for mt in (max_tokens, min(max_tokens * 2, 65536), min(max_tokens * 4, 65536)):
        payload = {
            "model": "indic-ocr",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_uri}}]}],
            "table_format": table_format,
            "max_tokens": mt,
        }
        try:
            resp = requests.post(BASE_URL,
                                 headers={"Authorization": f"Bearer {BODHAN_API_KEY}"},
                                 json=payload, timeout=180)
        except requests.RequestException as e:
            return {"stage": "http", "http_status": getattr(e.response, "status_code", None),
                    "body": str(e)}, None
        if resp.status_code != 200:
            last = {"stage": "ocr", "http_status": resp.status_code,
                    "body": resp.text[:2000]}
            if "truncated" not in resp.text:
                return last, None
            continue
        body = resp.json()
        return None, {
            "text": body["choices"][0]["message"]["content"],
            "blocks": body.get("blocks", []),
            "usage": body.get("usage", {}),
        }
    return last, None


MAX_LONG_EDGE = 2200


def _shrink(img_bytes: bytes, ext: str) -> tuple:
    """Downscale oversized scans to keep per-page OCR fast.

    Returns (bytes, mime). Untouched input keeps its original format; a
    resized scan is re-encoded as PNG, so the caller must label it image/png.
    """
    doc = fitz.open(stream=img_bytes, filetype=ext)
    page = doc[0]
    long_edge = max(page.rect.width, page.rect.height)
    if long_edge <= MAX_LONG_EDGE:
        doc.close()
        mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
        return img_bytes, mime
    scale = MAX_LONG_EDGE / long_edge
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB)
    data = pix.tobytes("png")
    doc.close()
    return data, "image/png"


def run_digitize(file_path: Path, table_format: str = "html",
                 max_tokens: int = 4096, dpi: int = 200) -> dict:
    if not BODHAN_API_KEY:
        return {"error": True, "stage": "auth",
                "body": "BODHAN_API_KEY not set (backend/config.py reads it from .env)"}

    if file_path.suffix.lower() in IMAGE_EXTS:
        ext = file_path.suffix.lower().lstrip(".")
        raw, mime = _shrink(file_path.read_bytes(), ext)
        b64 = base64.b64encode(raw).decode()
        err, page = _ocr_one(f"data:{mime};base64,{b64}", table_format, max_tokens)
        entry = {"page_num": 1}
        if err:
            entry["error"] = err
        else:
            entry.update(page)
        pages = [entry]
    else:
        pages = _ocr_pdf(file_path, table_format, max_tokens, dpi)

    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for p in pages:
        for k in total:
            total[k] += p.get("usage", {}).get(k, 0)
    return {"format": "json", "pages": pages, "usage": total,
            "table_format": table_format}


def _ocr_pdf(file_path: Path, table_format: str, max_tokens: int, dpi: int) -> list:
    pages = []
    doc = fitz.open(str(file_path))
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        entry = {"page_num": i + 1}
        err, page_res = _ocr_one(f"data:image/png;base64,{b64}", table_format, max_tokens)
        if err:
            entry["error"] = err
        else:
            entry.update(page_res)
        pages.append(entry)
        if doc.page_count > 1:
            time.sleep(PAGE_SLEEP_SECONDS)
    doc.close()
    return pages


def _pp_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)