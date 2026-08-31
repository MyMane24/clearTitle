"""Verification results persistence for a case."""

from __future__ import annotations

import json

from backend.database.connection import _get_conn


def save_verification_results(
    *,
    case_id: str,
    status: str,
    verdict: str,
    summary: dict | None = None,
    items: list | None = None,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO verification_results (case_id, status, verdict, summary, items) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status=VALUES(status), verdict=VALUES(verdict), "
            "summary=VALUES(summary), items=VALUES(items)",
            (case_id, status, verdict,
             json.dumps(summary, ensure_ascii=False) if summary is not None else None,
             json.dumps(items, ensure_ascii=False) if items is not None else None),
        )
        conn.commit()


def get_verification_results(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT case_id, status, verdict, summary, items, created_at, updated_at "
            "FROM verification_results WHERE case_id = %s",
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("summary", "items"):
            if result.get(field) and isinstance(result[field], str):
                result[field] = json.loads(result[field])
        return result
