"""Results payload builders for the results endpoint."""

from __future__ import annotations

from backend.database.repositories.document_repo import get_case_documents
from backend.database.repositories.title_chain_repo import get_title_chain
from backend.database.repositories.verification_results_repo import get_verification_results


def _case_row(case_id: str) -> dict:
    from backend.database.connection import _get_conn
    with _get_conn() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, status, total_docs, completed_docs, failed_docs, "
            "verification_status, verdict, created_at, updated_at "
            "FROM cases WHERE id = %s",
            (case_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise KeyError(f"Case {case_id} not found in DB")
    return dict(row)


def build_case_results(case_id: str) -> dict:
    case = _case_row(case_id)
    documents = get_case_documents(case_id)
    title_chain = get_title_chain(case_id)
    verification = get_verification_results(case_id)

    if not title_chain:
        title_chain = {"case_id": case_id, "status": "pending", "chain": []}
    if not isinstance(title_chain.get("chain"), list):
        title_chain["chain"] = []

    if not verification:
        verification = {
            "case_id": case_id,
            "status": "pending",
            "verdict": "N/A",
            "summary": {},
            "items": [],
        }
    if not isinstance(verification.get("items"), list):
        verification["items"] = []

    return {
        "case": {
            "case_id": case["id"],
            "status": case["status"],
            "total_docs": case["total_docs"],
            "completed_docs": case["completed_docs"],
            "failed_docs": case["failed_docs"],
            "verification_status": case.get("verification_status"),
            "verdict": case.get("verdict"),
            "created_at": case.get("created_at"),
            "updated_at": case.get("updated_at"),
        },
        "documents": [
            {
                "doc_id": d["doc_id"],
                "doc_index": d["doc_index"],
                "filename": d["filename"],
                "document_type": d.get("document_type"),
                "status": d.get("status"),
                "page_count": d.get("page_count"),
                "structured": d.get("structured_json") or {},
                "error": d.get("error"),
                "model_used": d.get("model_used"),
                "cost_usd": d.get("cost_usd"),
            }
            for d in documents
        ],
        "title_chain": title_chain,
        "verification": verification,
    }
