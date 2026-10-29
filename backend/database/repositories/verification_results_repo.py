"""Compatibility adapter that translates legacy seed checks into v3.0 results."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.database.connection import _get_conn
from backend.services.agent_schemas import SCHEMA_VERSION, normalize_status, validate_transaction_verification


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
        cursor.execute("SELECT case_result FROM case_results WHERE case_id = %s FOR UPDATE", (case_id,))
        row = cursor.fetchone()
        try:
            result = json.loads(row[0]) if row and isinstance(row[0], str) else (row[0] if row else {})
        except (TypeError, ValueError):
            result = {}
        result = result if isinstance(result, list) else []
        for index, item in enumerate(items or [], start=1):
            tx_id = f"LEGACY-CHECK-{index:04d}"
            result[:] = [entry for entry in result if entry.get("tx_id") != tx_id]
            result_status = normalize_status(item.get("status") or status)
            if result_status == "ISSUES_IDENTIFIED":
                # These historical checks have no stored document/page citations,
                # so they cannot substantiate an identified issue under schema 3.0.
                result_status = "INCONCLUSIVE"
            terminal = result_status in {
                "VERIFIED_WITH_AVAILABLE_EVIDENCE", "INCONCLUSIVE",
            }
            result.append(validate_transaction_verification({
                "tx_id": tx_id,
                "sequence": index,
                "status": result_status,
                "report": (
                    f"## Conclusion\n\nLegacy verification check for "
                    f"{item.get('field') or 'recorded field'}: "
                    f"{item.get('notes') or 'No check details were recorded.'}"
                ),
                "cited_documents": [],
                "required_documents": [],
                "reviewed_document_ids": [],
                "verified_at": datetime.now(timezone.utc).isoformat() if terminal else None,
                "schema_version": SCHEMA_VERSION,
                "transaction_metadata": {"field": item.get("field"), "values": {
                    "structured": item.get("sd_value"), "encumbrance": item.get("ec_value"),
                    "khata": item.get("khata_value"),
                }},
            }).model_dump())
        result.sort(key=lambda entry: entry.get("sequence", 0))
        cursor.execute(
            "INSERT INTO case_results (case_id, case_result) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE case_result = VALUES(case_result)",
            (case_id, json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
