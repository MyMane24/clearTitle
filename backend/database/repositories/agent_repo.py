"""Persistence for the case title chain and its document navigation aids."""

from __future__ import annotations

import json

from backend.database.connection import _get_conn
from backend.logger import get_logger

logger = get_logger(__name__)


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


# -- documents -----------------------------------------------------------------


def get_agent_documents(case_id: str) -> list[dict]:
    """Return navigation summaries and processing state, never OCR text."""
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT doc_id, filename, document_type, status, summary "
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


def save_phase_a_result(*, case_id: str, result: dict, chain_doc_ids: list[str]) -> None:
    """Persist the title chain and the documents it was built from."""
    from backend.schemas.analysis import phase_a_hash

    identity = result.get("property_identity") or {}
    graph = result.get("title_chain_graph") or ""
    detailed_chain = result.get("title_chain") or []
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains "
            "(case_id, status, property_identity, title_chain_graph, detailed_chain, "
            "phase_a_hash, chain_doc_ids, missing_documents) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status = VALUES(status), "
            "property_identity = VALUES(property_identity), "
            "title_chain_graph = VALUES(title_chain_graph), "
            "detailed_chain = VALUES(detailed_chain), "
            "phase_a_hash = VALUES(phase_a_hash), "
            "chain_doc_ids = VALUES(chain_doc_ids), "
            "missing_documents = VALUES(missing_documents)",
            (
                case_id, "complete", _dump(identity), graph, _dump(detailed_chain),
                phase_a_hash(result), _dump(chain_doc_ids),
                _dump(result.get("missing_documents") or []),
            ),
        )
        conn.commit()


# -- agent status --------------------------------------------------------------


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


def get_agent_result(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT property_identity, title_chain_graph, detailed_chain, chain, phase_a_hash, "
                "chain_doc_ids, missing_documents FROM title_chains WHERE case_id = %s",
                (case_id,),
            )
            row = cursor.fetchone()
        except Exception:
            row = None
    if not row or all(value is None for value in row):
        return None
    property_identity = _load(row[0]) or {}
    title_chain_graph = row[1] or ""
    detailed_chain = _load(row[2]) if len(row) > 2 else None
    legacy_chain = _load(row[3]) if len(row) > 3 else None
    if not detailed_chain and isinstance(legacy_chain, dict):
        # Older title-chain records stored the reconstructed chain directly under
        # `transactions`; adapt it in memory without rewriting or losing the row.
        legacy_transactions = legacy_chain.get("transactions")
        if isinstance(legacy_transactions, list):
            property_identity = property_identity or legacy_chain.get("property_identity") or {}
            title_chain_graph = title_chain_graph or legacy_chain.get("title_story") or ""
            detailed_chain = [
                {
                    "tx_id": item.get("tx_id"),
                    "chain_position": item.get("sequence") or index,
                    "documented_transaction": item,
                    "related_events": [],
                }
                for index, item in enumerate(legacy_transactions, start=1)
                if isinstance(item, dict)
            ]
    return {
        "property_identity": property_identity,
        "title_chain_graph": title_chain_graph,
        "title_chain": detailed_chain or [],
        "phase_a_hash": row[4] if len(row) > 4 else None,
        # None marks a chain saved before its source documents were recorded.
        "chain_doc_ids": _load(row[5]) if len(row) > 5 else None,
        "missing_documents": (_load(row[6]) if len(row) > 6 else None) or [],
    }


def get_persisted_title_chain_entries(case_id: str) -> list[dict]:
    """Strict read of the saved chain for identity reconciliation.

    Unlike ``get_agent_result`` (which swallows database failures so a chain can
    still be displayed), this reader must distinguish a genuinely empty case from
    an unreadable one: it returns ``[]`` only when the row is absent/empty, and
    raises on any failed or corrupt read. The chain save uses it so a failed read
    aborts the save instead of renumbering transaction ids from an unknown state.
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT detailed_chain, chain FROM title_chains WHERE case_id = %s",
            (case_id,),
        )
        row = cursor.fetchone()
    if not row:
        return []
    detailed_chain = _load(row[0]) if row[0] is not None else None
    if isinstance(detailed_chain, list):
        return detailed_chain
    if detailed_chain is not None:
        # An unreadable persisted shape is an unknown state, not an empty one.
        raise ValueError(f"title chain for case {case_id} has an unexpected shape")
    legacy_chain = _load(row[1]) if row[1] is not None else None
    if not isinstance(legacy_chain, dict):
        return []
    # Older title-chain records stored the reconstructed transactions directly
    # under `transactions`; adapt in memory, without rewriting the row.
    legacy_transactions = legacy_chain.get("transactions")
    if isinstance(legacy_transactions, list):
        return [
            {
                "tx_id": item.get("tx_id"),
                "chain_position": item.get("sequence") or index,
                "documented_transaction": item,
                "related_events": [],
            }
            for index, item in enumerate(legacy_transactions, start=1)
            if isinstance(item, dict)
        ]
    return []
