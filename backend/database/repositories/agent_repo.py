"""Persistence for the ClearTitle single-agent workflow.

Authoritative stores (each fact lives in exactly one place):

* ``title_chains``           — Phase A property identity, graph, and detailed chain
* ``findings``               — one verification result per transaction (upserted)
* ``reports``                — final report versions (append-only history)
* ``cases.agent_result``     — legacy result column; not used for Phase A
* ``agent_todos``            — durable transaction-verification checklist
* ``case_memory``            — *only* resume state; never authoritative findings
* ``documents.summary``      — per-document navigation label

There is no second database and no duplicate findings store.
"""

from __future__ import annotations

import json

from backend.database.connection import _get_conn


def _dump(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _load(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


# ── documents ─────────────────────────────────────────────────────────────────


def get_agent_documents(case_id: str) -> list[dict]:
    """Return document ids, citation filenames, and saved summaries for the agent."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, filename, summary "
            "FROM documents WHERE case_id = %s ORDER BY doc_index ASC",
            (case_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_document_metadata(case_id: str, doc_id: str) -> dict | None:
    """Metadata + structured extraction for one document (agent navigation aid)."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, doc_index, filename, document_type, page_count, status, "
            "structured_data, summary FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
    if not row:
        return None
    doc = dict(row)
    doc["structured_data"] = _load(doc.get("structured_data")) or {}
    return doc


def set_document_summary(*, case_id: str, doc_id: str, summary: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET summary = %s WHERE case_id = %s AND doc_id = %s",
            (summary, case_id, doc_id),
        )
        conn.commit()


def get_document_raw_text(case_id: str, doc_id: str) -> str:
    """Read the canonical merged OCR text directly from the database."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT merged_ocr_text FROM documents WHERE case_id = %s AND doc_id = %s",
            (case_id, doc_id),
        )
        row = cursor.fetchone()
    return str(row[0] or "") if row else ""


def save_phase_a_result(*, case_id: str, result: dict) -> None:
    """Persist Phase A in its three authoritative title_chains columns."""
    identity = result.get("property_identity") or {}
    graph = result.get("title_chain_graph") or ""
    detailed_chain = result.get("title_chain") or []
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains "
            "(case_id, status, property_identity, title_chain_graph, detailed_chain) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status = VALUES(status), "
            "property_identity = VALUES(property_identity), "
            "title_chain_graph = VALUES(title_chain_graph), "
            "detailed_chain = VALUES(detailed_chain)",
            (case_id, "complete", _dump(identity), graph, _dump(detailed_chain)),
        )
        conn.commit()


# ── case columns (agent_status / agent_memory / agent_result) ─────────────────


def _update_case_column(*, case_id: str, column: str, value) -> None:
    if column not in ("agent_memory", "agent_result"):
        raise ValueError(f"unexpected column {column}")
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE cases SET {column} = %s WHERE id = %s", (_dump(value), case_id))
        conn.commit()


def _read_case_column(case_id: str, column: str):
    if column not in ("agent_memory", "agent_result"):
        raise ValueError(f"unexpected column {column}")
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {column} FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
    return _load(row[0]) if row else None


# ── case_memory: resume state only (NOT authoritative findings) ───────────────


def save_agent_memory(*, case_id: str, memory: dict) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO case_memory (case_id, memory) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE memory = VALUES(memory)",
            (case_id, _dump(memory)),
        )
        conn.commit()


def get_agent_memory(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT memory FROM case_memory WHERE case_id = %s", (case_id,))
            row = cursor.fetchone()
        except Exception:
            row = None
    if row and row[0] is not None:
        return _load(row[0])
    return _read_case_column(case_id, "agent_memory")


# ── authoritative title chain (title_chains table) ────────────────────────────


def save_title_chain(*, case_id: str, chain: dict, status: str = "complete") -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains (case_id, status, chain) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE chain = VALUES(chain), status = VALUES(status)",
            (case_id, status, _dump(chain)),
        )
        conn.commit()


def get_title_chain(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT chain FROM title_chains WHERE case_id = %s", (case_id,))
            row = cursor.fetchone()
        except Exception:
            row = None
    return _load(row[0]) if row else None


# ── findings: one verification result per transaction (upserted) ──────────────


def save_transaction_result(*, case_id: str, tx_id: str, verification: dict) -> None:
    """Upsert a single transaction's verification result (idempotent)."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM findings WHERE case_id = %s AND tx_id = %s", (case_id, tx_id)
        )
        cursor.execute(
            "INSERT INTO findings (case_id, tx_id, tx_index, status, finding, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                case_id,
                tx_id,
                int(verification.get("sequence") or 0),
                verification.get("status"),
                verification.get("conclusion") or verification.get("finding"),
                _dump(verification),
            ),
        )
        conn.commit()


