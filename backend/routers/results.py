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
    from backend.workers.title_chain_tasks import run_case_analysis_task
    run_case_analysis_task.apply_async(args=[case_id])
    return {"case_id": case_id, "status": "queued"}


@router.post("/results/{case_id}/verify")
async def trigger_verification(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Re-run only the verification pass for a completed case."""
    _enforce_access(case_id, user)
    from backend.workers.title_chain_tasks import run_verification_only_task
    run_verification_only_task.apply_async(args=[case_id])
    return {"case_id": case_id, "status": "queued"}


@router.post("/results/{case_id}/title-chain")
async def trigger_title_chain(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Re-run only the title-chain build for a completed case."""
    _enforce_access(case_id, user)
    from backend.workers.title_chain_tasks import run_title_chain_only_task
    run_title_chain_only_task.apply_async(args=[case_id])
    return {"case_id": case_id, "status": "queued"}


@router.get("/results/{case_id}/ocr")
async def get_case_ocr(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Raw OCR `full_text` for every document in a case (from outputs/<case>/ocr_raw)."""
    _enforce_access(case_id, user)
    from backend.database.repositories.document_repo import get_case_documents
    from backend.integrations.storage.file_utils import BASE_DIR, read_json

    documents = get_case_documents(case_id)
    ocr_dir = BASE_DIR / "outputs" / case_id / "ocr_raw"

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
        merged_path = ocr_dir / f"{doc_id}_merged.json"
        if merged_path.is_file():
            try:
                merged = read_json(merged_path)
                entry["full_text"] = merged.get("full_text") or ""
                entry["total_pages"] = merged.get("total_pages") or entry["total_pages"]
                entry["available"] = bool(entry["full_text"])
            except Exception as e:  # pragma: no cover - corrupt file must not 500
                logger.warning("Failed to read OCR for %s/%s: %s", case_id, doc_id, e)
        result.append(entry)

    return {"case_id": case_id, "documents": result}
