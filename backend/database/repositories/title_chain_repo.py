"""Title-chain persistence for a case."""

from __future__ import annotations

import json

from backend.database.connection import _get_conn


def save_title_chain(
    *,
    case_id: str,
    status: str,
    chain: list | None = None,
    source: dict | None = None,
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains (case_id, status, chain, source) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status=VALUES(status), chain=VALUES(chain), source=VALUES(source)",
            (case_id, status,
             json.dumps(chain, ensure_ascii=False) if chain is not None else None,
             json.dumps(source, ensure_ascii=False) if source is not None else None),
        )
        conn.commit()


def get_title_chain(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT case_id, status, chain, source, created_at, updated_at "
            "FROM title_chains WHERE case_id = %s",
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("chain", "source"):
            if result.get(field) and isinstance(result[field], str):
                result[field] = json.loads(result[field])
        return result
