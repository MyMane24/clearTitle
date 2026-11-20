"""The report writer: turns a closed Case File into a due diligence report.

The model writes the narrative sections and the opinion from the Case File
alone (no OCR text). The application builds the factual tables (documents
examined, requisitions), checks every reference and the opinion's consistency
with the Case File, and lists what changed since the previous version.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from backend.config import VERIFY_REPORT_CALL_BUDGET
from backend.prompts.loader import load_prompt
from backend.schemas.due_diligence import (
    DEFAULT_SECTIONS,
    WRITTEN_SECTION_IDS,
    DueDiligenceReport,
    Finding,
    FindingsBlock,
    Opinion,
    ParagraphBlock,
    Section,
    TableBlock,
    WrittenReport,
)
from backend.services.verification.case_file import CaseFile
from backend.services.verification.tools import VERDICT_WORDS, transfer_name


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
    problems += opinion_problems(case, written.opinion)
    return problems


@report_agent.output_validator
def check_written_report(ctx: RunContext[ReportDeps], written: WrittenReport) -> WrittenReport:
    problems = report_problems(ctx.deps.case, written)
    if problems:
        raise ModelRetry("Fix the report:\n- " + "\n- ".join(problems))
    return written


# -- Built sections and versioning --------------------------------------------


def _transfer_name(link) -> str:
    match = re.search(
        r"(19|20)\d{2}", link.transaction.executed_date or link.transaction.registration_date or ""
    )
    year = f" of {match.group(0)}" if match else ""
    kind = link.transaction.transaction_type.replace("_", " ")
    return f"{kind}{year}"


def case_issues(case: CaseFile) -> list[Finding]:
    """Every problem a buyer must know about, most serious first.

    Recorded issues, plus defects and breaks in the chain that no recorded
    issue already covers, so nothing serious is left out of the report.
    """
    findings = [
        Finding(
            title=issue.title,
            text=issue.detail,
            severity=issue.severity,
            refs=[issue.id, *issue.link_ids],
        )
        for issue in case.issues
    ]
    covered = {link_id for issue in case.issues for link_id in issue.link_ids}
    for link in case.chain:
        if link.link_id in covered:
            continue
        if link.verdict and link.verdict.verdict == "defective":
            findings.append(
                Finding(
                    title=f"{_transfer_name(link)} is defective",
                    text=link.verdict.summary,
                    severity="high",
                    refs=[link.link_id],
                )
            )
    for index, link in enumerate(case.chain):
        if index and not link.continues_previous and link.link_id not in covered:
            findings.append(
                Finding(
                    title=f"Break in the title chain before the {_transfer_name(link).lower()}",
                    text=link.break_note or "No document shows how ownership passed.",
                    severity="high",
                    refs=[link.link_id],
                )
            )
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda finding: order.get(finding.severity or "low", 3))


def _issues_section(case: CaseFile) -> Section:
    items = case_issues(case)
    blocks = (
        [FindingsBlock(items=items)]
        if items
        else [ParagraphBlock(text="No issues were found in the documents examined.")]
    )
    return Section(id="issues", title="Issues identified", blocks=blocks)


def _requisitions_section(case: CaseFile) -> Section:
    rows = [[item.document, item.reason, item.status] for item in case.requisitions]
    return Section(
        id="requisitions",
        title="Documents needed",
        blocks=[
            TableBlock(
                columns=["Document needed", "Why it is needed", "Status"],
                rows=rows or [["No further documents are needed", "", ""]],
                refs=[item.id for item in case.requisitions],
            )
        ],
    )


OPINION_WORDS = {
    "CLEAR": "clear",
    "CLEAR_SUBJECT_TO": "clear subject to conditions",
    "NOT_CLEAR": "not clear",
}


def basis(case: CaseFile, opinion: str) -> dict:
    """What a report rests on, with readable names, to compare one version with the next."""
    return {
        "opinion": opinion,
        "links": {
            link.link_id: {
                "name": transfer_name(link),
                "verdict": link.verdict.verdict if link.verdict else None,
            }
            for link in case.chain
        },
        "issues": {issue.id: issue.title for issue in case.issues},
        "requisitions": {
            item.id: {"document": item.document, "status": item.status}
            for item in case.requisitions
        },
    }


def _entry(value, key: str, fallback: str):
    """Read a basis entry; reports saved before readable names stored bare values."""
    return value.get(key, fallback) if isinstance(value, dict) else fallback


def _verdict_words(verdict) -> str:
    return VERDICT_WORDS.get(verdict, "not yet judged") if verdict else "not yet judged"


def changes(previous: dict, current: dict) -> list[str]:
    """Plain-language differences between two report versions, without internal ids."""
    if not previous:
        return []
    lines = []
    if previous.get("opinion") != current["opinion"]:
        before = OPINION_WORDS.get(previous.get("opinion"), "unknown")
        lines.append(f"The opinion changed from {before} to {OPINION_WORDS[current['opinion']]}.")
    old_links, new_links = previous.get("links", {}), current["links"]
    for link_id, value in new_links.items():
        name = value["name"].capitalize()
        verdict = value["verdict"]
        if link_id not in old_links:
            lines.append(f"{name} was added to the title chain ({_verdict_words(verdict)}).")
            continue
        old = old_links[link_id]
        old_verdict = old.get("verdict") if isinstance(old, dict) else old
        if old_verdict != verdict:
            lines.append(
                f"{name}: now {_verdict_words(verdict)} (before: {_verdict_words(old_verdict)})."
            )
    for link_id, old in old_links.items():
        if link_id not in new_links:
            name = _entry(old, "name", "a transfer")
            lines.append(f"{name.capitalize()} was removed from the title chain.")
    old_reqs, new_reqs = previous.get("requisitions", {}), current["requisitions"]
    for req_id, value in new_reqs.items():
        document, status = value["document"], value["status"]
        old_status = _entry(old_reqs.get(req_id), "status", old_reqs.get(req_id))
        if req_id not in old_reqs:
            lines.append(f"A new document is needed: {document}.")
        elif old_status != status and status == "resolved":
            lines.append(f"Received and accepted: {document}.")
        elif old_status != status and status == "open":
            lines.append(f"Still needed after review: {document}.")
    old_issues = previous.get("issues", {})
    lines += [
        f"New issue: {title}."
        for issue_id, title in current["issues"].items()
        if issue_id not in old_issues
    ]
    return lines


def assemble(
    case: CaseFile, written: WrittenReport, version: int, previous: dict | None
) -> DueDiligenceReport:
    """Merge the written sections with the built ones, in the standard order."""
    built = {
        "issues": _issues_section(case),
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
            "Write the due diligence report: property_summary, opinion, opinion_reasons, and "
            "only these sections (issues and documents needed are added by the application):",
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
