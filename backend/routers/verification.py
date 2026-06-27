"""
Verification endpoints (V2): run cross-doc verification, get report, submit feedback.
Per-doc verification happens during structuring — no separate endpoint needed.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.logger import get_logger
from backend.services.mysql_store_v2 import (
    get_case_documents,
    get_cross_doc_verification,
    store_feedback,
)
from backend.services.verification_engine import (
    run_verification,
    submit_human_feedback,
)
from backend.services.redis_store import case_exists as redis_case_exists
from backend.services import vector_store as vs

router = APIRouter()
logger = get_logger(__name__)


class FeedbackItem(BaseModel):
    doc_id: str = ""
    original_flag: str = ""
    human_correction: str = ""
    reason: str = ""
    accepted: bool = True
    finding_type: str = ""
    original_severity: str = ""
    corrected_severity: str = ""


class FeedbackSubmit(BaseModel):
    case_id: str
    feedback: list[FeedbackItem]


# ── Start cross-doc verification ─────────────────────────────────────────

@router.post("/verify/{case_id}")
async def start_verification(case_id: str):
    """Run cross-document verification (per-doc already done during structuring)."""
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    docs = get_case_documents(case_id)
    if not docs:
        raise HTTPException(
            status_code=400,
            detail="No documents found. Complete OCR pipeline first.",
        )

    try:
        report = run_verification(case_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")

    return {
        "case_id": case_id,
        "status": "completed",
        "verdict": report.get("verdict", "UNKNOWN"),
        "total_findings": report.get("summary", {}).get("total_findings", 0),
        "per_doc_findings": report.get("summary", {}).get("per_doc_findings", 0),
        "cross_doc_findings": report.get("summary", {}).get("cross_doc_findings", 0),
        "high_severity": report.get("summary", {}).get("high_severity", 0),
        "findings": report.get("findings", []),
        "documents": report.get("summary", {}).get("documents", []),
        "metadata": report.get("metadata", {}),
    }


# ── Get report ───────────────────────────────────────────────────────────

@router.get("/verify/{case_id}/report")
async def get_verification_report_endpoint(case_id: str):
    """Get the latest verification report for a case (merged per-doc + cross-doc)."""
    report = get_cross_doc_verification(case_id)
    if not report:
        raise HTTPException(status_code=404, detail="No verification report found")

    return {
        "case_id": case_id,
        "status": report["status"],
        "verdict": report.get("verdict"),
        "findings": report.get("findings", []),
        "final_report": report.get("final_report", ""),
        "created_at": report.get("created_at"),
        "updated_at": report.get("updated_at"),
    }


# ── Get per-doc verification notes ───────────────────────────────────────

@router.get("/verify/{case_id}/per-doc")
async def get_per_doc_verification(case_id: str):
    """Get per-document verification notes for all docs in a case."""
    docs = get_case_documents(case_id)
    if not docs:
        raise HTTPException(status_code=404, detail="No documents found")

    result = []
    for doc in docs:
        vn = doc.get("verification_notes", []) or []
        result.append({
            "doc_id": doc["doc_id"],
            "document_type": doc.get("document_type"),
            "filename": doc.get("filename"),
            "verification_notes": vn,
            "input_tokens": doc.get("input_tokens", 0),
            "output_tokens": doc.get("output_tokens", 0),
            "cost_usd": doc.get("cost_usd", 0),
            "latency_ms": doc.get("latency_ms", 0),
            "model_used": doc.get("model_used", ""),
        })

    return {"case_id": case_id, "documents": result}


# ── Submit feedback ──────────────────────────────────────────────────────

@router.post("/verify/{case_id}/feedback")
async def submit_feedback(case_id: str, body: FeedbackSubmit):
    """Submit human review feedback for verification findings."""
    feedback_list = [fb.model_dump() for fb in body.feedback]

    # Store in V2 DB
    try:
        store_feedback(case_id=case_id, feedback_list=feedback_list)
    except Exception as e:
        logger.warning("Failed to store feedback in DB: %s", e)

    # Store in vector DB for learning
    try:
        submit_human_feedback(case_id, feedback_list)
    except Exception as e:
        logger.warning("Failed to store feedback in vector DB: %s", e)

    return {
        "case_id": case_id,
        "feedback_stored": len(feedback_list),
        "message": "Feedback recorded. The system will learn from this correction.",
    }


# ── Vector DB status ─────────────────────────────────────────────────────

@router.get("/verify/learnings/stats")
async def learnings_stats():
    """Get stats about stored learnings in the vector database."""
    try:
        total = vs.count()
        return {"total_learnings": total, "vector_db": "qdrant_in_memory"}
    except Exception as e:
        return {"total_learnings": 0, "vector_db": "not_initialized", "error": str(e)}


# ── Cost dashboard ──────────────────────────────────────────────────────

@router.get("/analytics/cost-dashboard")
async def cost_dashboard(days: int = 7):
    """Get daily cost and quota usage summary for the last N days."""
    from backend.services.mysql_store_v2 import get_daily_cost_summary
    try:
        data = get_daily_cost_summary(days=days)
        return {
            "days": days,
            "records": data,
            "total_cost": round(sum(r["total_cost_usd"] for r in data if r["total_cost_usd"]), 6),
            "total_calls": sum(r["call_count"] for r in data),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/analytics/quota-tracking")
async def quota_tracking():
    """Get current (last 24h) quota consumption by provider/model."""
    from backend.services.mysql_store_v2 import get_quota_tracking
    try:
        return {"records": get_quota_tracking()}
    except Exception as e:
        return {"error": str(e)}


# ── Analytics ────────────────────────────────────────────────────────────

@router.get("/analytics/token-usage")
async def token_usage_analytics(case_id: str | None = None):
    """Get token usage and cost analytics. If case_id provided, return per-doc breakdown."""
    from backend.services.mysql_store_v2 import get_case_documents as v2_get_docs

    docs = v2_get_docs(case_id) if case_id else []
    if not docs:
        return {"case_id": case_id, "documents": [], "total": {}}

    total_in = sum(d.get("input_tokens", 0) for d in docs)
    total_out = sum(d.get("output_tokens", 0) for d in docs)
    total_cost = sum(float(d.get("cost_usd", 0) or 0) for d in docs)
    total_latency = sum(d.get("latency_ms", 0) for d in docs)

    return {
        "case_id": case_id,
        "documents": [{
            "doc_id": d["doc_id"],
            "document_type": d.get("document_type"),
            "input_tokens": d.get("input_tokens", 0),
            "output_tokens": d.get("output_tokens", 0),
            "latency_ms": d.get("latency_ms", 0),
            "cost_usd": float(d.get("cost_usd", 0) or 0),
            "model_used": d.get("model_used", ""),
        } for d in docs],
        "total": {
            "documents": len(docs),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "total_cost_usd": round(total_cost, 6),
            "total_latency_ms": total_latency,
        },
    }
