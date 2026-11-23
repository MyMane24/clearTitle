"""The report writer: turns a closed Case File into a due diligence report.

The model writes only the opinion and one or two reasons, from the Case File
alone (no OCR text). The application builds the findings from the transfer
records and the property today, checks the opinion against them, and lists what
changed since the previous version.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from backend.config import VERIFY_REPORT_CALL_BUDGET
from backend.prompts.loader import load_prompt
from backend.schemas.due_diligence import DueDiligenceReport, Finding, Opinion, WrittenReport
from backend.services.verification.case_file import (
    SECTIONS,
    CaseFile,
    section_ok,
    transfer_result,
    transfer_year,
)
from backend.services.verification.tools import RESULT_WORDS, SECTION_WORDS, transfer_name


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


def _missing(documents) -> bool:
    return any(doc.status == "missing" for doc in documents)


# -- Gates --------------------------------------------------------------------


def opinion_problems(case: CaseFile, opinion: Opinion) -> list[str]:
    """Why ``opinion`` is inconsistent with the Case File, if it is."""
    window = case.window()
    defects = [
        f"{transfer_name(t)} is defective" for t in window if transfer_result(t) == "defective"
    ]
    reservations = [
        f"{transfer_name(t)} is {RESULT_WORDS.get(transfer_result(t) or '', 'not verified')}"
        for t in window
        if transfer_result(t) != "verified"
    ]
    for name in SECTIONS:
        section = case.section(name)
        if section is None:
            reservations.append(f"{SECTION_WORDS[name].lower()} were not recorded")
            continue
        if any(c.severity == "high" for c in section.concerns):
            defects.append(f"a high concern in {SECTION_WORDS[name].lower()}")
        if not section_ok(section):
            reservations.append(f"{SECTION_WORDS[name].lower()} are not in order")
    reservations += [
        f"{entry.filename} could not be read"
        for entry in case.documents.values()
        if entry.examination_error
    ]
    if defects and opinion != "NOT_CLEAR":
        return [f"The opinion must be NOT_CLEAR because {'; '.join(defects)}."]
    if reservations and opinion == "CLEAR":
        return [f"The opinion cannot be CLEAR because {'; '.join(reservations)}."]
    return []


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


def report_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """Why the written report does not faithfully reflect the Case File, if it does not."""
    return opinion_problems(case, written.opinion) + length_problems(written)


@report_agent.output_validator
def check_written_report(ctx: RunContext[ReportDeps], written: WrittenReport) -> WrittenReport:
    problems = report_problems(ctx.deps.case, written)
    if problems:
        raise ModelRetry("Fix the report:\n- " + "\n- ".join(problems))
    return written


# -- Findings and versioning ---------------------------------------------------


_ORDER = {"high": 0, "medium": 1, "low": 2}


def case_issues(case: CaseFile) -> list[Finding]:
    """Every problem a buyer must know about, most serious first, then what checked out.

    Each transfer's breaks and concerns, titled by the transfer, and each concern in
    the property today, titled by its section.
    """
    findings = []
    for transfer in case.window():
        title = transfer_name(transfer).removeprefix("the ").capitalize()
        if transfer.connects and not transfer.connects.ok:
            findings.append(
                Finding(
                    title=f"Break in the title chain before the {title.lower()}",
                    text=transfer.connects.note,
                    severity="medium" if _missing(transfer.documents) else "high",
                )
            )
        findings += [
            Finding(title=title, text=concern.text, severity=concern.severity)
            for concern in transfer.concerns
        ]
    for name in SECTIONS:
        section = case.section(name)
        findings += [
            Finding(title=SECTION_WORDS[name], text=concern.text, severity=concern.severity)
            for concern in (section.concerns if section else [])
        ]
    findings.sort(key=lambda finding: _ORDER.get(finding.severity or "low", 3))
    return findings + clear_findings(case)


def clear_findings(case: CaseFile) -> list[Finding]:
    """What checked out: the unbroken chain, built from the records. Never claimed for a
    chain with a break, a defect, a missing document or an unverified transfer."""
    window = case.window()
    proven = all(transfer_result(t) in ("verified", "verified_with_concerns") for t in window)
    connected = all(t.connects is None or t.connects.ok for t in window)
    if not (window and proven and connected):
        return []
    years = [year for t in window if (year := transfer_year(t))]
    since = f" from {years[0]}" if years else ""
    count = "one transfer" if len(window) == 1 else f"{len(window)} transfers"
    return [
        Finding(
            title="Chain of title is unbroken",
            text=f"Ownership traces{since} through {count} to the current owner; each "
            "seller is the buyer in the transfer before.",
            severity="clear",
        )
    ]


OPINION_WORDS = {
    "CLEAR": "clear",
    "CLEAR_SUBJECT_TO": "clear subject to conditions",
    "NOT_CLEAR": "not clear",
}


def basis(case: CaseFile, opinion: str) -> dict:
    """What a report rests on, with readable names, to compare one version with the next."""
    concerns = [c.text for t in case.transfers for c in t.concerns]
    concerns += [c.text for name in SECTIONS if (s := case.section(name)) for c in s.concerns]
    return {
        "opinion": opinion,
        "links": {
            t.id: {"name": transfer_name(t), "verdict": transfer_result(t)} for t in case.transfers
        },
        "concerns": concerns,
        "requisitions": {
            item.id: {"document": item.document, "status": item.status} for item in case.requests
        },
    }


def _entry(value, key: str, fallback: str):
    """Read a basis entry; reports saved before readable names stored bare values."""
    return value.get(key, fallback) if isinstance(value, dict) else fallback


def _result_words(result) -> str:
    return RESULT_WORDS.get(result, "not yet judged") if result else "not yet judged"


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
        name, result = value["name"].capitalize(), value["verdict"]
        if link_id not in old_links:
            lines.append(f"{name} was added to the title chain ({_result_words(result)}).")
            continue
        old = old_links[link_id]
        old_result = old.get("verdict") if isinstance(old, dict) else old
        if _result_words(old_result) != _result_words(result):
            lines.append(
                f"{name}: now {_result_words(result)} (before: {_result_words(old_result)})."
            )
    for link_id, old in old_links.items():
        if link_id not in new_links:
            lines.append(
                f"{_entry(old, 'name', 'a transfer').capitalize()} was removed from the title chain."
            )
    old_reqs, new_reqs = previous.get("requisitions", {}), current["requisitions"]
    for req_id, value in new_reqs.items():
        document, status = value["document"], value["status"]
        old_status = _entry(old_reqs.get(req_id), "status", old_reqs.get(req_id))
        if req_id not in old_reqs:
            lines.append(f"A new document is needed: {document}.")
        elif old_status != status and status in ("settled", "resolved"):
            lines.append(f"Received and accepted: {document}.")
        elif old_status != status and status == "open":
            lines.append(f"Still needed after review: {document}.")
    for req_id, old in old_reqs.items():
        if req_id not in new_reqs and _entry(old, "status", "") in (
            "open",
            "fulfilled",
            "received",
        ):
            lines.append(f"No longer needed: {_entry(old, 'document', 'a document')}.")
    old_concerns = set(previous.get("concerns") or previous.get("issues", {}).values())
    lines += [f"New concern: {text}" for text in current["concerns"] if text not in old_concerns]
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

    Each transfer's result, summary, break and concerns; the property today; the
    documents still needed and the unreadable documents. No citations or examiner
    reports.
    """
    transfers = []
    for transfer in case.window():
        result = transfer_result(transfer)
        transfers.append(
            f"- {transfer_name(transfer).capitalize()}: "
            + (f"{RESULT_WORDS[result]}. {transfer.summary}" if result else "not verified")
        )
        if transfer.connects and not transfer.connects.ok:
            transfers.append(f"    break: {transfer.connects.note}")
        transfers += [f"    [{c.severity}] {c.text}" for c in transfer.concerns]
    today = []
    for name in SECTIONS:
        section = case.section(name)
        if section is None:
            today.append(f"- {SECTION_WORDS[name]}: not recorded")
            continue
        today.append(f"- {SECTION_WORDS[name]}: {section.note}")
        today += [f"    [{c.severity}] {c.text}" for c in section.concerns]
    needed = [
        f"- {item.document}: {item.reason}"
        for item in case.requests
        if item.status in ("open", "received")
    ]
    unreadable = [
        f"- {entry.filename}: {entry.examination_error}"
        for entry in case.documents.values()
        if entry.examination_error
    ]
    return "\n".join(
        [
            "Write the opinion and one or two reasons.",
            "",
            "TRANSFERS (root to current owner)",
            *(transfers or ["- none"]),
            "",
            "THE PROPERTY TODAY",
            *today,
            "",
            "DOCUMENTS STILL NEEDED",
            *(needed or ["- none"]),
            "",
            "DOCUMENTS THAT COULD NOT BE READ",
            *(unreadable or ["- none"]),
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
