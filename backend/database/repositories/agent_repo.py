"""Persistence for case-level title-chain verification results and memory."""

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


def is_terminal_transaction_result(result: dict, documents: list[dict] | None = None) -> bool:
    """True when a verification result is complete and not merely checkpointed.

    Moved here from services.cleartitle_agent so the dossier logic consults one
    single terminal-state rule.
    """
    from backend.services.agent_schemas import normalize_status

    status = normalize_status(result.get("status"))
    metadata = result.get("transaction_metadata") or {}
    checkpoint = metadata.get("_verification_checkpoint")
    if checkpoint in {"bounded_stop", "repeated_tool_call"}:
        return False
    if status == "INCONCLUSIVE" and documents is not None:
        prior_manifest = metadata.get("_document_manifest")
        current_manifest = {
            str(document["doc_id"]): str(document.get("status") or "unknown")
            for document in documents
        }
        if isinstance(prior_manifest, dict) and prior_manifest != current_manifest:
            return False
    return status in {
        "VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE",
    }


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


def save_phase_a_result(*, case_id: str, result: dict) -> None:
    """Persist Phase A in its three authoritative title_chains columns."""
    from backend.schemas.analysis import phase_a_hash

    identity = result.get("property_identity") or {}
    graph = result.get("title_chain_graph") or ""
    detailed_chain = result.get("title_chain") or []
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains "
            "(case_id, status, property_identity, title_chain_graph, detailed_chain, phase_a_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status = VALUES(status), "
            "property_identity = VALUES(property_identity), "
            "title_chain_graph = VALUES(title_chain_graph), "
            "detailed_chain = VALUES(detailed_chain), "
            "phase_a_hash = VALUES(phase_a_hash)",
            (case_id, "complete", _dump(identity), graph, _dump(detailed_chain), phase_a_hash(result)),
        )
        conn.commit()


# -- case columns (agent_status / agent_memory / agent_result) -----------------


# -- case_memory: concise human-readable text, with parseable checkpoint labels -


def save_agent_memory(*, case_id: str, memory: dict) -> None:
    checkpoint = {
        "case_id": case_id,
        "current_tx_id": memory.get("current_tx_id") or memory.get("paused_transaction"),
        "current_stage": memory.get("current_stage") or memory.get("stage"),
        "status": memory.get("status") or memory.get("last_transaction_status"),
        "paused_transaction": memory.get("paused_transaction") or (
            memory.get("current_tx_id")
            if (memory.get("current_stage") or memory.get("stage")) == "paused"
            and (memory.get("status") or memory.get("last_transaction_status")) == "PENDING_NOT_VERIFIED"
            else None
        ),
        "result_ref": memory.get("result_ref") or memory.get("current_tx_id") or memory.get("paused_transaction"),
        "next_action": memory.get("next_action"),
        "updated_at": memory.get("updated_at"),
        "evidence_retry_tx_id": memory.get("evidence_retry_tx_id"),
    }
    checkpoint = {key: value for key, value in checkpoint.items() if value is not None}
    skipped_tx_ids = sorted(set(memory.get("skipped_tx_ids") or []))
    if skipped_tx_ids:
        checkpoint["skipped_tx_ids"] = skipped_tx_ids
    text = _dump(checkpoint)
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO case_memory (case_id, case_memory) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE case_memory = VALUES(case_memory)",
            (case_id, text),
        )
        conn.commit()