def get_transaction_result(case_id: str, tx_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT payload FROM findings WHERE case_id = %s AND tx_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (case_id, tx_id),
            )
            row = cursor.fetchone()
        except Exception:
            row = None
    return _load(row[0]) if row else None


def list_transaction_results(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT payload FROM findings WHERE case_id = %s ORDER BY tx_index ASC, id ASC",
                (case_id,),
            )
            rows = cursor.fetchall()
        except Exception:
            rows = []
    return [p for r in rows if (p := _load(r[0]))]


# ── durable TODO checklist (agent_todos table) ────────────────────────────────


def list_todos(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, case_id, tx_id, description, state, required_evidence, updated_at "
                "FROM agent_todos WHERE case_id = %s ORDER BY tx_index ASC, id ASC",
                (case_id,),
            )
            rows = cursor.fetchall()
        except Exception:
            rows = []
    out = []
    for row in rows:
        t = dict(row)
        t["required_evidence"] = _load(t.get("required_evidence")) or []
        t["updated_at"] = str(t.get("updated_at") or "")
        out.append(t)
    return out


def upsert_todo(*, case_id: str, tx_id: str, description: str = "", state: str = "PENDING",
                required_evidence: list[str] | None = None, tx_index: int = 0) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agent_todos (case_id, tx_id, tx_index, description, state, required_evidence) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE description = VALUES(description), "
            "required_evidence = VALUES(required_evidence)",
            (case_id, tx_id, tx_index, description, state, _dump(required_evidence or [])),
        )
        conn.commit()


def set_todo_state(*, case_id: str, tx_id: str, state: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE agent_todos SET state = %s WHERE case_id = %s AND tx_id = %s",
            (state, case_id, tx_id),
        )
        conn.commit()


# ── agent status + final result ───────────────────────────────────────────────


def set_agent_status(*, case_id: str, status: str) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE cases SET agent_status = %s WHERE id = %s", (status, case_id))
        conn.commit()


def get_agent_status(case_id: str) -> str | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_status FROM cases WHERE id = %s", (case_id,))
        row = cursor.fetchone()
    return row[0] if row else None


def save_agent_result(*, case_id: str, result: dict) -> None:
    """Append a final report version + update the read-optimised case column.

    Only called when a *final* report is produced (not on pause), so the
    reports history has one row per completed pass.
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reports (case_id, result) VALUES (%s, %s)",
            (case_id, _dump(result)),
        )
        conn.commit()
    _update_case_column(case_id=case_id, column="agent_result", value=result)


def get_agent_result(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT property_identity, title_chain_graph, detailed_chain "
                "FROM title_chains WHERE case_id = %s",
                (case_id,),
            )
            row = cursor.fetchone()
        except Exception:
            row = None
    if not row or all(value is None for value in row):
        return None
    return {
        "property_identity": _load(row[0]) or {},
        "title_chain_graph": row[1] or "",
        "title_chain": _load(row[2]) or [],
    }


def get_agent_state(case_id: str) -> dict:
    """Return ``{status, memory, result}`` for a case (any may be None)."""
    return {
        "status": get_agent_status(case_id),
        "memory": get_agent_memory(case_id),
        "result": get_agent_result(case_id),
    }
