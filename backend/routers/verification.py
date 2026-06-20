"""
Verification endpoints: run agentic verification, get report, submit feedback.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.mysql_store import (
    get_verification_report,
    get_case_bundle,
    store_feedback,
    get_training_record,
    list_training_records,
)
from backend.services.verification_engine import (
    run_verification,
    submit_human_feedback,
)
from backend.services.redis_store import case_exists as redis_case_exists
from backend.services import vector_store as vs

router = APIRouter()


class FeedbackItem(BaseModel):
    doc_id: str = ""
    original_flag: str
    human_correction: str
    reason: str = ""
    accepted: bool = True
    finding_type: str = ""


class FeedbackSubmit(BaseModel):
    case_id: str
    feedback: list[FeedbackItem]


# ── Start verification ─────────────────────────────────────────────────────

@router.post("/verify/{case_id}")
async def start_verification(case_id: str):
    """Run the full agentic verification workflow for a case."""
    if not redis_case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    docs = get_case_bundle(case_id)
    if not docs:
        raise HTTPException(
            status_code=400,
            detail="No structured documents available. Complete OCR pipeline first.",
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
        "high_severity": report.get("summary", {}).get("high_severity", 0),
        "findings": report.get("findings", []),
        "documents": report.get("summary", {}).get("documents", []),
    }


# ── Get report ─────────────────────────────────────────────────────────────

@router.get("/verify/{case_id}/report")
async def get_verification_report_endpoint(case_id: str):
    """Get the latest verification report for a case."""
    report = get_verification_report(case_id)
    if not report:
        raise HTTPException(status_code=404, detail="No verification report found")

    return {
        "case_id": case_id,
        "status": report["status"],
        "report": report.get("report_json", {}),
        "created_at": report.get("created_at"),
        "updated_at": report.get("updated_at"),
    }


# ── Submit feedback ────────────────────────────────────────────────────────

@router.post("/verify/{case_id}/feedback")
async def submit_feedback(case_id: str, body: FeedbackSubmit):
    """Submit human review feedback for verification findings."""
    report = get_verification_report(case_id)
    if not report:
        raise HTTPException(status_code=404, detail="No verification report found")

    report_id = report["id"]
    feedback_list = [fb.model_dump() for fb in body.feedback]

    # Store in MySQL
    ids = store_feedback(
        case_id=case_id,
        report_id=report_id,
        feedback_list=feedback_list,
    )

    # Store in vector DB + update report
    try:
        submit_human_feedback(case_id, feedback_list)
    except Exception as e:
        pass  # Non-fatal: learning store may fail independently

    return {
        "case_id": case_id,
        "feedback_stored": len(ids),
        "message": "Feedback recorded. The system will learn from this correction.",
    }


# ── Vector DB status ───────────────────────────────────────────────────────

@router.get("/verify/learnings/stats")
async def learnings_stats():
    """Get stats about stored learnings in the vector database."""
    try:
        total = vs.count()
        return {"total_learnings": total, "vector_db": "qdrant_in_memory"}
    except Exception as e:
        return {"total_learnings": 0, "vector_db": "not_initialized", "error": str(e)}


# ── Training data ──────────────────────────────────────────────────────────

@router.get("/verify/training-data")
async def training_data(limit: int = 50, offset: int = 0):
    """List training records for future fine-tuning."""
    records = list_training_records(limit=limit, offset=offset)
    return {
        "total": len(records),
        "records": records,
    }


@router.get("/verify/training-data/{case_id}")
async def training_data_detail(case_id: str):
    """Get full training record for a case (input + agent output + human feedback)."""
    record = get_training_record(case_id)
    if not record:
        raise HTTPException(status_code=404, detail="No training record found")
    return record
