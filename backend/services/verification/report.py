"""The report writer: turns a closed Case File into an advocate-style title report.

The model writes the report (particulars, documents scrutinised with a paragraph on
each, history of title, certificate and opinion) from the Case File: the transfer
records and each examined document's examiner facts, never OCR text. Gates check
that it covers every examined document, invents no document number, names the
present owners, carries no internal ids, and that the opinion agrees with the
records. The application adds the documents still required, the date and what
changed since the previous version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from backend.config import VERIFY_REPORT_CALL_BUDGET
from backend.domain.chain_continuity import name_words
from backend.prompts.loader import load_prompt
from backend.schemas.due_diligence import (
    DueDiligenceReport,
    Opinion,
    RequiredDocument,
    WrittenReport,
)
from backend.services.verification.case_file import (
    SECTIONS,
    CaseFile,
    ExaminerReport,
    section_ok,
    transfer_result,
)
from backend.services.verification.tools import (
    RESULT_WORDS,
    SECTION_WORDS,
    id_problems,
    transfer_name,
)


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
    """At most two short reasons for the page header."""
    problems = []
    if len(written.reasons) > REASONS_MAX:
        problems.append(f"Give at most {REASONS_MAX} reasons, the most important first.")
    problems += [
        f"Reason {index} has {len(reason)} characters; keep it to {REASON_CHARS}."
        for index, reason in enumerate(written.reasons, start=1)
        if len(reason) > REASON_CHARS
    ]
    return problems


def coverage_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """Every examined document is listed once, with one paragraph each, in the same order."""
    listed = [row.doc_id for row in written.documents]
    problems = [
        f"{doc_id} is not a document of this case."
        for doc_id in listed
        if doc_id not in case.documents
    ]
    examined = [doc_id for doc_id, entry in case.documents.items() if entry.examined]
    missing = [doc_id for doc_id in examined if doc_id not in listed]
    if missing:
        problems.append(
            f"List every examined document in documents; missing: {', '.join(missing)}."
        )
    twice = sorted({doc_id for doc_id in listed if listed.count(doc_id) > 1})
    if twice:
        problems.append(f"List each document once; repeated: {', '.join(twice)}.")
    if [detail.doc_id for detail in written.document_details] != listed:
        problems.append(
            "document_details must have one paragraph per listed document, in the same order "
            "as documents."
        )
    return problems


_NOT_ENGLISH = re.compile(r"[\u0c80-\u0cff]")  # Kannada script
_SCAN_WORDS = re.compile(r"\b(?:OCR|garbled)\b", re.IGNORECASE)


def _wording_problems(field: str, text: str) -> list[str]:
    """The report is in English and never talks about the scanning."""
    problems = []
    if _NOT_ENGLISH.search(text):
        snippet = "".join(_NOT_ENGLISH.findall(text))[:20]
        problems.append(
            f"{field} contains Kannada script ({snippet}). Write in English: give the English "
            "form the documents use, or leave it out."
        )
    if _SCAN_WORDS.search(text):
        problems.append(
            f'{field} mentions OCR or garbled text. Say the part "is not legible" instead.'
        )
    return problems


def text_problems(written: WrittenReport) -> list[str]:
    """No internal ids, Kannada script or talk of OCR in any text the reader sees (ids
    belong only in doc_id)."""
    fields = {
        "reasons": written.reasons,
        "title_holders": written.title_holders,
        "property_description": [written.property_description],
        "boundaries": [v for v in written.boundaries.model_dump().values() if v],
        "documents": [row.nature for row in written.documents],
        "document_details": [detail.text for detail in written.document_details],
        "history": written.history,
        "certificate": [written.certificate],
    }
    return [
        problem
        for field, texts in fields.items()
        for t in texts
        for problem in [*id_problems(field, t), *_wording_problems(field, t)]
    ][:6]


def holder_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """The title holders are the acquirers of the last transfer in the chain."""
    if not case.transfers:
        return []
    owners = case.transfers[-1].transaction.transferees
    if not name_words(owners) or name_words(owners) & name_words(written.title_holders):
        return []
    return [
        f"title_holders must be the present owners from the last transfer: {', '.join(owners)}."
    ]


# Document, registration, order and survey numbers: parts joined by "-" or "/", with a digit.
_NUMBER = re.compile(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+")
_DATE = re.compile(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _report_text(report: ExaminerReport) -> str:
    return _squash(
        " ".join([report.summary, *(f"{getattr(f, 'text', '')} {f.quote}" for f in report.facts())])
    )


def number_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """Every document, registration, order or survey number written about a document must
    appear in that document's examiner report: numbers are copied, never made up."""
    problems = []
    for detail in written.document_details:
        entry = case.documents.get(detail.doc_id)
        if entry is None or entry.report is None:
            continue
        known = _report_text(entry.report)
        for token in _NUMBER.findall(detail.text):
            if (
                len(token) >= 5
                and any(char.isdigit() for char in token)
                and not _DATE.fullmatch(token)
                and _squash(token) not in known
            ):
                problems.append(
                    f"{token!r} in the paragraph on {detail.doc_id} is not in that document's "
                    "facts. Copy numbers exactly as the facts give them, or leave them out."
                )
    return problems[:6]


