"""Results endpoints: case documents and the built title chain."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

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
    """Case info, documents, and the built title chain."""
    _enforce_access(case_id, user)
    try:
        return build_case_results(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.post("/results/{case_id}/chain")
async def build_title_chain(case_id: str, user: dict | None = Depends(get_optional_user)):
    """(Re)build the case's title chain."""
    _enforce_access(case_id, user)
    from backend.database.repositories.agent_repo import set_agent_status
    from backend.workers.title_chain_tasks import run_case_analysis_task
    # Mark the build as running before queueing so a poller never mistakes the
    # previous build's "done" for this one's result.
    set_agent_status(case_id=case_id, status="running")
    try:
        run_case_analysis_task.apply_async(args=[case_id], kwargs={"force": True})
    except Exception as error:
        set_agent_status(case_id=case_id, status="error")
        logger.exception("Failed to queue chain build for %s", case_id)
        raise HTTPException(
            status_code=503, detail="Could not queue the title-chain build. Please retry."
        ) from error
    return {"case_id": case_id, "status": "queued"}


@router.get("/results/{case_id}/ocr")
async def get_case_ocr(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Raw OCR full_text for every document in a case (from canonical MySQL storage)."""
    _enforce_access(case_id, user)
    from pathlib import Path

    from backend.database.repositories.document_repo import get_case_documents
    from backend.integrations.storage.file_utils import read_json
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
