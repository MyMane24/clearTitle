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
    sale_deed_doc_id: str | None = None,
    ec_doc_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0,
    model_used: str = "",
) -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO title_chains (case_id, status, chain, source, sale_deed_doc_id, ec_doc_id, "
            "input_tokens, output_tokens, latency_ms, cost_usd, model_used) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE status=VALUES(status), chain=VALUES(chain), source=VALUES(source), "
            "sale_deed_doc_id=VALUES(sale_deed_doc_id), ec_doc_id=VALUES(ec_doc_id), "
            "input_tokens=VALUES(input_tokens), output_tokens=VALUES(output_tokens), "
            "latency_ms=VALUES(latency_ms), cost_usd=VALUES(cost_usd), model_used=VALUES(model_used)",
            (case_id, status,
             json.dumps(chain, ensure_ascii=False) if chain is not None else None,
             json.dumps(source, ensure_ascii=False) if source is not None else None,
             sale_deed_doc_id, ec_doc_id,
             input_tokens, output_tokens, latency_ms, cost_usd, model_used),
        )
        conn.commit()


def get_title_chain(case_id: str) -> dict | None:
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT case_id, status, chain, source, sale_deed_doc_id, ec_doc_id, "
            "input_tokens, output_tokens, latency_ms, cost_usd, model_used, created_at, updated_at "
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
