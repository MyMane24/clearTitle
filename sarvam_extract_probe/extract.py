"""Minimal Sarvam Doc-AI Extract client over plain HTTP (SDK 0.1.28 has no doc_ai.extract).

Endpoints (from docs.sarvam.ai):
  POST /doc-ai/v1/job/extract        create+submit (multipart: file, schema, language, output_format)
  GET  /doc-ai/v1/job/<id>/status    poll
  GET  /doc-ai/v1/job/<id>/results   structured JSON
"""
import json
import time
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
import sys  # noqa: E402
sys.path.insert(0, str(_REPO))

from backend.config import SARVAM_API_KEY  # noqa: E402

BASE_URL = "https://api.sarvam.ai/doc-ai/v1"
TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
POLL_SECONDS = 3
MAX_WAIT_SECONDS = 240


def run_extract(file_path: Path, schema: dict, language: str = "kn-IN") -> dict:
    headers = {"api-subscription-key": SARVAM_API_KEY}
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/pdf")}
        data = {"schema": json.dumps(schema), "language": language, "output_format": "json"}
        resp = requests.post(f"{BASE_URL}/job/extract", headers=headers, files=files, data=data, timeout=120)

    if not resp.ok:
        return {"error": True, "stage": "create", "http_status": resp.status_code, "body": resp.text}
    payload = resp.json()

    job_id = payload.get("job_id")
    if not job_id:
        return {"error": True, "stage": "create", "payload": payload}

    deadline = time.time() + MAX_WAIT_SECONDS
    status = payload.get("status", "pending")
    usage = None
    status_resp = None
    while status.lower() not in TERMINAL and time.time() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            status_resp = requests.get(f"{BASE_URL}/job/{job_id}/status", headers=headers, timeout=60)
            status_resp.raise_for_status()
            status = status_resp.json().get("status", "unknown")
            usage = status_resp.json().get("usage", usage)
        except requests.RequestException as e:
            return {"error": True, "job_id": job_id, "stage": "status_poll", "http_status": getattr(e.response, "status_code", None), "body": str(e)}

    if status.lower() not in TERMINAL:
        return {"error": True, "job_id": job_id, "stage": "timeout", "final_status": status, "usage": usage}

    try:
        results = requests.get(f"{BASE_URL}/job/{job_id}/results", headers=headers, timeout=60)
        results.raise_for_status()
        body = results.json()
        return {
            "job_id": job_id,
            "final_status": status,
            "usage": usage or body.get("usage"),
            "result_status": results.status_code,
            "result": body.get("result"),
        }
    except requests.RequestException as e:
        return {"error": True, "job_id": job_id, "stage": "results", "http_status": getattr(e.response, "status_code", None), "body": str(e), "final_status": status, "usage": usage}