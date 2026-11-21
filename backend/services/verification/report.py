"""The report writer: turns a closed Case File into a due diligence report.

The model writes only the opinion and one or two reasons, from the Case File
alone (no OCR text). The application builds the findings, checks the opinion
against the Case File, and lists what changed since the previous version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from backend.config import VERIFY_REPORT_CALL_BUDGET
from backend.prompts.loader import load_prompt
from backend.schemas.due_diligence import DueDiligenceReport, Finding, Opinion, WrittenReport
from backend.services.verification.case_file import CaseFile, link_year
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
    window = case.window()
    defects += [
        f"defective {link.link_id}"
        for link in window
        if link.verdict and link.verdict.verdict == "defective"
    ]
    defects += [
        f"break before {link.link_id}" for link in window[1:] if not link.continues_previous
    ]
    reservations = [f"medium issue {i.id}" for i in case.issues if i.severity == "medium"]
    reservations += [
        f"{link.link_id} is {link.verdict.verdict if link.verdict else 'unverified'}"
        for link in window
        if not link.verdict or link.verdict.verdict != "verified"
    ]
    reservations += [
        f"requisition {item.id} is open"
        for item in case.requisitions
        if item.status in ("open", "fulfilled")
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
    return opinion_problems(case, written.opinion) + length_problems(written)


REASONS_MAX, REASON_CHARS = 2, 140


def length_problems(written: WrittenReport) -> list[str]:
    """The buyer's page is one page: at most two short reasons."""
    problems = []
    if len(written.reasons) > REASONS_MAX:
        problems.append(f"Give at most {REASONS_MAX} reasons, the most important first.")
    problems += [
        f"Reason {index} has {len(reason)} characters; keep it to {REASON_CHARS}."
        for index, reason in enumerate(written.reasons, start=1)
        if len(reason) > REASON_CHARS
    ]
    return problems


@report_agent.output_validator
def check_written_report(ctx: RunContext[ReportDeps], written: WrittenReport) -> WrittenReport:
    problems = report_problems(ctx.deps.case, written)
    if problems:
        raise ModelRetry("Fix the report:\n- " + "\n- ".join(problems))
    return written


# -- Findings and versioning ---------------------------------------------------


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
        )
        for issue in case.issues
    ]
    covered = {
        link_id
        for issue in case.issues
        if len(issue.link_ids) <= 3  # a summary naming most of the chain covers nothing
        for link_id in issue.link_ids
    }
    for link in case.chain:
        if link.link_id in covered:
            continue
        if link.verdict and link.verdict.verdict == "defective":
            findings.append(
                Finding(
                    title=f"{_transfer_name(link)} is defective",
                    text=link.verdict.summary,
                    severity="high",
                )
            )
    for index, link in enumerate(case.window()):
        if index and not link.continues_previous and link.link_id not in covered:
            findings.append(
                Finding(
                    title=f"Break in the title chain before the {_transfer_name(link).lower()}",
                    text=link.break_note or "No document shows how ownership passed.",
                    severity="high",
                )
            )
    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(findings, key=lambda finding: order.get(finding.severity or "low", 3))
    return findings + clear_findings(case)


def clear_findings(case: CaseFile) -> list[Finding]:
    """What checked out: the unbroken chain (built from the verdicts) and the Lead's
    cited clear checks. Never claimed for a chain with a break or an unjudged transfer."""
    findings = []
    window = case.window()
    judged = all(
        link.verdict and link.verdict.verdict in ("verified", "verified_with_concerns")
        for link in window
    )
    connected = all(link.continues_previous for link in window[1:])
    if window and judged and connected:
        years = [year for link in window if (year := link_year(link))]
        since = f" from {years[0]}" if years else ""
        count = "one transfer" if len(window) == 1 else f"{len(window)} transfers"
        findings.append(
            Finding(
                title="Chain of title is unbroken",
                text=f"Ownership traces{since} through {count} to the current owner; each "
                "seller is the buyer in the transfer before.",
                severity="clear",
            )
        )
    findings += [
        Finding(title=check.title, text=check.detail, severity="clear")
        for check in case.clear_checks
    ]
    return findings


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
        elif old_status != status and status == "withdrawn":
            lines.append(f"No longer needed: {document}.")
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
    """The saved report: the writer's opinion and reasons, the built findings and changes."""
    return DueDiligenceReport(
        version=version,
        opinion=written.opinion,
        reasons=written.reasons,
        findings=case_issues(case),
        changes=changes(previous or {}, basis(case, written.opinion)),
    )


def report_input(case: CaseFile) -> str:
    """What the writer needs for the opinion and its reasons, in words, without ids.

    Each transfer's verdict and summary, the breaks, the issues, the documents still
    needed and the unreadable documents. Nothing else: no checks, citations or
    examiner reports.
    """
    window = case.window()
    transfers = []
    for index, link in enumerate(window):
        if index and not link.continues_previous:
            transfers.append(f"- BREAK before {transfer_name(link)}: {link.break_note or 'no note'}")
        verdict = link.verdict
        transfers.append(
            f"- {transfer_name(link).capitalize()}: "
            + (f"{VERDICT_WORDS[verdict.verdict]}. {verdict.summary}" if verdict else "no verdict")
        )
    issues = [f"- [{issue.severity}] {issue.title}: {issue.detail}" for issue in case.issues]
    needed = [
        f"- {item.document}: {item.reason}"
        for item in case.requisitions
        if item.status in ("open", "fulfilled")
    ]
    unreadable = [
        f"- {entry.filename}: {entry.examination_error}"
        for entry in case.documents.values()
        if entry.examination_error
    ]
    passed = [f"- {check.title}" for check in case.clear_checks]
    return "\n".join(
        [
            "Write the opinion and one or two reasons.",
            "",
            "TRANSFERS (root to current owner)",
            *(transfers or ["- none"]),
            "",
            "ISSUES",
            *(issues or ["- none"]),
            "",
            "DOCUMENTS STILL NEEDED",
            *(needed or ["- none"]),
            "",
            "DOCUMENTS THAT COULD NOT BE READ",
            *(unreadable or ["- none"]),
            "",
            "CHECKS THAT PASSED",
            *(passed or ["- none"]),
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
