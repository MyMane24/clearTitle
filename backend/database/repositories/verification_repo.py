"""
Pipeline log persistence.

Old cross-doc verification / human feedback storage was removed with the
per-document verification layer. Title-chain and verification results live in
`title_chain_repo` and `verification_results_repo`.
"""

from __future__ import annotations

import json

from backend.database.connection import _get_conn


def append_pipeline_log(case_id: str, msg: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pipeline_logs FROM cases WHERE id = %s FOR UPDATE", (case_id,))
        row = cursor.fetchone()
        logs = []
        if row and row[0]:
            try:
                logs = json.loads(row[0])
            except Exception:
                logs = []
        if not isinstance(logs, list):
            logs = []
        logs.append(msg)
        logs = logs[-200:]
        cursor.execute(
            "UPDATE cases SET pipeline_logs = %s WHERE id = %s",
            (json.dumps(logs, ensure_ascii=False), case_id)
        )
        conn.commit()


def get_pipeline_logs(case_id: str) -> list[str]:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pipeline_logs FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                logs = json.loads(row[0])
                if isinstance(logs, list):
                    return logs
            except Exception:
                pass
        return []
