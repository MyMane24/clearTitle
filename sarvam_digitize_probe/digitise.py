"""Minimal Sarvam Doc-AI Digitise client over plain HTTP (like extract.py).

Endpoints (docs.sarvam.ai/api-reference/doc-ai/job/digitise):
  POST /doc-ai/v1/job/digitise   create+submit (multipart: file, language, output_format, model)
  GET  /doc-ai/v1/job/<id>/status
  GET  /doc-ai/v1/job/<id>/results
"""
import json
import sys
import time
import zipfile
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # repo root, for backend.config

from backend.config import SARVAM_API_KEY  # noqa: E402

BASE_URL = "https://api.sarvam.ai/doc-ai/v1"
TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
POLL_SECONDS = 3
MAX_WAIT_SECONDS = 300


def run_digitise(file_path: Path, language: str = "kn-IN",
                 output_format: str = "md", model: str = "") -> dict:
    headers = {"api-subscription-key": SARVAM_API_KEY}
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/pdf")}
        data = {"language": language, "output_format": output_format}
        if model:
            data["model"] = model
        resp = requests.post(f"{BASE_URL}/job/digitise", headers=headers,
                             files=files, data=data, timeout=120)

    if not resp.ok:
        return {"error": True, "stage": "create", "http_status": resp.status_code, "body": resp.text}
    payload = resp.json()
    job_id = payload.get("job_id")
    if not job_id:
        return {"error": True, "stage": "create", "payload": payload}

    deadline = time.time() + MAX_WAIT_SECONDS
    status = payload.get("status", "pending")
    usage = None
    while status.lower() not in TERMINAL and time.time() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            sr = requests.get(f"{BASE_URL}/job/{job_id}/status", headers=headers, timeout=60)
            sr.raise_for_status()
            body = sr.json()
            status = body.get("status", "unknown")
            usage = body.get("usage", usage)
        except requests.RequestException as e:
            return {"error": True, "job_id": job_id, "stage": "status_poll",
                    "http_status": getattr(e.response, "status_code", None), "body": str(e)}

    if status.lower() not in TERMINAL:
        return {"error": True, "job_id": job_id, "stage": "timeout",
                "final_status": status, "usage": usage}

    try:
        rr = requests.get(f"{BASE_URL}/job/{job_id}/results", headers=headers, timeout=120)
        rr.raise_for_status()
    except requests.RequestException as e:
        return {"error": True, "job_id": job_id, "stage": "results",
                "http_status": getattr(e.response, "status_code", None),
                "body": str(e), "final_status": status, "usage": usage}

    out = {"job_id": job_id, "final_status": status, "usage": usage or rr.json().get("usage") if "application/json" in rr.headers.get("content-type", "") else usage}
    out.update(_parse(rr))
    return out


def _parse(resp: requests.Response) -> dict:
    ct = resp.headers.get("content-type", "")
    if "application/json" in ct:
        body = resp.json()
        pages = _pages_from_blocks(body.get("blocks")) if body.get("blocks") else []
        return {"format": "json", "payload": body, "pages": pages}
    return _parse_zip(resp.content)


def _parse_zip(zip_bytes: bytes) -> dict:
    markdown = ""
    html = ""
    pages = []
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        md_names = sorted(n for n in zf.namelist() if n.endswith(".md"))
        html_names = sorted(n for n in zf.namelist() if n.lower().endswith((".html", ".htm")))
        for n in md_names:
            markdown += zf.read(n).decode("utf-8", "replace") + "\n"
        for n in html_names:
            html += zf.read(n).decode("utf-8", "replace") + "\n"
        for n in sorted(zf.namelist()):
            if n.startswith("metadata/page_") and n.endswith(".json"):
                meta = json.loads(zf.read(n).decode("utf-8"))
                blocks = meta.get("blocks", [])
                text = "\n".join(
                    b.get("text", "").strip()
                    for b in sorted(blocks, key=lambda b: b.get("reading_order", 0))
                    if b.get("text", "").strip()
                )
                pages.append({"page_num": meta.get("page_num", len(pages) + 1), "text": text})
    return {"format": "zip", "markdown": markdown, "html": html, "pages": pages}


def _pages_from_blocks(blocks: list) -> list:
    """Best-effort grouping of doc-ai JSON blocks into pages."""
    by_page = {}
    for b in blocks or []:
        p = b.get("page_num") or b.get("page") or b.get("doc_id") or 1
        by_page.setdefault(p, []).append(b)
    out = []
    for p in sorted(by_page):
        text = "\n".join(
            b.get("text", "").strip()
            for b in sorted(by_page[p], key=lambda b: b.get("reading_order", 0))
            if b.get("text", "").strip()
        )
        if text:
            out.append({"page_num": p, "text": text})
    return out