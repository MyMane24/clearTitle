"""Results payload builders for the results endpoint."""

from __future__ import annotations

from backend.database.repositories.document_repo import get_case_documents


def classification_action_message(document: dict) -> str:
    document_type = document.get("document_type") or "unknown document"
    label = document_type.replace("_", " ").lower()
    reason = (document.get("error") or "").strip()
    if not reason:
        reason = f"This appears to be a {label}, not a property or title document."
    return f"{reason} Replace it with a property document or continue without it."


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


def _agent_block(case_id: str) -> dict:
    from backend.database.repositories.agent_repo import get_agent_state
    state = get_agent_state(case_id)
    memory = state.get("memory") or {}
    result = state.get("result") or {}
    # Return the agent's saved deliverable without rebuilding or translating its
    # fields for the UI. Status is orchestration metadata, not part of the result.
    return {
        **result,
        "status": state.get("status") or ("done" if result else "idle"),
        "stage": memory.get("stage"),
    }


def build_case_results(case_id: str) -> dict:
    case = _case_row(case_id)
    documents = get_case_documents(case_id)

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
        "needs_action": _needs_action(case_id),
        "agent": _agent_block(case_id),
    }


def _needs_action(case_id: str) -> list[dict]:
    from backend.database.repositories.document_repo import get_classification_failed_documents
    actions = []
    for doc in get_classification_failed_documents(case_id):
        document_type = doc.get("document_type") or "unknown document"
        actions.append({
            "doc_id": doc["doc_id"],
            "filename": doc["filename"],
            "document_type": document_type,
            "message": classification_action_message(doc),
            "choices": [
                {"action": "skip", "method": "POST",
                 "url": f"/api/case/{case_id}/doc/{doc['doc_id']}/skip",
                 "label": "Continue without this document"},
                {"action": "replace", "method": "POST",
                 "url": f"/api/case/{case_id}/doc/{doc['doc_id']}/replace",
                 "label": "Upload a replacement document"},
            ],
        })
    return actions
