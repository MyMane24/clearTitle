"""
Case-level persistence operations.

Extracted verbatim from `backend/services/mysql_store.py` (case operations).
"""

from __future__ import annotations

import json

from backend.database.connection import _get_conn


def init_case(*, case_id: str, total_docs: int, user_id: str | None = None) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cases (id, user_id, status, total_docs) VALUES (%s, %s, 'uploaded', %s) "
            "ON DUPLICATE KEY UPDATE status='uploaded', total_docs=VALUES(total_docs), "
            "completed_docs=0, failed_docs=0",
            (case_id, user_id, total_docs),
        )
        conn.commit()


def update_case_status(*, case_id: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cases SET
                completed_docs = (SELECT COUNT(*) FROM documents
                    WHERE case_id = %s AND status = 'structured'),
                failed_docs = (SELECT COUNT(*) FROM documents
                    WHERE case_id = %s AND status IN ('failed','classification_failed')),
                status = CASE
                    WHEN (SELECT COUNT(*) FROM documents
                        WHERE case_id = %s AND status IN ('failed','classification_failed')) > 0
                    THEN 'partial'
                    WHEN (SELECT COUNT(*) FROM documents
                        WHERE case_id = %s AND status = 'structured') = total_docs
                    THEN 'complete'
                    ELSE 'processing'
                END
            WHERE id = %s
        """, (case_id, case_id, case_id, case_id, case_id))
        conn.commit()


def set_case_status(*, case_id: str, status: str) -> None:
    """Direct case-status write (Phase 3: MySQL is the source of truth).

    Used for transient states (e.g. 'processing', 'failed') that are set when a
    pipeline starts/aborts; final status transitions still go through
    `update_case_status` / `recompute_case_status`.
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cases SET status = %s WHERE id = %s",
            (status, case_id),
        )
        conn.commit()


def upload_docs_reset(*, case_id: str, new_total: int) -> None:
    """Bump total_docs and invalidate title-chain/verification when more docs are uploaded."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cases SET total_docs = %s, status = 'uploaded', "
            "verification_status = NULL, verdict = NULL WHERE id = %s",
            (new_total, case_id)
        )
        cursor.execute("DELETE FROM title_chains WHERE case_id = %s", (case_id,))
        cursor.execute("DELETE FROM verification_results WHERE case_id = %s", (case_id,))
        conn.commit()


def list_cases(user_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        if user_id:
            cursor.execute(
                "SELECT id, status, total_docs, completed_docs, failed_docs, "
                "verification_status, verdict, created_at, updated_at "
                "FROM cases WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (user_id, limit, offset),
            )
        else:
            cursor.execute(
                "SELECT id, status, total_docs, completed_docs, failed_docs, "
                "verification_status, verdict, created_at, updated_at "
                "FROM cases ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
        return [dict(row) for row in cursor.fetchall()]


def get_case_owner(case_id: str) -> str | None:
    """Return the user_id that owns a case, or None."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def set_case_owner(*, case_id: str, user_id: str) -> bool:
    """Attach an anonymous case (user_id IS NULL) to a user.

    Returns True if the case was linked, False if it was already owned
    (or did not exist).
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cases SET user_id = %s WHERE id = %s AND user_id IS NULL",
            (user_id, case_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def set_case_verification_status(*, case_id: str, verification_status: str, verdict: str) -> None:
    """Record the outcome of the title-chain + verification pass."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cases SET verification_status = %s, verdict = %s WHERE id = %s",
            (verification_status, verdict, case_id),
        )
        conn.commit()


def recompute_case_status(case_id: str) -> None:
    update_case_status(case_id=case_id)


def delete_case(case_id: str) -> None:
    """Delete all records for a single case from database."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in (
            "title_chains",
            "verification_results",
            "documents",
        ):
            try:
                cursor.execute(f"DELETE FROM {table} WHERE case_id = %s", (case_id,))
            except Exception:
                pass
        try:
            cursor.execute("DELETE FROM cases WHERE id = %s", (case_id,))
        except Exception:
            pass
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()


def get_case_status_payload(case_id: str) -> dict:
    with _get_conn() as conn:
        # 1. Fetch case info
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT status, total_docs, completed_docs, failed_docs, "
            "verification_status, verdict, pipeline_logs "
            "FROM cases WHERE id = %s",
            (case_id,)
        )
        case_row = cursor.fetchone()
        if not case_row:
            raise KeyError(f"Case {case_id} not found in DB")

        # 2. Fetch documents
        cursor.execute(
            "SELECT doc_id, filename, document_type, status, structured_data, file_paths, error, "
            "page_count, input_tokens, output_tokens, latency_ms, cost_usd, model_used "
            "FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,)
        )
        doc_rows = cursor.fetchall()

    # Reconstruct log list
    logs = []
    if case_row.get("pipeline_logs"):
        try:
            logs = json.loads(case_row["pipeline_logs"])
        except Exception:
            pass

    # Reconstruct files list
    files = []
    results = []
    errors = []

    for d in doc_rows:
        file_paths = {}
        if d.get("file_paths"):
            try:
                file_paths = json.loads(d["file_paths"])
            except Exception:
                pass

        # files element
        files.append({
            "doc_id": d["doc_id"],
            "original_name": d["filename"],
            "saved_path": file_paths.get("raw")
        })

        # results element (only if status is structured)
        if d["status"] == "structured":
            structured_data = {}
            if d.get("structured_data"):
                try:
                    structured_data = json.loads(d["structured_data"])
                except Exception:
                    pass

            doc_type = d.get("document_type") or ""
            safe_type = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in doc_type.upper())
            results.append({
                "doc_id": d["doc_id"],
                "filename": d["filename"],
                "doc_type": doc_type,
                "status": "complete",
                "structured": structured_data,
                "result_file": f"{d['doc_id']}_{safe_type}.json",
                "total_pages": d["page_count"],
                "chunks_used": 1,  # derived placeholder
                "input_tokens": d["input_tokens"],
                "output_tokens": d["output_tokens"],
                "cost_usd": float(d["cost_usd"]),
                "latency_ms": d["latency_ms"],
                "model_used": d["model_used"],
                "provider": "gemini" if "gemini" in (d["model_used"] or "").lower() else "groq"
            })

        # errors element (if failed or classification_failed)
        if d["status"] in ("failed", "classification_failed"):
            action_required = None
            if d["status"] == "classification_failed":
                action_required = "replace_or_skip"
            errors.append({
                "doc_id": d["doc_id"],
                "step": "classify" if d["status"] == "classification_failed" else "pipeline",
                "error": d["error"],
                "action_required": action_required
            })

    # Calculate progress
    total = case_row["total_docs"]
    done = case_row["completed_docs"] + case_row["failed_docs"]
    case_status = case_row["status"]

    if total > 0:
        progress = min(100, int((done / total) * 90)) if case_status == "processing" else 100
    else:
        progress = 0

    return {
        "case_id": case_id,
        "status": case_status,
        "completed_docs": case_row["completed_docs"],
        "total_docs": case_row["total_docs"],
        "failed_docs": case_row["failed_docs"],
        "verification_status": case_row.get("verification_status"),
        "verdict": case_row.get("verdict"),
        "files": files,
        "results": results,
        "errors": errors,
        "progress": progress,
        "log": logs
    }
