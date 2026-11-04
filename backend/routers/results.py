"""Results endpoints: title chain + verification output."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from backend.database.repositories.case_repo import get_case_owner
from backend.logger import get_logger
from backend.services.auth import get_optional_user
from backend.services.final_report import (
    FinalReportMissing,
    MalformedCaseResultError,
    NoCaseResult,
    ReportSynthesisError,
)
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


@router.get("/results/{case_id}/required-documents/pdf")
async def get_required_documents_pdf(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Download the saved transaction-specific outstanding-document checklist."""
    _enforce_access(case_id, user)
    try:
        from backend.services.report import render_required_documents_pdf
        pdf = render_required_documents_pdf(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    except Exception as e:
        logger.error("Required-documents PDF generation failed for %s: %s", case_id, e)
        raise HTTPException(status_code=500, detail="Could not generate required-documents checklist")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="required-documents-checklist.pdf"'},
    )


@router.post("/results/{case_id}/analyze")
async def trigger_analysis(case_id: str, user: dict | None = Depends(get_optional_user)):
    """(Re)run or resume the ClearTitle verification agent for a case."""
    _enforce_access(case_id, user)
    from backend.workers.title_chain_tasks import run_case_analysis_task
    run_case_analysis_task.apply_async(args=[case_id])
    return {"case_id": case_id, "status": "queued"}


@router.post("/results/{case_id}/agent/skip/{tx_ref}")
async def skip_agent_transaction(case_id: str, tx_ref: str, user: dict | None = Depends(get_optional_user)):
    """Skip a paused transaction (verification incomplete) and continue the agent.
    tx_ref can be either the stable tx_id (e.g. PA-TC-0001) or the 1-based sequence.
    """
    _enforce_access(case_id, user)
    from backend.workers.agent_tasks import skip_cleartitle_transaction_task
    skip_cleartitle_transaction_task.apply_async(args=[case_id, tx_ref])
    return {"case_id": case_id, "status": "queued"}


@router.get("/results/{case_id}/ocr")
async def get_case_ocr(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Raw OCR full_text for every document in a case (from canonical MySQL storage)."""
    _enforce_access(case_id, user)
    from backend.database.repositories.document_repo import get_case_documents
    from backend.integrations.storage.file_utils import read_json
    from pathlib import Path
    documents = get_case_documents(case_id)
    from backend.database.repositories.document_repo import get_document_ocr_text

    result = []
    for d in documents:
        doc_id = d["doc_id"]
        entry = {
            "doc_id": doc_id,
            "doc_index": d.get("doc_index"),
            "filename": d.get("filename"),
            "document_type": d.get("document_type"),
            "status": d.get("status"),
            "total_pages": d.get("page_count"),
            "full_text": "",
            "available": False,
        }
        entry["full_text"] = get_document_ocr_text(case_id, doc_id) or ""
        # Backward-compatible read for cases created before the DB column existed.
        if not entry["full_text"]:
            merged_path = (d.get("file_paths") or {}).get("merged_ocr")
            if merged_path and Path(merged_path).is_file():
                try:
                    merged = read_json(Path(merged_path))
                    entry["full_text"] = merged.get("full_text") or ""
                    entry["total_pages"] = merged.get("total_pages") or entry["total_pages"]
                except Exception as e:
                    logger.warning("Failed to read legacy OCR file for %s/%s: %s", case_id, doc_id, e)
        entry["available"] = bool(entry["full_text"])
        result.append(entry)

    return {"case_id": case_id, "documents": result}


@router.get("/results/{case_id}/final-report")
async def get_final_report_state(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Final-report readiness plus the state of any generated report."""
    _enforce_access(case_id, user)
    try:
        from backend.services.final_report import get_report_state
        return get_report_state(case_id)
    except MalformedCaseResultError:
        raise HTTPException(status_code=400, detail="Case result data is malformed")
    except NoCaseResult:
        raise HTTPException(status_code=404, detail="No verification results for this case yet")


@router.post("/results/{case_id}/final-report/generate")
async def generate_final_report(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Generate the final report after re-checking readiness inside the case lock."""
    _enforce_access(case_id, user)
    try:
        from backend.services import final_report as final_report_service
        from backend.integrations.llm.agent_llm import AgentLLMError
        try:
            outcome = final_report_service.generate_final_report(case_id)
        except (AgentLLMError, ReportSynthesisError) as e:
            logger.error("Final report synthesis failed for %s: %s", case_id, e)
            raise HTTPException(status_code=502, detail="Report generation agent failed")
    except MalformedCaseResultError:
        raise HTTPException(status_code=400, detail="Case result data is malformed")
    except NoCaseResult:
        raise HTTPException(status_code=404, detail="No verification results for this case yet")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Final report generation failed for %s: %s", case_id, e)
        raise HTTPException(status_code=500, detail="Report generation failed")
    if outcome.get("status") == "busy":
        raise HTTPException(status_code=409, detail="A report is already being generated for this case")
    return outcome


@router.get("/results/{case_id}/final-report/pdf")
async def download_final_report(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Serve the persisted report PDF; the generation agent is never triggered here."""
    _enforce_access(case_id, user)
    try:
        from backend.services.final_report import REPORT_FILENAME, stored_pdf_path
        path = stored_pdf_path(case_id)
    except FinalReportMissing as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{REPORT_FILENAME}"'},
    )