def report_problems(case: CaseFile, written: WrittenReport) -> list[str]:
    """Why the written report does not faithfully reflect the Case File, if it does not."""
    return [
        *opinion_problems(case, written.opinion),
        *length_problems(written),
        *coverage_problems(case, written),
        *text_problems(written),
        *holder_problems(case, written),
        *number_problems(case, written),
    ]


@report_agent.output_validator
def check_written_report(ctx: RunContext[ReportDeps], written: WrittenReport) -> WrittenReport:
    problems = report_problems(ctx.deps.case, written)
    if problems:
        raise ModelRetry("Fix the report:\n- " + "\n- ".join(problems))
    return written


# -- Versioning -----------------------------------------------------------------


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


def required_documents(case: CaseFile) -> list[RequiredDocument]:
    """The annexure: every document still asked of the buyer."""
    return [
        RequiredDocument(document=item.document, reason=item.reason)
        for item in case.requests
        if item.status in ("open", "received")
    ]


def assemble(
    case: CaseFile, written: WrittenReport, version: int, previous: dict | None
) -> DueDiligenceReport:
    """The saved report: what the writer wrote, plus the annexure, the date and the changes."""
    return DueDiligenceReport(
        **written.model_dump(),
        version=version,
        documents_required=required_documents(case),
        prepared_on=date.today(),
        changes=changes(previous or {}, basis(case, written.opinion)),
    )


_FACT_SECTIONS = (
    "instrument", "parties", "schedule", "consideration", "recitals", "encumbrances",
    "restrictions",
)  # fmt: skip


def _document_facts(report: ExaminerReport) -> list[str]:
    lines = [f"    summary: {report.summary}"]
    for section in _FACT_SECTIONS:
        for fact in getattr(report, section):
            if hasattr(fact, "capacity"):
                who = f"{fact.name} ({fact.role}, {fact.capacity}"
                who += f", for {fact.represented_by})" if fact.represented_by else ")"
                lines.append(f"    party: {who}")
            else:
                lines.append(f"    {section} - {fact.topic}: {fact.text}")
    return lines


def report_input(case: CaseFile) -> str:
    """What the writer needs, as text: the transfers and their results, the property today,
    the documents still needed, and each examined document's examiner facts (with its id,
    for the doc_id fields only). No OCR text and no citations."""
    transfers = []
    for transfer in case.window():
        t = transfer.transaction
        result = transfer_result(transfer)
        transfers.append(
            f"- {transfer_name(transfer).capitalize()} ({t.executed_date or t.registration_date or 'undated'}, "
            f"no. {t.transaction_number or 'not stated'}): {', '.join(t.transferors) or '?'} -> "
            f"{', '.join(t.transferees)}. "
            + (f"{RESULT_WORDS[result]}. {transfer.summary}" if result else "not verified")
        )
        if transfer.connects and not transfer.connects.ok:
            transfers.append(f"    break: {transfer.connects.note}")
        transfers += [f"    [{c.severity}] {c.text}" for c in transfer.concerns]
    earlier = [
        f"- {transfer_name(t).capitalize()}: {', '.join(t.transaction.transferors) or '?'} -> "
        f"{', '.join(t.transaction.transferees)} (before the 30-year search)"
        for t in case.transfers
        if case.before_root(t)
    ]
    today = []
    for name in SECTIONS:
        section = case.section(name)
        if section is None:
            today.append(f"- {SECTION_WORDS[name]}: not recorded")
            continue
        today.append(f"- {SECTION_WORDS[name]}: {section.note}")
        today += [f"    [{c.severity}] {c.text}" for c in section.concerns]
    needed = [f"- {item.document}: {item.reason}" for item in required_documents(case)]
    documents = []
    for doc_id, entry in case.documents.items():
        if entry.report is None:
            continue
        documents.append(f"[{doc_id}] {entry.document_type} | {entry.filename}")
        documents += _document_facts(entry.report)
    unreadable = [
        f"- {entry.filename}: {entry.examination_error}"
        for entry in case.documents.values()
        if entry.examination_error
    ]
    owners = case.transfers[-1].transaction.transferees if case.transfers else []
    return "\n".join(
        [
            "Write the Report of Investigation of Title from these results.",
            f"Present owners (last transfer): {', '.join(owners) or 'not known'}",
            "",
            "EARLIER HISTORY",
            *(earlier or ["- none"]),
            "",
            "TRANSFERS VERIFIED (root to present owner)",
            *(transfers or ["- none"]),
            "",
            "THE PROPERTY TODAY",
            *today,
            "",
            "DOCUMENTS STILL NEEDED (listed by the application in an annexure)",
            *(needed or ["- none"]),
            "",
            "DOCUMENTS THAT COULD NOT BE READ",
            *(unreadable or ["- none"]),
            "",
            "DOCUMENTS EXAMINED (id in brackets, then the examiner's facts)",
            *documents,
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
