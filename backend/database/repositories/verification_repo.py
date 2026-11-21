"""
Pipeline logs and verification agent storage.

The verification agent keeps one Case File per case, a row per run, a live
event feed and versioned due diligence reports. Title chains live in `agent_repo`.
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
            (json.dumps(logs, ensure_ascii=False), case_id),
        )
        conn.commit()


def get_pipeline_logs(case_id: str) -> list[str]:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pipeline_logs FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
    if not row or not row[0]:
        return []
    try:
        logs = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return []
    return logs if isinstance(logs, list) else []


# -- verification agent --------------------------------------------------------


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


class StaleCaseFileError(RuntimeError):
    """The Case File was saved by someone else since it was loaded."""


def get_case_file(case_id: str) -> tuple[dict, int] | None:
    """The stored Case File JSON and its version, or None when there is none."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT data, version FROM verification_case_files WHERE case_id = %s", (case_id,)
        )
        row = cursor.fetchone()
    if not row:
        return None
    return _load(row[0]), int(row[1])


def save_case_file(case_id: str, data: dict, expected_version: int) -> int:
    """Save the Case File if nobody saved it since ``expected_version``.

    Returns:
        The new version.

    Raises:
        StaleCaseFileError: Another writer saved a newer version first.
    """
    new_version = expected_version + 1
    with _get_conn() as conn:
        cursor = conn.cursor()
        if expected_version == 0:
            cursor.execute(
                "INSERT IGNORE INTO verification_case_files (case_id, version, data) "
                "VALUES (%s, %s, %s)",
                (case_id, new_version, _dump(data)),
            )
        else:
            cursor.execute(
                "UPDATE verification_case_files SET data = %s, version = %s "
                "WHERE case_id = %s AND version = %s",
                (_dump(data), new_version, case_id, expected_version),
            )
        if cursor.rowcount != 1:
            conn.rollback()
            raise StaleCaseFileError(
                f"case file for {case_id} changed since version {expected_version}"
            )
        conn.commit()
    return new_version


def create_run(run_id: str, case_id: str, kind: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO verification_runs (id, case_id, kind, status) VALUES (%s, %s, %s, %s)",
            (run_id, case_id, kind, "running"),
        )
        conn.commit()


def finish_run(
    run_id: str, status: str, usage: dict | None = None, error: str | None = None
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE verification_runs SET status = %s, usage_json = %s, error = %s, "
            "finished_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, _dump(usage) if usage is not None else None, error, run_id),
        )
        conn.commit()


def get_latest_run(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, case_id, kind, status, usage_json, error, started_at, finished_at "
            "FROM verification_runs WHERE case_id = %s ORDER BY started_at DESC, id DESC LIMIT 1",
            (case_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    run = dict(row)
    run["usage"] = _load(run.pop("usage_json"))
    return run


def append_event(case_id: str, run_id: str, kind: str, text: str, ref: str | None = None) -> int:
    """Add one step to the live feed and return its id."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO verification_events (case_id, run_id, kind, text, ref) "
            "VALUES (%s, %s, %s, %s, %s)",
            (case_id, run_id, kind, text[:4000], ref),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_events(case_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
    """Feed events after ``after_id``, oldest first."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, run_id, kind, text, ref, created_at FROM verification_events "
            "WHERE case_id = %s AND id > %s ORDER BY id ASC LIMIT %s",
            (case_id, after_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def save_report(case_id: str, version: int, opinion: str, report: dict) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO due_diligence_reports (case_id, version, opinion, report) "
            "VALUES (%s, %s, %s, %s)",
            (case_id, version, opinion, _dump(report)),
        )
        conn.commit()


def get_latest_report(case_id: str) -> dict | None:
    """The newest report: ``{version, opinion, report, created_at}``."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT version, opinion, report, created_at FROM due_diligence_reports "
            "WHERE case_id = %s ORDER BY version DESC LIMIT 1",
            (case_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    result = dict(row)
    result["report"] = _load(result["report"])
    return result
