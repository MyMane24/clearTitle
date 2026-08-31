"""Results endpoints: title chain + verification output."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.database.repositories.case_repo import get_case_owner
from backend.logger import get_logger
from backend.services.auth import get_optional_user
from backend.services.results import build_case_results

router = APIRouter()
logger = get_logger(__name__)


def _enforce_access(case_id: str, user: dict | None) -> None:
    owner = get_case_owner(case_id)
    if owner and (user is None or owner != user["id"]):
        raise HTTPException(status_code=403, detail="Not your case")


@router.get("/results/{case_id}")
async def get_results(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Full results payload: case info, documents, title chain, verification."""
    _enforce_access(case_id, user)
    try:
        return build_case_results(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.get("/results/{case_id}/report/pdf")
async def get_report_pdf(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Download a PDF Title Verification Report for a case."""
    _enforce_access(case_id, user)
    try:
        from backend.services.report import render_report_pdf
        pdf = render_report_pdf(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    except Exception as e:  # pragma: no cover - report rendering must not 500 raw
        logger.error("Report generation failed for %s: %s", case_id, e)
        raise HTTPException(status_code=500, detail="Could not generate report")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="title-report-{case_id}.pdf"'},
    )


@router.post("/results/{case_id}/analyze")
async def trigger_analysis(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Manually (re)run the title-chain + verification pass for a completed case."""
    _enforce_access(case_id, user)
    from backend.workers.title_chain_tasks import build_title_chain_task, verify_case_task
    build_title_chain_task.apply_async(
        args=[case_id], link=verify_case_task.si(case_id)
    )
    return {"case_id": case_id, "status": "queued"}
