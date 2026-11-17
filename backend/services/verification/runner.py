"""The run manager: drives one verification run from start to report.

A run loads (or starts) the Case File, lets the Lead work through
``agent.iter()``, records every step in the live feed, saves the Case File
after every step, and writes a new report version once the closure gate
passes. A crashed or budget-limited run leaves a saved Case File, so the next
run continues from it instead of starting over. The runner contains no legal
knowledge: that lives in prompts and skills.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage

from backend.config import (
    VERIFY_EXAMINER_MODEL,
    VERIFY_LEAD_CALL_BUDGET,
    VERIFY_LEAD_MODEL,
    VERIFY_REPORT_MODEL,
)
from backend.logger import get_logger
from backend.services.verification import case_file as cf
from backend.services.verification.agents import lead_agent
from backend.services.verification.context import render_case_file
from backend.services.verification.deps import TextCache, VerifyDeps
from backend.services.verification.events import record_node
from backend.services.verification.report import write_report
from backend.services.verification.store import Store

logger = get_logger(__name__)

DONE, INCOMPLETE, ERROR = "done", "incomplete", "error"


@dataclass
class Models:
    """The model for each role. Tests pass FunctionModels here."""

    lead: object
    examiner: object
    report: object


def default_models() -> Models:
    from backend.integrations.llm.agent_models import build_agent_model

    return Models(
        lead=build_agent_model(VERIFY_LEAD_MODEL),
        examiner=build_agent_model(VERIFY_EXAMINER_MODEL),
        report=build_agent_model(VERIFY_REPORT_MODEL),
    )


def prepare_case_file(store: Store, case_id: str) -> tuple[cf.CaseFile, int, list[str]] | None:
    """Load the Case File (fresh if the title chain changed) and add new documents.

    Returns ``(case, version, notes)``, or None when there is no title chain to verify.
    """
    phase_a = store.phase_a(case_id)
    if not phase_a or not phase_a.get("title_chain"):
        return None
    documents = store.documents(case_id)
    loaded = store.load_case_file(case_id)
    if loaded and loaded[0].phase_a_hash == phase_a.get("phase_a_hash"):
        case, version = loaded
    else:
        case = cf.from_phase_a(case_id, phase_a, documents)
        version = loaded[1] if loaded else 0
        if loaded:
            _carry_over_examinations(store, loaded[0], case)
    return case, version, sync_documents(case, documents)


def _carry_over_examinations(store: Store, old: cf.CaseFile, new: cf.CaseFile) -> None:
    """Keep examiner reports from a reset Case File when the document text is unchanged."""
    for doc_id, entry in new.documents.items():
        previous = old.documents.get(doc_id)
        if not (previous and previous.examined and previous.report and previous.text_hash):
            continue
        if cf.text_hash(store.text(new.case_id, doc_id)) == previous.text_hash:
            entry.examined, entry.report = True, previous.report
            entry.text_hash = previous.text_hash


def sync_documents(case: cf.CaseFile, documents: list[dict]) -> list[str]:
    """Add newly processed documents and settle requisitions whose upload failed.

    Returns notes describing what changed.
    """
    notes = []
    for entry in case.documents.values():
        if entry.examination_error:  # retry documents an earlier run could not examine
            entry.examination_error = None
    structured = {doc["doc_id"]: doc for doc in documents if doc.get("status") == "structured"}
    for doc_id, doc in structured.items():
        if doc_id not in case.documents:
            case.documents[doc_id] = cf.DocumentEntry(
                doc_id=doc_id,
                filename=str(doc.get("filename") or ""),
                document_type=str(doc.get("document_type") or ""),
                summary=doc.get("summary"),
            )
            notes.append(f"New document {doc_id} ({doc.get('document_type')}).")
    for item in case.requisitions:
        if item.status == "fulfilled" and item.doc_id not in structured:
            notes.append(f"The document uploaded for {item.id} could not be processed.")
            item.status, item.doc_id = "open", None
    return notes


def task_prompt(case: cf.CaseFile, deps: VerifyDeps, kind: str, notes: list[str]) -> str:
    arrived = [item for item in case.requisitions if item.status == "fulfilled"]
    if kind == "incremental" and arrived:
        lines = [
            "New documents have arrived for these requisitions. Examine each new document, "
            "decide with review_requisition whether it settles the requisition, update every "
            "link, lead and issue it affects, then close. Do not re-examine unchanged documents.",
            *(f"- {item.id}: {item.document} -> document {item.doc_id}" for item in arrived),
        ]
    else:
        lines = [
            "Verify the title chain of this case. Continue from the Case File below: "
            "documents already examined keep their saved reports."
        ]
    if notes:
        lines += ["", "Changes since the last run:", *(f"- {note}" for note in notes)]
    return "\n".join([*lines, "", render_case_file(case, deps.gate_context)])


async def run(case_id: str, *, store: Store, models: Models, kind: str = "full") -> dict:
    """Run verification for a case and return ``{status, run_id, ...}``."""
    prepared = prepare_case_file(store, case_id)
    if prepared is None:
        return {"case_id": case_id, "status": ERROR, "reason": "build the title chain first"}
    case, version, notes = prepared
    run_id = str(uuid.uuid4())
    store.create_run(run_id, case_id, kind)
    emit = store.sink(case_id, run_id)
    deps = VerifyDeps(
        case=case,
        text_of=TextCache(lambda doc_id: store.text(case_id, doc_id)),
        emit=emit,
        examiner_model=models.examiner,
    )
    version = store.save_case_file(case, version)
    agent_run = None
    status, error, result = ERROR, None, {}
    emit("run", f"Verification started ({kind})", run_id)
    try:
        async with lead_agent.iter(
            task_prompt(case, deps, kind, notes),
            deps=deps,
            model=models.lead,
            usage_limits=UsageLimits(request_limit=VERIFY_LEAD_CALL_BUDGET),
        ) as agent_run:
            async for node in agent_run:
                record_node(node, emit)
                version = store.save_case_file(case, version)
            closing = agent_run.result.output.summary
        emit("run", "All checks closed. Writing the due diligence report.", run_id)
        previous = store.latest_report(case_id)
        report = await write_report(
            case,
            models.report,
            version=(previous.version + 1) if previous else 1,
            previous_basis=previous.basis if previous else None,
            usage=deps.sub_usage,
        )
        store.save_report(case_id, report)
        emit("report", f"Report v{report.version}: {report.opinion.replace('_', ' ')}", run_id)
        status, result = DONE, {"report_version": report.version, "summary": closing}
    except UsageLimitExceeded as exc:
        status, error = INCOMPLETE, f"model-call budget reached: {exc}"
        emit("run", "Stopped: the model-call budget was reached. Run again to continue.", run_id)
    except Exception as exc:
        logger.exception("verification_failed case_id=%s run_id=%s", case_id, run_id)
        status, error = ERROR, f"{type(exc).__name__}: {exc}"
        emit("run", "Verification failed. Progress is saved; run again to continue.", run_id)
    finally:
        try:
            store.save_case_file(case, version)
        except Exception:
            logger.exception("case_file_save_failed case_id=%s", case_id)
        lead_usage = agent_run.usage if agent_run is not None else RunUsage()
        usage = {
            "lead_requests": lead_usage.requests,
            "sub_requests": deps.sub_usage.requests,
            "input_tokens": lead_usage.input_tokens + deps.sub_usage.input_tokens,
            "output_tokens": lead_usage.output_tokens + deps.sub_usage.output_tokens,
        }
        store.finish_run(run_id, status, usage, error)
    return {"case_id": case_id, "run_id": run_id, "status": status, "error": error, **result}
