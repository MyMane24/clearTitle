"""
Redis-backed state store — Phase 3: READ CACHE ONLY.

MySQL is the single source of truth. Every write in this module first persists
to MySQL (via the repositories) and then updates the Redis cache best-effort;
every read tries Redis first (hot path) and falls back to MySQL when Redis
misses or is down. All Redis calls are guarded so a Redis outage never blocks
the pipeline (no stale-Redis-wins, MySQL failure is the only failure mode).

Extracted from `backend/services/redis_store.py`; behavior shift per plan §8.2.
"""

from __future__ import annotations

import json

from backend.database.connection import _get_conn
from backend.database.repositories.case_repo import (
    get_case_status_payload as _mysql_case_payload,
)
from backend.database.repositories.case_repo import (
    set_case_status as _mysql_set_case_status,
)
from backend.database.repositories.verification_repo import (
    append_pipeline_log,
)
from backend.database.repositories.verification_repo import (
    get_pipeline_logs as _mysql_pipeline_logs,
)
from backend.integrations.redis.client import get_redis as _get_client

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
    try:
        r = _get_client()
        if r.exists(_meta_key(case_id)) > 0:
            return True
    except Exception as e:
        print(f"Redis cache unavailable for case_exists: {e}")

    # MySQL is authoritative
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, total_docs FROM cases WHERE id = %s", (case_id,))
            row = cursor.fetchone()
            if row:
                status, total_docs = row
                try:
                    r = _get_client()
                    pipe = r.pipeline()
                    pipe.hset(_meta_key(case_id), "status", status)
                    pipe.hset(_meta_key(case_id), "total_docs", str(total_docs))
                    pipe.execute()
                    # Trigger file caching too
                    get_case_files(case_id)
                except Exception:
                    pass
                return True
    except Exception as e:
        print(f"Fallback check in MySQL failed for case_exists: {e}")

    return False


def init_case(case_id: str, files_data: list[dict]) -> None:
    """Warm the Redis cache for a new case. Persistence is handled by MySQL
    (`case_repo.init_case` + `document_repo.init_document`) in the router."""
    try:
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
    except Exception as e:
        print(f"Failed to warm Redis cache for case {case_id}: {e}")


def get_case_meta(case_id: str) -> dict:
    try:
        r = _get_client()
        data = r.hgetall(_meta_key(case_id))
        if data:
            return {
                "status": data.get("status", "unknown"),
                "total_docs": int(data.get("total_docs", 0)),
            }
    except Exception as e:
        print(f"Redis cache unavailable for get_case_meta: {e}")

    # MySQL is authoritative
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, total_docs FROM cases WHERE id = %s", (case_id,))
            row = cursor.fetchone()
            if row:
                return {"status": row[0], "total_docs": row[1]}
    except Exception as e:
        print(f"MySQL fallback failed for get_case_meta: {e}")
    raise KeyError(f"Case {case_id} not found in DB")


def set_case_status(case_id: str, status: str) -> None:
    """MySQL-first status write; Redis updated as a best-effort cache."""
    try:
        _mysql_set_case_status(case_id=case_id, status=status)
    except Exception as e:
        print(f"Failed to update case status in MySQL: {e}")
    try:
        r = _get_client()
        r.hset(_meta_key(case_id), "status", status)
    except Exception as e:
        print(f"Failed to update case status in Redis cache: {e}")


def get_case_files(case_id: str) -> list[dict]:
    try:
        r = _get_client()
        data = r.get(_files_key(case_id))
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"Redis cache unavailable for get_case_files: {e}")

    # Reconstruct from MySQL
    try:
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
                try:
                    r = _get_client()
                    r.set(_files_key(case_id), json.dumps(files_data))
                except Exception:
                    pass
                return files_data
    except Exception as e:
        print(f"Fallback to MySQL failed for get_case_files: {e}")

    return []


def update_file_in_case(case_id: str, doc_id: str, saved_path: str, filename: str) -> None:
    try:
        r = _get_client()
        files = get_case_files(case_id)
        for f in files:
            if f["doc_id"] == doc_id:
                f["saved_path"] = saved_path
                f["original_name"] = filename
                break
        r.set(_files_key(case_id), json.dumps(files))
    except Exception as e:
        print(f"Failed to update Redis cache for case {case_id}: {e}")


def get_doc_file_path(case_id: str, doc_id: str) -> str | None:
    try:
        for f in get_case_files(case_id):
            if f["doc_id"] == doc_id and f.get("saved_path"):
                return f["saved_path"]
    except Exception:
        pass

    # Fallback to MySQL
    try:
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
    try:
        for f in get_case_files(case_id):
            if f["doc_id"] == doc_id:
                return f["original_name"]
    except Exception:
        pass

    # Fallback to MySQL
    try:
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
    try:
        r = _get_client()
        items = r.lrange(_results_key(case_id), 0, -1)
        return [json.loads(x) for x in items]
    except Exception as e:
        print(f"Redis cache unavailable for get_case_results: {e}")

    # MySQL is authoritative
    try:
        return _mysql_case_payload(case_id).get("results", [])
    except Exception as e:
        print(f"MySQL fallback failed for get_case_results: {e}")
        return []


