"""
Redis-backed state store for the document processing pipeline.
Replaces the in-memory JOBS dict so state survives server restarts
and can be read/written by multiple Celery workers.
"""

from __future__ import annotations

import json

from backend.services.redis_client import get_redis as _get_client




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
    if r.exists(_meta_key(case_id)) > 0:
        return True

    # Fallback to MySQL
    try:
        from backend.services.mysql_store import _get_conn
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, total_docs FROM cases WHERE id = %s", (case_id,))
            row = cursor.fetchone()
            if row:
                status, total_docs = row
                pipe = r.pipeline()
                pipe.hset(_meta_key(case_id), "status", status)
                pipe.hset(_meta_key(case_id), "total_docs", str(total_docs))
                pipe.execute()
                # Trigger file caching too
                get_case_files(case_id)
                return True
    except Exception as e:
        print(f"Fallback check in MySQL failed for case_exists: {e}")

    return False


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
    if data:
        return json.loads(data)

    # Reconstruct from MySQL
    try:
        from backend.services.mysql_store import _get_conn
        with _get_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT doc_id, filename, file_paths FROM documents WHERE case_id = %s ORDER BY doc_index ASC", (case_id,))
            rows = cursor.fetchall()
            if rows:
                files_data = []
                for row in rows:
                    paths = row.get("file_paths")
                    if isinstance(paths, str):
                        paths = json.loads(paths)
                    saved_path = paths.get("raw") if isinstance(paths, dict) else None
                    files_data.append({
                        "doc_id": row["doc_id"],
                        "original_name": row["filename"],
                        "saved_path": saved_path,
                    })
                r.set(_files_key(case_id), json.dumps(files_data))
                return files_data
    except Exception as e:
        print(f"Fallback to MySQL failed for get_case_files: {e}")

    return []


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
        if f["doc_id"] == doc_id and f.get("saved_path"):
            return f["saved_path"]

    # Fallback to MySQL
    try:
        from backend.services.mysql_store import _get_conn
        with _get_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT file_paths FROM documents WHERE case_id = %s AND doc_id = %s", (case_id, doc_id))
            row = cursor.fetchone()
            if row and row.get("file_paths"):
                paths = row["file_paths"]
                if isinstance(paths, str):
                    paths = json.loads(paths)
                if isinstance(paths, dict) and "raw" in paths:
                    raw_path = paths["raw"]
                    try:
                        update_file_in_case(case_id, doc_id, raw_path, get_doc_filename(case_id, doc_id) or doc_id)
                    except Exception:
                        pass
                    return raw_path
    except Exception as e:
        print(f"Fallback to MySQL failed for get_doc_file_path: {e}")

    return None


def get_doc_filename(case_id: str, doc_id: str) -> str | None:
    for f in get_case_files(case_id):
        if f["doc_id"] == doc_id:
            return f["original_name"]

    # Fallback to MySQL
    try:
        from backend.services.mysql_store import _get_conn
        with _get_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT filename FROM documents WHERE case_id = %s AND doc_id = %s", (case_id, doc_id))
            row = cursor.fetchone()
            if row and row.get("filename"):
                return row["filename"]
    except Exception as e:
        print(f"Fallback to MySQL failed for get_doc_filename: {e}")

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
    try:
        from backend.services.mysql_store import append_pipeline_log
        append_pipeline_log(case_id, msg)
    except Exception as e:
        print(f"Failed to append log to MySQL: {e}")


def add_result(case_id: str, result: dict) -> None:
    r = _get_client()
    r.rpush(_results_key(case_id), json.dumps(result, ensure_ascii=False))


def add_error(case_id: str, error: dict) -> None:
    r = _get_client()
    r.rpush(_errors_key(case_id), json.dumps(error, ensure_ascii=False))


def remove_error_for_doc(case_id: str, doc_id: str) -> None:
    r = _get_client()
    errors = get_case_errors(case_id)
    filtered = [e for e in errors if e.get("doc_id") != doc_id]
    # Use MULTI/EXEC (transaction=True) so the delete and re-push are atomic.
    # Without this, a concurrent reader sees an empty errors list in the
    # brief window between the DELETE and the RPUSH.
    pipe = r.pipeline(transaction=True)
    pipe.delete(_errors_key(case_id))
    if filtered:
        pipe.rpush(_errors_key(case_id), *[json.dumps(e, ensure_ascii=False) for e in filtered])
    pipe.execute()


def increment_done_count(case_id: str) -> int:
    r = _get_client()
    return r.incr(_done_count_key(case_id))


def get_done_count(case_id: str) -> int:
    r = _get_client()
    val = r.get(_done_count_key(case_id))
    return int(val) if val else 0


# Lua script for atomic read-merge-write on the per-doc status JSON blob.
# Eliminates the TOCTOU race where two concurrent workers both read the same
# stale value, merge different fields, and one silently overwrites the other.
#
# KEYS[1] = docs hash key  (case:{id}:docs)
# KEYS[2] = doc_id field   (the hash field to update)
# ARGV[1] = JSON string of the fields to merge in
_SET_DOC_STATUS_LUA = """\
local raw = redis.call('HGET', KEYS[1], KEYS[2])
local existing = {}
if raw then
    local ok, val = pcall(cjson.decode, raw)
    if ok and type(val) == 'table' then existing = val end
end
local ok2, updates = pcall(cjson.decode, ARGV[1])
if not ok2 then return redis.error_reply('set_doc_status: bad JSON in updates') end
for k, v in pairs(updates) do existing[k] = v end
redis.call('HSET', KEYS[1], KEYS[2], cjson.encode(existing))
return 1
"""


def set_doc_status(case_id: str, doc_id: str, **fields) -> None:
    r = _get_client()
    key = _docs_status_key(case_id)
    updates_json = json.dumps(fields, ensure_ascii=False)
    r.eval(_SET_DOC_STATUS_LUA, 2, key, doc_id, updates_json)



# ── Single-case delete ────────────────────────────────────────────────────────────

def delete_case(case_id: str) -> int:
    """Delete all Redis keys for a single case. Returns count of keys deleted."""
    r = _get_client()
    keys = r.keys(f"case:{case_id}:*")
    if not keys:
        return 0
    count = len(keys)
    r.delete(*keys)
    return count


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


def add_files_to_case(case_id: str, new_files: list[dict]) -> None:
    r = _get_client()
    meta = get_case_meta(case_id)
    old_total = meta.get("total_docs", 0)
    new_total = old_total + len(new_files)

    pipe = r.pipeline()
    pipe.hset(_meta_key(case_id), "total_docs", str(new_total))
    pipe.hset(_meta_key(case_id), "status", "uploaded")

    files = get_case_files(case_id)
    files.extend(new_files)
    pipe.set(_files_key(case_id), json.dumps(files))
    pipe.execute()
