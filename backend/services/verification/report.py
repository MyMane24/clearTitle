"""The report writer: turns a closed Case File into a due diligence report.

The model writes the narrative sections and the opinion from the Case File
alone (no OCR text). The application builds the factual tables (documents
examined, requisitions), checks every reference and the opinion's consistency
with the Case File, and lists what changed since the previous version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from backend.config import VERIFY_REPORT_CALL_BUDGET
from backend.prompts.loader import load_prompt
from backend.schemas.due_diligence import (
    DEFAULT_SECTIONS,
    WRITTEN_SECTION_IDS,
    DueDiligenceReport,
    Opinion,
    Section,
    TableBlock,
    WrittenReport,
)
from backend.services.verification.case_file import CaseFile


@dataclass
class ReportDeps:
    case: CaseFile


report_agent = Agent(
    deps_type=ReportDeps,
    output_type=WrittenReport,
    instructions=load_prompt("verify_report"),
    retries={"output": 4},
    name="report_writer",
)


# -- Gates --------------------------------------------------------------------


def opinion_problems(case: CaseFile, opinion: Opinion) -> list[str]:
    """Why ``opinion`` is inconsistent with the Case File, if it is."""
    defects = [f"high issue {i.id}" for i in case.issues if i.severity == "high"]
    defects += [
        f"defective {link.link_id}"
        for link in case.chain
        if link.verdict and link.verdict.verdict == "defective"
    ]
    defects += [
        f"break before {link.link_id}" for link in case.chain[1:] if not link.continues_previous
    ]
    reservations = [f"medium issue {i.id}" for i in case.issues if i.severity == "medium"]
    reservations += [
        f"{link.link_id} is {link.verdict.verdict if link.verdict else 'unverified'}"
        for link in case.chain
        if not link.verdict or link.verdict.verdict != "verified"
    ]
    reservations += [
        f"requisition {item.id} is open" for item in case.requisitions if item.status != "resolved"
    ]
    reservations += [
        f"{entry.doc_id} was not examined"
        for entry in case.documents.values()
        if entry.examination_error
    ]
    if defects and opinion != "NOT_CLEAR":
        return [f"The opinion must be NOT_CLEAR because of: {', '.join(defects)}."]
    if reservations and opinion == "CLEAR":
        return [f"The opinion cannot be CLEAR because: {', '.join(reservations)}."]
    return []


def report_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """Why the written report does not faithfully reflect the Case File, if it does not."""
    known = case.known_ids() | set(case.documents)
    sections = {section.id: section for section in written.sections}
    problems = [f"Missing section {sid!r}." for sid in WRITTEN_SECTION_IDS if sid not in sections]
    refs = {ref for section in written.sections for ref in section.refs()}
    refs |= {ref for reason in written.opinion_reasons for ref in reason.refs}
    unknown = sorted(refs - known)
    if unknown:
        problems.append(f"Unknown ids in refs: {', '.join(unknown)}. Use Case File ids only.")
    scrutiny = sections.get("transaction_scrutiny")
    if scrutiny is not None:
        missing = [link.link_id for link in case.chain if link.link_id not in scrutiny.refs()]
        if missing:
            problems.append(f"transaction_scrutiny has no finding for: {', '.join(missing)}.")
    red_flags = sections.get("red_flags")
    if red_flags is not None:
        missing = [issue.id for issue in case.issues if issue.id not in red_flags.refs()]
        if missing:
            problems.append(f"red_flags does not cover: {', '.join(missing)}.")
    problems += opinion_problems(case, written.opinion)
    return problems


@report_agent.output_validator
def check_written_report(ctx: RunContext[ReportDeps], written: WrittenReport) -> WrittenReport:
    problems = report_problems(ctx.deps.case, written)
    if problems:
        raise ModelRetry("Fix the report:\n- " + "\n- ".join(problems))
    return written


# -- Built sections and versioning --------------------------------------------


def _documents_section(case: CaseFile) -> Section:
    rows = [
        [
            entry.doc_id,
            entry.document_type,
            entry.filename,
            "Examined in full"
            if entry.examined
            else f"Not examined: {entry.examination_error or 'pending'}",
        ]
        for entry in case.documents.values()
    ]
    return Section(
        id="documents_examined",
        title="Documents examined",
        blocks=[
            TableBlock(
                columns=["Document", "Type", "File", "Status"],
                rows=rows,
                refs=list(case.documents),
            )
        ],
    )


def _requisitions_section(case: CaseFile) -> Section:
    rows = [
        [item.id, item.document, item.reason, ", ".join(item.affects), item.status]
        for item in case.requisitions
    ]
    return Section(
        id="requisitions",
        title="Requisitions",
        blocks=[
            TableBlock(
                columns=["Id", "Document required", "Why", "Affects", "Status"],
                rows=rows or [["-", "No further documents required", "", "", ""]],
                refs=[item.id for item in case.requisitions],
            )
        ],
    )


def basis(case: CaseFile, opinion: str) -> dict:
    """What a report rests on, to compare one version with the next."""
    return {
        "opinion": opinion,
        "links": {
            link.link_id: link.verdict.verdict if link.verdict else None for link in case.chain
        },
        "issues": {issue.id: f"{issue.severity}: {issue.title}" for issue in case.issues},
        "requisitions": {item.id: item.status for item in case.requisitions},
    }


def changes(previous: dict, current: dict) -> list[str]:
    """Plain-language differences between two report bases."""
    if not previous:
        return []
    lines = []
    if previous.get("opinion") != current["opinion"]:
        lines.append(f"Opinion changed from {previous.get('opinion')} to {current['opinion']}.")
    for key, label in (("links", "Transaction"), ("requisitions", "Requisition")):
        before, after = previous.get(key, {}), current[key]
        for item_id, value in after.items():
            if item_id not in before:
                lines.append(f"{label} {item_id} added ({value}).")
            elif before[item_id] != value:
                lines.append(f"{label} {item_id}: {before[item_id]} -> {value}.")
        lines += [f"{label} {item_id} removed." for item_id in before if item_id not in after]
    before_issues, after_issues = previous.get("issues", {}), current["issues"]
    lines += [f"New issue {i}: {t}." for i, t in after_issues.items() if i not in before_issues]
    return lines


def assemble(
    case: CaseFile, written: WrittenReport, version: int, previous: dict | None
) -> DueDiligenceReport:
    """Merge the written sections with the built ones, in the standard order."""
    built = {
        "documents_examined": _documents_section(case),
        "requisitions": _requisitions_section(case),
    }
    by_id = {section.id: section for section in written.sections if section.id not in built}
    ordered = [
        built.get(sid) or by_id.pop(sid)
        for sid, _, _ in DEFAULT_SECTIONS
        if sid in built or sid in by_id
    ]
    current = basis(case, written.opinion)
    return DueDiligenceReport(
        version=version,
        property_summary=written.property_summary,
        opinion=written.opinion,
        opinion_reasons=written.opinion_reasons,
        sections=[*ordered, *by_id.values()],
        changes_since_previous=changes(previous or {}, current),
        basis=current,
    )


def report_input(case: CaseFile) -> str:
    """The Case File in full detail for the writer (summaries, not OCR text)."""
    section_lines = [
        f"- {sid}: {title}. {how}" for sid, title, how in DEFAULT_SECTIONS if how != "built"
    ]
    payload = case.model_dump(
        mode="json",
        exclude={"counters", "tasks", "schema_version", "version"},
    )
    for entry in payload["documents"].values():
        report = entry.pop("report", None)
        entry["examined_summary"] = report["summary"] if report else None
    return "\n".join(
        [
            "Write the due diligence report. Sections, in this order:",
            *section_lines,
            "",
            "CASE FILE (JSON):",
            json.dumps(payload, ensure_ascii=False, indent=1),
        ]
    )


async def write_report(
    case: CaseFile, model, version: int, previous_basis: dict | None, usage=None
) -> DueDiligenceReport:
    result = await report_agent.run(
        report_input(case),
        deps=ReportDeps(case=case),
        model=model,
        usage_limits=UsageLimits(request_limit=VERIFY_REPORT_CALL_BUDGET),
    )
    if usage is not None:
        usage.incr(result.usage)
    return assemble(case, result.output, version, previous_basis)