def get_case_errors(case_id: str) -> list[dict]:
    try:
        r = _get_client()
        items = r.lrange(_errors_key(case_id), 0, -1)
        return [json.loads(x) for x in items]
    except Exception as e:
        print(f"Redis cache unavailable for get_case_errors: {e}")

    # MySQL is authoritative
    try:
        return _mysql_case_payload(case_id).get("errors", [])
    except Exception as e:
        print(f"MySQL fallback failed for get_case_errors: {e}")
        return []


def get_case_log(case_id: str) -> list[str]:
    try:
        r = _get_client()
        return r.lrange(_log_key(case_id), 0, -1)
    except Exception as e:
        print(f"Redis cache unavailable for get_case_log: {e}")

    # MySQL is authoritative
    try:
        return _mysql_pipeline_logs(case_id)
    except Exception as e:
        print(f"MySQL fallback failed for get_case_log: {e}")
        return []


def append_log(case_id: str, msg: str) -> None:
    """MySQL-first log append (authoritative); Redis updated best-effort."""
    try:
        append_pipeline_log(case_id, msg)
    except Exception as e:
        print(f"Failed to append log to MySQL: {e}")

    safe_msg = f"[{case_id}] {msg}".encode("ascii", "backslashreplace").decode("ascii")
    print(safe_msg)

    try:
        r = _get_client()
        pipe = r.pipeline()
        pipe.rpush(_log_key(case_id), msg)
        pipe.ltrim(_log_key(case_id), -200, -1)
        pipe.execute()
    except Exception as e:
        print(f"Failed to append log to Redis cache: {e}")


def add_result(case_id: str, result: dict) -> None:
    try:
        r = _get_client()
        r.rpush(_results_key(case_id), json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(f"Failed to add result to Redis cache: {e}")


def add_error(case_id: str, error: dict) -> None:
    try:
        r = _get_client()
        r.rpush(_errors_key(case_id), json.dumps(error, ensure_ascii=False))
    except Exception as e:
        print(f"Failed to add error to Redis cache: {e}")


def remove_error_for_doc(case_id: str, doc_id: str) -> None:
    try:
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
    except Exception as e:
        print(f"Failed to remove error from Redis cache: {e}")


def increment_done_count(case_id: str) -> int:
    try:
        r = _get_client()
        return r.incr(_done_count_key(case_id))
    except Exception as e:
        print(f"Redis cache unavailable for increment_done_count: {e}")
        return 0


def get_done_count(case_id: str) -> int:
    try:
        r = _get_client()
        val = r.get(_done_count_key(case_id))
        return int(val) if val else 0
    except Exception as e:
        print(f"Redis cache unavailable for get_done_count: {e}")

    # MySQL is authoritative
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT completed_docs FROM cases WHERE id = %s", (case_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else 0
    except Exception as e:
        print(f"MySQL fallback failed for get_done_count: {e}")
        return 0


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
    try:
        r = _get_client()
        key = _docs_status_key(case_id)
        updates_json = json.dumps(fields, ensure_ascii=False)
        r.eval(_SET_DOC_STATUS_LUA, 2, key, doc_id, updates_json)
    except Exception as e:
        print(f"Failed to update doc status in Redis cache: {e}")


# ── Single-case delete ────────────────────────────────────────────────────────────

def delete_case(case_id: str) -> int:
    """Delete all Redis cache keys for a single case. Returns count of keys deleted."""
    try:
        r = _get_client()
        pattern = f"case:{case_id}:*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                r.delete(*keys)
                count += len(keys)
            if cursor == 0:
                break
        return count
    except Exception as e:
        print(f"Failed to delete Redis cache for case {case_id}: {e}")
        return 0


# ── Full flush ────────────────────────────────────────────────────────────────────

def flush_all_cases() -> int:
    """Delete ALL case:* keys from the Redis cache. Returns count of keys deleted."""
    try:
        r = _get_client()
        count = 0
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match="case:*", count=100)
            if keys:
                r.delete(*keys)
                count += len(keys)
            if cursor == 0:
                break
        return count
    except Exception as e:
        print(f"Failed to flush Redis cache: {e}")
        return 0


# ── Reset / cleanup ──────────────────────────────────────────────────────────────

def reset_for_retry(case_id: str) -> None:
    """Reset for a retry run — MySQL status becomes 'processing'; Redis cache cleared."""
    try:
        _mysql_set_case_status(case_id=case_id, status="processing")
    except Exception as e:
        print(f"Failed to update case status in MySQL: {e}")
    try:
        r = _get_client()
        pipe = r.pipeline()
        pipe.delete(_done_count_key(case_id))
        pipe.delete(_results_key(case_id))
        pipe.delete(_errors_key(case_id))
        pipe.delete(_docs_status_key(case_id))
        pipe.hset(_meta_key(case_id), "status", "processing")
        pipe.execute()
    except Exception as e:
        print(f"Failed to reset Redis cache for case {case_id}: {e}")


# ── Full job snapshot (for status endpoint) ──────────────────────────────────────

def get_case_job(case_id: str) -> dict:
    """Return a dict matching the old JOBS[case_id] format for frontend compat.

    Redis is the hot path; on any cache failure this degrades to the
    MySQL-authoritative payload (`case_repo.get_case_status_payload`).
    """
    try:
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
    except Exception:
        pass

    return _mysql_case_payload(case_id)


def add_files_to_case(case_id: str, new_files: list[dict]) -> None:
    try:
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
    except Exception as e:
        print(f"Failed to update Redis cache for case {case_id}: {e}")
