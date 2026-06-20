"""
Redis-backed state store for the document processing pipeline.
Replaces the in-memory JOBS dict so state survives server restarts
and can be read/written by multiple Celery workers.
"""

from __future__ import annotations

import json
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_client():
    try:
        import redis as redis_module
    except ImportError as exc:
        raise RuntimeError(
            "redis-py is not installed. Run pip install -r requirements.txt"
        ) from exc
    return redis_module.from_url(REDIS_URL, decode_responses=True)


# ── Key helpers ──────────────────────────────────────────────────────────────────

def _meta_key(case_id: str) -> str:
    return f"case:{case_id}:meta"

def _files_key(case_id: str) -> str:
    return f"case:{case_id}:files"

def _results_key(case_id: str) -> str:
    return f"case:{case_id}:results"

def _errors_key(case_id: str) -> str:
    return f"case:{case_id}:errors"

def _log_key(case_id: str) -> str:
    return f"case:{case_id}:log"

def _docs_status_key(case_id: str) -> str:
    return f"case:{case_id}:docs"

def _done_count_key(case_id: str) -> str:
    return f"case:{case_id}:done_count"


# ── Case-level operations ────────────────────────────────────────────────────────

def case_exists(case_id: str) -> bool:
    r = _get_client()
    return r.exists(_meta_key(case_id)) > 0


def init_case(case_id: str, files_data: list[dict]) -> None:
    r = _get_client()
    pipe = r.pipeline()
    pipe.hset(_meta_key(case_id), "status", "uploaded")
    pipe.hset(_meta_key(case_id), "total_docs", str(len(files_data)))
    pipe.set(_files_key(case_id), json.dumps(files_data))
    pipe.delete(_results_key(case_id))
    pipe.delete(_errors_key(case_id))
    pipe.delete(_log_key(case_id))
    pipe.delete(_docs_status_key(case_id))
    pipe.delete(_done_count_key(case_id))
    pipe.lpush(_log_key(case_id), f"Case {case_id} created — {len(files_data)} file(s) uploaded")
    pipe.ltrim(_log_key(case_id), 0, 199)
    pipe.execute()


def get_case_meta(case_id: str) -> dict:
    r = _get_client()
    data = r.hgetall(_meta_key(case_id))
    if not data:
        raise KeyError(f"Case {case_id} not found in Redis")
    return {
        "status": data.get("status", "unknown"),
        "total_docs": int(data.get("total_docs", 0)),
    }


def set_case_status(case_id: str, status: str) -> None:
    r = _get_client()
    r.hset(_meta_key(case_id), "status", status)


def get_case_files(case_id: str) -> list[dict]:
    r = _get_client()
    data = r.get(_files_key(case_id))
    if not data:
        return []
    return json.loads(data)


def update_file_in_case(case_id: str, doc_id: str, saved_path: str, filename: str) -> None:
    r = _get_client()
    files = get_case_files(case_id)
    for f in files:
        if f["doc_id"] == doc_id:
            f["saved_path"] = saved_path
            f["original_name"] = filename
            break
    r.set(_files_key(case_id), json.dumps(files))


def get_doc_file_path(case_id: str, doc_id: str) -> str | None:
    for f in get_case_files(case_id):
        if f["doc_id"] == doc_id:
            return f["saved_path"]
    return None


def get_doc_filename(case_id: str, doc_id: str) -> str | None:
    for f in get_case_files(case_id):
        if f["doc_id"] == doc_id:
            return f["original_name"]
    return None


def get_case_results(case_id: str) -> list[dict]:
    r = _get_client()
    items = r.lrange(_results_key(case_id), 0, -1)
    return [json.loads(x) for x in items]


def get_case_errors(case_id: str) -> list[dict]:
    r = _get_client()
    items = r.lrange(_errors_key(case_id), 0, -1)
    return [json.loads(x) for x in items]


def get_case_log(case_id: str) -> list[str]:
    r = _get_client()
    return r.lrange(_log_key(case_id), 0, -1)


def append_log(case_id: str, msg: str) -> None:
    r = _get_client()
    pipe = r.pipeline()
    pipe.rpush(_log_key(case_id), msg)
    pipe.ltrim(_log_key(case_id), -200, -1)
    pipe.execute()
    safe_msg = f"[{case_id}] {msg}".encode("ascii", "backslashreplace").decode("ascii")
    print(safe_msg)


def add_result(case_id: str, result: dict) -> None:
    r = _get_client()
    r.rpush(_results_key(case_id), json.dumps(result, ensure_ascii=False))


def add_error(case_id: str, error: dict) -> None:
    r = _get_client()
    r.rpush(_errors_key(case_id), json.dumps(error, ensure_ascii=False))


def remove_error_for_doc(case_id: str, doc_id: str) -> None:
    r = _get_client()
    errors = get_case_errors(case_id)
    errors = [e for e in errors if e.get("doc_id") != doc_id]
    r.delete(_errors_key(case_id))
    if errors:
        r.rpush(_errors_key(case_id), *[json.dumps(e, ensure_ascii=False) for e in errors])


def increment_done_count(case_id: str) -> int:
    r = _get_client()
    return r.incr(_done_count_key(case_id))


def get_done_count(case_id: str) -> int:
    r = _get_client()
    val = r.get(_done_count_key(case_id))
    return int(val) if val else 0


# ── Per-doc status ───────────────────────────────────────────────────────────────

def set_doc_status(case_id: str, doc_id: str, **fields) -> None:
    r = _get_client()
    key = _docs_status_key(case_id)
    existing_raw = r.hget(key, doc_id)
    existing = json.loads(existing_raw) if existing_raw else {}
    existing.update(fields)
    r.hset(key, doc_id, json.dumps(existing, ensure_ascii=False))


# ── Full flush ────────────────────────────────────────────────────────────────────

def flush_all_cases() -> int:
    """Delete ALL case:* keys from Redis. Returns count of keys deleted."""
    r = _get_client()
    keys = r.keys("case:*")
    if not keys:
        return 0
    count = len(keys)
    r.delete(*keys)
    return count


# ── Reset / cleanup ──────────────────────────────────────────────────────────────

def reset_for_retry(case_id: str) -> None:
    """Prepare Redis state for a retry run — clear done_count and reset status."""
    r = _get_client()
    pipe = r.pipeline()
    pipe.delete(_done_count_key(case_id))
    pipe.delete(_results_key(case_id))
    pipe.delete(_errors_key(case_id))
    pipe.delete(_docs_status_key(case_id))
    pipe.hset(_meta_key(case_id), "status", "processing")
    pipe.execute()


# ── Full job snapshot (for status endpoint) ──────────────────────────────────────

def get_case_job(case_id: str) -> dict:
    """Return a dict matching the old JOBS[case_id] format for frontend compat."""
    meta = get_case_meta(case_id)
    files = get_case_files(case_id)
    results = get_case_results(case_id)
    results.sort(key=lambda r: r.get("doc_id", ""))
    errors = get_case_errors(case_id)
    errors.sort(key=lambda e: e.get("doc_id", ""))
    log = get_case_log(case_id)

    done = get_done_count(case_id)
    total = meta["total_docs"]
    if total > 0:
        progress = min(100, int((done / total) * 90)) if meta["status"] == "processing" else 100
    else:
        progress = 0

    return {
        "case_id": case_id,
        "status": meta["status"],
        "files": files,
        "results": results,
        "errors": errors,
        "progress": progress,
        "log": log,
    }