def get_agent_memory(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT case_memory FROM case_memory WHERE case_id = %s", (case_id,))
            row = cursor.fetchone()
        except Exception:
            row = None
    if not row or not row[0]:
        return {}
    text = str(row[0])
    try:
        saved = json.loads(text)
        if isinstance(saved, dict) and saved.get("case_id"):
            if (
                not saved.get("paused_transaction")
                and saved.get("current_stage") == "paused"
                and saved.get("status") == "PENDING_NOT_VERIFIED"
            ):
                saved["paused_transaction"] = saved.get("current_tx_id")
            return saved
    except (TypeError, ValueError):
        pass
    # Backward-compatible reader for the former labeled-text checkpoint.
    result = {"memory_text": text, "case_id": case_id}
    for line in text.splitlines():
        if line.startswith("Progress: "):
            result["stage"] = line.removeprefix("Progress: ")
            result["current_stage"] = result["stage"]
        elif line.startswith("Current transaction: "):
            result["current_tx_id"] = line.removeprefix("Current transaction: ")
            result["result_ref"] = result["current_tx_id"]
        elif line.startswith("Paused transaction: "):
            result["paused_transaction"] = line.removeprefix("Paused transaction: ")
        elif line.startswith("Next action: "):
            result["next_action"] = line.removeprefix("Next action: ")
        elif line.startswith("Completed transactions: "):
            result["completed_tx_ids"] = line.removeprefix("Completed transactions: ").split(", ")
        elif line.startswith("Pending transactions: "):
            result["pending_tx_ids"] = line.removeprefix("Pending transactions: ").split(", ")
        elif line.startswith("Skipped this run: "):
            result["skipped_tx_ids"] = line.removeprefix("Skipped this run: ").split(", ")
        elif line.startswith("Last transaction: "):
            tx_id, _, status = line.removeprefix("Last transaction: ").partition(" — ")
            result["last_transaction_id"] = tx_id
            result["last_transaction_status"] = status
            result["status"] = status
        elif line.startswith("Missing document: "):
            name, _, reason = line.removeprefix("Missing document: ").partition(" — ")
            result.setdefault("missing_documents", []).append({"document_type": name, "reason": reason})
    return result


# -- authoritative title chain (title_chains table) ----------------------------


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


# -- case_results: one row per case; transaction results append/update in JSON --


def _case_result(case_id: str) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT case_result FROM case_results WHERE case_id = %s", (case_id,))
        row = cursor.fetchone()
    value = _load(row[0]) if row else None
    if isinstance(value, list):
        return value
    if isinstance(value, dict):  # tolerate pre-change case_result payloads
        return value.get("transactions") or []
    return []


def save_transaction_result(*, case_id: str, tx_id: str, verification: dict) -> None:
    """Validate and upsert one canonical transaction result in the case row."""
    from backend.services.agent_schemas import validate_transaction_verification

    canonical = validate_transaction_verification(verification).model_dump()
    if canonical["tx_id"] != tx_id:
        raise ValueError("transaction result tx_id does not match persistence key")
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT case_result FROM case_results WHERE case_id = %s FOR UPDATE",
            (case_id,),
        )
        row = cursor.fetchone()
        state = _load(row[0]) if row else None
        transactions = state if isinstance(state, list) else (
            state.get("transactions", []) if isinstance(state, dict) else []
        )
        transactions[:] = [item for item in transactions if item.get("tx_id") != tx_id]
        transactions.append(canonical)
        transactions.sort(key=lambda item: int(item.get("sequence") or 0))
        cursor.execute(
            "INSERT INTO case_results (case_id, case_result) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE case_result = VALUES(case_result)",
            (case_id, _dump(transactions)),
        )
        conn.commit()


def get_transaction_result(case_id: str, tx_id: str) -> dict | None:
    return next((item for item in _case_result(case_id)
                 if item.get("tx_id") == tx_id), None)


def list_transaction_results(case_id: str) -> list[dict]:
    return _case_result(case_id)


def list_persisted_transaction_results(case_id: str) -> list[dict]:
    """Strict read of the persisted transaction results (dossier registry).

    ``_case_result`` tolerates failed or corrupt reads by degrading to ``[]``
    — safe for report readers, but identity allocation must distinguish a
    genuinely empty case from an unreadable one: numbering finding ids from an
    empty registry could reissue an id another dossier already carries. This
    reader raises on a failed database read, corrupt JSON, or an unexpected
    payload shape, and returns ``[]`` only for an absent/empty row.
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT case_result FROM case_results WHERE case_id = %s",
            (case_id,),
        )
        row = cursor.fetchone()
    raw = row[0] if row else None
    if raw is None:
        return []
    if isinstance(raw, (dict, list)):
        value = raw
    else:
        try:
            value = json.loads(raw)
        except Exception as error:
            raise ValueError(
                f"case transaction results for case {case_id} are unreadable: {error}"
            ) from error
    if value is None:  # persisted JSON null — a genuinely empty registry
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):  # tolerate pre-change case_result payloads
        transactions = value.get("transactions")
        if transactions is None:
            return []
        if isinstance(transactions, list):
            return transactions
    raise ValueError(f"case transaction results for case {case_id} have an unexpected shape")


# -- agent status + final result -----------------------------------------------


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
                "SELECT property_identity, title_chain_graph, detailed_chain, chain, phase_a_hash "
                "FROM title_chains WHERE case_id = %s",
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
    }


def get_persisted_title_chain_entries(case_id: str) -> list[dict]:
    """Strict read of the persisted Phase A chain for identity reconciliation.

    Unlike ``get_agent_result`` (which swallows database failures to keep report
    reads working), this reader must distinguish a genuinely empty case from an
    unreadable one: it returns ``[]`` only when the row is absent/empty, and
    raises on any failed or corrupt read. The Phase A save uses it so a failed
    read aborts the save instead of renumbering transaction ids from an
    unknown state.
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


def get_agent_state(case_id: str) -> dict:
    """Return ``{status, memory, result}`` for a case (any may be None)."""
    return {
        "status": get_agent_status(case_id),
        "memory": get_agent_memory(case_id),
        "result": get_agent_result(case_id),
        "case_result": _case_result(case_id),
    }
