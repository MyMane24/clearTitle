"""The verification agent's public interface. Routers and workers call only this.

* ``start(case_id, kind)``: queue a run (full, or incremental after uploads).
* ``get_state(case_id)``: the Case File summary, the latest run and the latest report.
* ``list_events(case_id, after)``: the live feed.
* ``report_pdf(case_id)``: the latest report as a PDF.
* ``attach_requisition_document``: link an uploaded document to its request.
* ``owns_chain`` / ``after_documents_processed``: hooks for the document pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.database.repositories import verification_repo as repo
from backend.logger import get_logger
from backend.schemas.due_diligence import DueDiligenceReport
from backend.services.verification import case_file as cf
from backend.services.verification.store import DbStore

logger = get_logger(__name__)

RUNNING = "running"
# A run row still "running" after Celery's hard time limit belongs to a killed worker.
_STALE_AFTER = timedelta(seconds=7500)


class VerificationBusyError(RuntimeError):
    """A verification run is in progress for this case."""


class RequisitionError(ValueError):
    """The request does not exist or cannot take a document now."""


def start(case_id: str, kind: str = "full", fresh: bool = False) -> dict:
    """Queue a verification run. Raises if one is already running.

    ``fresh`` throws away the saved Case File and examines every document again.
    """
    if is_running(case_id):
        raise VerificationBusyError("Verification is already running for this case.")
    from backend.workers.verification_tasks import run_verification_task

    run_verification_task.apply_async(args=[case_id], kwargs={"kind": kind, "fresh": fresh})
    return {"case_id": case_id, "status": "queued", "kind": kind, "fresh": fresh}


def is_running(case_id: str) -> bool:
    """True while a run is in progress. A run older than the task time limit is stale."""
    latest = repo.get_latest_run(case_id)
    if not latest or latest["status"] != RUNNING:
        return False
    started = latest.get("started_at")
    if isinstance(started, datetime):
        return datetime.now() - started < _STALE_AFTER
    return True


def get_state(case_id: str) -> dict:
    """Everything the dashboard shows about verification for this case."""
    stored = repo.get_case_file(case_id)
    latest_run = repo.get_latest_run(case_id)
    report = repo.get_latest_report(case_id)
    case = cf.load(stored[0]) if stored else None
    return {
        "case_id": case_id,
        "run": _run_view(latest_run),
        "case_file": _case_view(case) if case else None,
        "report": (
            DueDiligenceReport.model_validate(report["report"]).model_dump(mode="json")
            if report
            else None
        ),
    }


def report_pdf(case_id: str) -> bytes | None:
    """The latest report as PDF bytes, or None when the case has no report yet."""
    from backend.services.verification.report_pdf import render_pdf

    report = repo.get_latest_report(case_id)
    return render_pdf(DueDiligenceReport.model_validate(report["report"])) if report else None


def list_events(case_id: str, after: int = 0) -> list[dict]:
    return [
        {
            "id": event["id"],
            "run_id": event["run_id"],
            "kind": event["kind"],
            "text": event["text"],
            "ref": event["ref"],
            "created_at": str(event["created_at"]),
        }
        for event in repo.list_events(case_id, after)
    ]


def get_open_requisition(case_id: str, requisition_id: str) -> dict:
    """The document request as a dict, if it exists and is open for a document."""
    stored = repo.get_case_file(case_id)
    case = cf.load(stored[0]) if stored else None
    request = case.request(requisition_id) if case else None
    if request is None:
        raise RequisitionError(f"No document request {requisition_id}.")
    if request.status != "open":
        raise RequisitionError(f"Document request {requisition_id} is {request.status}.")
    return request.model_dump()


def attach_requisition_document(
    case_id: str, requisition_id: str, doc_id: str, source: str
) -> None:
    """Record that a document arrived for a request (verified after processing)."""
    if is_running(case_id):
        raise VerificationBusyError("Verification is running; upload when it finishes.")
    store = DbStore()
    loaded = store.load_case_file(case_id)
    if loaded is None:
        raise RequisitionError("This case has no verification yet.")
    case, version = loaded
    request = case.request(requisition_id)
    if request is None or request.status != "open":
        raise RequisitionError(f"Document request {requisition_id} is not open.")
    request.status, request.doc_id, request.source = "received", doc_id, source
    store.save_case_file(case, version)


def owns_chain(case_id: str) -> bool:
    """True once verification has started: it then maintains the working chain.

    New uploads are verified incrementally instead of triggering an automatic
    title-chain rebuild, which would discard verification progress.
    """
    try:
        return repo.get_case_file(case_id) is not None
    except Exception:
        logger.exception("verification_owns_chain_check_failed case_id=%s", case_id)
        return False


def after_documents_processed(case_id: str) -> bool:
    """Queue an incremental run when documents arrived for requests.

    Returns True when a run was queued.
    """
    stored = repo.get_case_file(case_id)
    if not stored:
        return False
    case = cf.load(stored[0])
    if not any(item.status == "received" for item in case.requests):
        return False
    try:
        start(case_id, kind="incremental")
    except VerificationBusyError:
        return False
    return True


def _run_view(run: dict | None) -> dict | None:
    if not run:
        return None
    return {
        "id": run["id"],
        "kind": run["kind"],
        "status": run["status"],
        "error": run["error"],
        "usage": run["usage"],
        "started_at": str(run["started_at"]),
        "finished_at": str(run["finished_at"]) if run["finished_at"] else None,
    }


def _case_view(case: cf.CaseFile) -> dict:
    """The Case File for the dashboard: each transfer with its worked-out result and
    whether it is before the root, each section with whether it is in order, and
    documents without examiner report bodies."""
    data = case.model_dump(mode="json", exclude={"counters", "report_basis", "set_aside"})
    for transfer, view in zip(case.transfers, data["transfers"], strict=True):
        view["result"] = cf.transfer_result(transfer)
        view["before_root"] = case.before_root(transfer)
    for name in cf.SECTIONS:
        if data["property_today"][name] is not None:
            data["property_today"][name]["ok"] = cf.section_ok(case.section(name))
    for entry in data["documents"].values():
        report = entry.pop("report", None)
        entry["examined_summary"] = report["summary"] if report else None
    return data
