"""Verification endpoints: start a run, follow its live feed, read the report,
and upload a document for a requisition. HTTP only; logic is in the service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.database.repositories.case_repo import get_case_owner
from backend.logger import get_logger
from backend.services.auth import get_optional_user
from backend.services.verification import service

router = APIRouter()
logger = get_logger(__name__)


def _enforce_access(case_id: str, user: dict | None) -> None:
    owner = get_case_owner(case_id)
    if owner and (user is None or owner != user["id"]):
        raise HTTPException(status_code=403, detail="Not your case")


@router.post("/verify/{case_id}")
async def start_verification(case_id: str, user: dict | None = Depends(get_optional_user)):
    """Start (or continue) verifying the case's title chain."""
    _enforce_access(case_id, user)
    try:
        return service.start(case_id)
    except service.VerificationBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to queue verification for %s", case_id)
        raise HTTPException(
            status_code=503, detail="Could not queue verification. Please retry."
        ) from error


@router.get("/verify/{case_id}")
async def get_verification(case_id: str, user: dict | None = Depends(get_optional_user)):
    """The Case File summary, the latest run and the latest report."""
    _enforce_access(case_id, user)
    return service.get_state(case_id)


@router.get("/verify/{case_id}/events")
async def get_verification_events(
    case_id: str, after: int = 0, user: dict | None = Depends(get_optional_user)
):
    """Live feed events after the given event id."""
    _enforce_access(case_id, user)
    return {"case_id": case_id, "events": service.list_events(case_id, after)}


@router.post("/verify/{case_id}/requisitions/{requisition_id}/upload")
async def upload_for_requisition(
    case_id: str,
    requisition_id: str,
    file: UploadFile = File(...),
    user: dict | None = Depends(get_optional_user),
):
    """Upload the document a requisition asks for. It is processed, then verified."""
    _enforce_access(case_id, user)
    from backend.routers.cases import add_uploaded_files

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF documents can be uploaded")
    try:
        service.get_open_requisition(case_id, requisition_id)
        if service.is_running(case_id):
            raise service.VerificationBusyError("Verification is running; upload when it finishes.")
    except service.RequisitionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.VerificationBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result = await add_uploaded_files(case_id, [file])
    doc_id = result["files"][0]["doc_id"]
    try:
        service.attach_requisition_document(case_id, requisition_id, doc_id, "manual_upload")
    except (service.RequisitionError, service.VerificationBusyError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {**result, "requisition_id": requisition_id, "doc_id": doc_id}
