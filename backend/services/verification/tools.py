"""The Lead Examiner's tools, grouped into toolsets.

Every tool that changes the Case File checks its input with the gates first.
A failed check becomes a ``ModelRetry`` telling the model what to fix, and the
Case File is left unchanged. To add a capability, add a tool to a toolset here
(or a new toolset) and register it in ``LEAD_TOOLSETS``.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from backend.schemas.chain import DocumentedTransaction, SourceRef
from backend.services.verification.case_file import (
    CheckResult,
    Citation,
    Issue,
    Lead,
    LinkVerdict,
    LinkVerdictKind,
    Requisition,
    Severity,
    WorkingLink,
)
from backend.services.verification.context import render_case_file
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.gates import (
    chain_problems,
    citation_problems,
    is_deed_type,
    link_evidence_problems,
    unexamined_link_sources,
)
from backend.services.verification.pages import normalize, split_pages

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EvidenceStatus = Literal["corroborated", "register_reported", "deed_reported", "recital_reported"]

_MAX_PAGES_PER_READ = 8
_TOOL_RETRIES = 5


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewTransfer(_Input):
    """A transfer to insert into the chain. Sources are taken from the citations."""

    transaction_type: Text = Field(description="Sale, Gift, Partition, Succession, ...")
    transaction_number: str | None = None
    executed_date: str | None = None
    registration_date: str | None = None
    transferors: list[Text] = Field(default_factory=list)
    transferees: list[Text] = Field(min_length=1)
    property_schedule: str | None = None
    survey_number: str | None = None
    consideration: str | None = None
    summary_points: list[Text] = Field(min_length=1)
    evidence_status: EvidenceStatus
    continues_previous: bool


class LinkCorrection(_Input):
    """Fields to change on a link. Leave a field out to keep it."""

    transaction_type: str | None = None
    transaction_number: str | None = None
    executed_date: str | None = None
    registration_date: str | None = None
    transferors: list[Text] | None = None
    transferees: list[Text] | None = None
    property_schedule: str | None = None
    survey_number: str | None = None
    consideration: str | None = None
    evidence_status: EvidenceStatus | None = None
    continues_previous: bool | None = None


# -- helpers ------------------------------------------------------------------


def _require(problems: list[str]) -> None:
    if problems:
        raise ModelRetry("Not saved. Fix and call again:\n- " + "\n- ".join(problems))


def _link(deps: VerifyDeps, link_id: str) -> WorkingLink:
    link = deps.case.link(link_id)
    if link is None:
        known = ", ".join(item.link_id for item in deps.case.chain)
        raise ModelRetry(f"No link {link_id!r}. Links: {known}.")
    return link


def _source_refs(deps: VerifyDeps, citations: list[Citation]) -> list[SourceRef]:
    seen: dict[str, SourceRef] = {}
    for citation in citations:
        entry = deps.case.documents[citation.doc_id]
        seen.setdefault(citation.doc_id, SourceRef(doc_id=entry.doc_id, filename=entry.filename))
    return list(seen.values())


def _own_instruments_examined(deps: VerifyDeps, link: WorkingLink) -> list[str]:
    """Examined deeds that are this link's own instrument: their instrument facts carry
    the link's registration number (a later deed merely reciting it does not count)."""
    number = re.sub(r"[^0-9a-z]", "", (link.transaction.transaction_number or "").casefold())
    if len(number) < 4:
        return []
    found = []
    for ref in link.transaction.source_refs:
        entry = deps.case.documents.get(ref.doc_id)
        if not (entry and entry.examined and entry.report and is_deed_type(entry.document_type)):
            continue
        facts = " ".join(f"{fact.text} {fact.quote}" for fact in entry.report.instrument)
        if number in re.sub(r"[^0-9a-z]", "", facts.casefold()):
            found.append(ref.doc_id)
    return found


VERDICT_WORDS = {
    "verified": "verified",
    "verified_with_concerns": "verified with concerns",
    "unverified_missing_document": "cannot be verified until a document is provided",
    "defective": "defective",
}
# Internal ids must never appear in text a buyer reads.
_INTERNAL_ID = re.compile(r"\b(?:PA-TC-\d+|VL-\d+|DOC_\d+|[RLI]\d{1,3})\b")


def transfer_name(link: WorkingLink) -> str:
    """A transfer named the way a buyer would: "the sale of 2019"."""
    match = re.search(
        r"(19|20)\d{2}", link.transaction.executed_date or link.transaction.registration_date or ""
    )
    year = f" of {match.group(0)}" if match else ""
    kind = link.transaction.transaction_type.replace("_", " ").lower()
    return f"the {kind}{year}"


def _plain(field: str, text: str | None) -> list[str]:
    """Refuse buyer-facing text that mentions internal ids."""
    ids = sorted(set(_INTERNAL_ID.findall(text or "")))
    if not ids:
        return []
    return [
        f"{field} mentions internal ids ({', '.join(ids)}). The buyer reads this text: name "
        'transfers in words ("the 2019 sale to Arjun Patil") and documents by what they are '
        '("the 2007 sale deed"); ids belong only in the id fields.'
    ]


def _digest(deps: VerifyDeps) -> str:
    """One line of what is still to do before closing, appended to every change.

    It lets the Lead keep track without calling view_case_file after each step.
    """
    case = deps.case
    parts = []
    no_verdict = [link.link_id for link in case.chain if link.verdict is None]
    if no_verdict:
        parts.append(f"no verdict: {', '.join(no_verdict)}")
    sources = unexamined_link_sources(case)
    if sources:
        docs = sorted({doc for docs in sources.values() for doc in docs})
        parts.append(f"examine sources: {', '.join(docs)}")
    open_leads = [lead.id for lead in case.leads if lead.status == "open"]
    if open_leads:
        parts.append(f"open leads: {', '.join(open_leads)}")
    breaks = [
        link.link_id
        for link in case.chain[1:]
        if not link.continues_previous and not link.break_note
    ]
    if breaks:
        parts.append(f"unrecorded break before: {', '.join(breaks)}")
    arrived = [item.id for item in case.requisitions if item.status == "fulfilled"]
    if arrived:
        parts.append(f"review arrived documents for: {', '.join(arrived)}")
    return f"\nStill to do: {'; '.join(parts)}." if parts else "\nNothing left: you may close."


def _change_chain(deps: VerifyDeps, change) -> None:
    """Apply a chain change, keeping it only if the chain gates still pass."""
    before = [link.model_copy(deep=True) for link in deps.case.chain]
    try:
        change()
        problems = chain_problems(deps.gate_context)
    except (ValueError, TypeError) as error:
        deps.case.chain = before
        raise ModelRetry(f"Not saved: {error}") from error
    if problems:
        deps.case.chain = before
        _require(problems)


# -- Case File toolset ----------------------------------------------------------

case_file_tools = FunctionToolset[VerifyDeps](id="case_file", max_retries=_TOOL_RETRIES)


@case_file_tools.tool
def view_case_file(ctx: RunContext[VerifyDeps]) -> str:
    """Show the current Case File: chain, documents, leads, issues, requisitions, tasks,
    and what is still to do before the case can close. It is the source of truth."""
    return render_case_file(ctx.deps.case, ctx.deps.gate_context)


@case_file_tools.tool
def record_link_verdict(
    ctx: RunContext[VerifyDeps],
    link_id: str,
    verdict: LinkVerdictKind,
    summary: str,
    checks: list[CheckResult],
) -> str:
    """Record the verification result for one chain link.

    Every check marked ok must cite the passage that proves it. An encumbrance
    certificate cannot be cited as proof of a transfer.

    Args:
        link_id: The link verified.
        verdict: verified (every check ok), verified_with_concerns (some concern,
            none failed), unverified_missing_document (a needed document is
            absent; add a requisition naming this link), or defective (a check failed).
        summary: One or two sentences for the report.
        checks: The individual checks (vendor title, parties and capacity,
            schedule and extent, execution, registration, stamp duty, consideration).
    """
    deps = ctx.deps
    link = _link(deps, link_id)
    statuses = {check.status for check in checks}
    citations = [citation for check in checks for citation in check.citations]
    problems = [
        f"Check {check.check!r} is ok but cites nothing. Cite the passage that proves it."
        for check in checks
        if check.status == "ok" and not check.citations
    ]
    if verdict == "verified" and statuses != {"ok"}:
        problems.append("verified needs every check ok.")
    if verdict == "defective" and "failed" not in statuses:
        problems.append("defective needs at least one failed check.")
    if verdict == "verified_with_concerns" and ("failed" in statuses or "concern" not in statuses):
        problems.append("verified_with_concerns needs a concern and no failed check.")
    if verdict == "unverified_missing_document" and "not_verifiable" not in statuses:
        problems.append("unverified_missing_document needs a not_verifiable check.")
    if verdict != "unverified_missing_document" and not citations:
        problems.append(
            f"A {verdict} verdict must cite evidence. Reopen the saved examiner reports of "
            "this link's documents with examine_document (free) and cite their passages."
        )
    examined_instruments = _own_instruments_examined(deps, link)
    if verdict == "unverified_missing_document" and examined_instruments:
        problems.append(
            f"The link's own instrument ({', '.join(examined_instruments)}) has been examined, "
            "so it is not missing. Reopen its report with examine_document and verify against it."
        )
    problems += citation_problems(deps.gate_context, citations)
    problems += link_evidence_problems(deps.gate_context, citations)
    problems += _plain("summary", summary)
    for check in checks:
        problems += _plain(f"Check {check.check!r} name", check.check)
        problems += _plain(f"Check {check.check!r} note", check.note)
    _require(problems)
    link.verdict = LinkVerdict(verdict=verdict, summary=summary, checks=checks)
    deps.emit(
        "verdict", f"{transfer_name(link).capitalize()}: {VERDICT_WORDS[verdict]}. {summary}", link_id
    )
    return f"Recorded {verdict} for {link_id}." + _digest(deps)


@case_file_tools.tool
def insert_link(
    ctx: RunContext[VerifyDeps],
    after_link_id: str | None,
    transfer: NewTransfer,
    reason: str,
    citations: list[Citation],
) -> str:
    """Add a transfer the chain is missing, e.g. a partition found in a recital.

    Args:
        after_link_id: Insert after this link; null to insert before the first link.
        transfer: The transfer. Its sources are the cited documents.
        reason: Why the chain needs it.
        citations: Passages that report the transfer.
    """
    deps = ctx.deps
    _require(["Cite the passages that report the transfer."] if not citations else [])
    _require(citation_problems(deps.gate_context, citations))
    _require(_plain("reason", reason))
    index = 0 if after_link_id is None else deps.case.chain.index(_link(deps, after_link_id)) + 1
    fields = transfer.model_dump(exclude={"continues_previous"})
    new_link = WorkingLink(
        link_id=deps.case.next_id("VL-"),
        origin="verification",
        continues_previous=transfer.continues_previous,
        transaction=DocumentedTransaction(**fields, source_refs=_source_refs(deps, citations)),
        amendments=[f"Inserted: {reason}"],
    )
    _change_chain(deps, lambda: deps.case.chain.insert(index, new_link))
    deps.emit(
        "chain",
        f"Added a transfer to the chain: {transfer_name(new_link)}. {reason}",
        new_link.link_id,
    )
    return f"Inserted {new_link.link_id}." + _digest(deps)


@case_file_tools.tool
def correct_link(
    ctx: RunContext[VerifyDeps],
    link_id: str,
    changes: LinkCorrection,
    reason: str,
    citations: list[Citation],
) -> str:
    """Correct a link's details (parties, date, number, extent, evidence status).

    Args:
        link_id: The link to correct.
        changes: Only the fields to change.
        reason: What was wrong.
        citations: Passages that support the correction.
    """
    deps = ctx.deps
    link = _link(deps, link_id)
    _require(["Cite the passages that support the correction."] if not citations else [])
    _require(citation_problems(deps.gate_context, citations))
    _require(_plain("reason", reason))
    updates = changes.model_dump(exclude_none=True)
    continues = updates.pop("continues_previous", None)

    def apply() -> None:
        refs = {ref.doc_id: ref for ref in link.transaction.source_refs}
        refs.update({ref.doc_id: ref for ref in _source_refs(deps, citations)})
        link.transaction = DocumentedTransaction.model_validate(
            {**link.transaction.model_dump(), **updates, "source_refs": list(refs.values())}
        )
        if continues is not None:
            link.continues_previous = continues
            link.break_note = None if continues else link.break_note
        link.amendments.append(f"Corrected: {reason}")

    _change_chain(deps, apply)
    deps.emit("chain", f"Corrected {transfer_name(link)}: {reason}", link_id)
    return f"Corrected {link_id}." + _digest(deps)


@case_file_tools.tool
def mark_break(ctx: RunContext[VerifyDeps], link_id: str, note: str) -> str:
    """Record that no recorded transfer connects this link to the previous one.

    Args:
        link_id: The link after the break.
        note: Who is missing between which owners, and what was searched.
    """
    deps = ctx.deps
    link = _link(deps, link_id)
    _require(_plain("note", note))

    def apply() -> None:
        link.continues_previous = False
        link.break_note = note
        link.amendments.append(f"Break recorded: {note}")

    _change_chain(deps, apply)
    deps.emit("chain", f"Break in the chain before {transfer_name(link)}: {note}", link_id)
    return f"Break recorded before {link_id}." + _digest(deps)


@case_file_tools.tool
def remove_link(
    ctx: RunContext[VerifyDeps], link_id: str, reason: str, citations: list[Citation]
) -> str:
    """Remove a link that is a duplicate or not a transfer of this property.

    Args:
        link_id: The link to remove.
        reason: Why it does not belong in the chain.
        citations: Passages that show it.
    """
    deps = ctx.deps
    link = _link(deps, link_id)
    _require(["Cite the passages that show it does not belong."] if not citations else [])
    _require(citation_problems(deps.gate_context, citations))
    _require(_plain("reason", reason))
    _change_chain(deps, lambda: deps.case.chain.remove(link))
    deps.emit("chain", f"Removed {transfer_name(link)} from the chain: {reason}", link_id)
    return f"Removed {link_id}." + _digest(deps)


@case_file_tools.tool
def open_lead(ctx: RunContext[VerifyDeps], text: str, source: str) -> str:
    """Note something discovered that must be followed up before the case can close.

    Args:
        text: What must be checked, e.g. "2005 partition may change B's title".
        source: Where it was seen, e.g. "EC p.2".
    """
    case = ctx.deps.case
    _require(_plain("text", text) + _plain("source", source))
    lead = Lead(id=case.next_id("L"), text=text, source=source)
    case.leads.append(lead)
    ctx.deps.emit("lead", f"Found something to follow up: {text}", lead.id)
    return f"Opened {lead.id}." + _digest(ctx.deps)


@case_file_tools.tool
def resolve_lead(
    ctx: RunContext[VerifyDeps],
    lead_id: str,
    outcome: Literal["evidence", "requisition", "not_material"],
    resolution: str,
    citations: list[Citation] | None = None,
    requisition_id: str | None = None,
) -> str:
    """Close a lead.

    Args:
        lead_id: The lead.
        outcome: evidence (cite it), requisition (name the requisition that
            covers it), or not_material (explain why it does not affect title).
        resolution: What was found or decided.
        citations: Required for outcome evidence.
        requisition_id: Required for outcome requisition: the requisition that covers
            this lead (the lead is added to what it affects).
    """
    deps = ctx.deps
    lead = deps.case.lead(lead_id)
    if lead is None:
        raise ModelRetry(f"No lead {lead_id!r}.")
    citations = citations or []
    problems = _plain("resolution", resolution)
    if outcome == "evidence":
        problems += ["Cite the evidence."] if not citations else []
        problems += citation_problems(deps.gate_context, citations)
    requisition = deps.case.requisition(requisition_id or "")
    if outcome == "requisition" and requisition is None:
        open_ids = [item.id for item in deps.case.requisitions if item.status == "open"]
        problems.append(
            f"Name the requisition that covers {lead_id} (open: {', '.join(open_ids) or 'none'}), "
            "or add one with add_requisition first."
        )
    _require(problems)
    if outcome == "requisition" and lead_id not in requisition.affects:
        requisition.affects = [*requisition.affects, lead_id]
    lead.status, lead.outcome, lead.resolution = "resolved", outcome, resolution
    deps.emit("lead", f"Followed up: {resolution}", lead_id)
    return f"Resolved {lead_id}." + _digest(deps)


@case_file_tools.tool
def record_issue(
    ctx: RunContext[VerifyDeps],
    severity: Severity,
    title: str,
    detail: str,
    link_ids: list[str] | None = None,
    citations: list[Citation] | None = None,
    distinct: bool = False,
) -> str:
    """Record a red flag or observation for the report. Record each problem once.

    Args:
        severity: high (a defect: title is not clear), medium (title is clear
            only subject to rectifying it), or low (an observation).
        title: Short title.
        detail: What is wrong and why it matters.
        link_ids: Links it concerns.
        citations: Passages that show it.
        distinct: Set true only if a similar existing issue is a different problem.
    """
    deps = ctx.deps
    link_ids, citations = link_ids or [], citations or []
    known = {link.link_id for link in deps.case.chain}
    problems = [f"No link {link_id!r}." for link_id in link_ids if link_id not in known]
    problems += citation_problems(deps.gate_context, citations)
    problems += _plain("title", title) + _plain("detail", detail)
    _require(problems)
    similar = None if distinct else _similar_issue(deps, title, detail)
    if similar is not None:
        return (
            f"Not recorded: this looks like {similar.id} ({similar.severity}: {similar.title}). "
            f"If it is the same problem, use update_issue on {similar.id}; if it is a different "
            "problem, call record_issue again with distinct=true."
        )
    issue = Issue(
        id=deps.case.next_id("I"),
        severity=severity,
        title=title,
        detail=detail,
        link_ids=link_ids,
        citations=citations,
    )
    deps.case.issues.append(issue)
    deps.emit("issue", f"Issue ({severity}): {title}", issue.id)
    return f"Recorded {issue.id}." + _digest(deps)


@case_file_tools.tool
def update_issue(
    ctx: RunContext[VerifyDeps],
    issue_id: str,
    severity: Severity | None = None,
    detail: str | None = None,
    link_ids: list[str] | None = None,
) -> str:
    """Change an existing issue's severity, detail or links instead of recording it again.

    Args:
        issue_id: The issue.
        severity: New severity, if it changes.
        detail: Replacement detail, if it changes.
        link_ids: Replacement list of links it concerns, if it changes.
    """
    deps = ctx.deps
    issue = next((item for item in deps.case.issues if item.id == issue_id), None)
    if issue is None:
        raise ModelRetry(f"No issue {issue_id!r}.")
    known = {link.link_id for link in deps.case.chain}
    _require([f"No link {link_id!r}." for link_id in link_ids or [] if link_id not in known])
    _require(_plain("detail", detail))
    issue.severity = severity or issue.severity
    issue.detail = detail or issue.detail
    issue.link_ids = link_ids if link_ids is not None else issue.link_ids
    deps.emit("issue", f"Issue updated ({issue.severity}): {issue.title}", issue_id)
    return f"Updated {issue_id}." + _digest(deps)


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if len(word) >= 4}


def _similar_issue(deps: VerifyDeps, title: str, detail: str) -> Issue | None:
    """An existing issue that is probably the same problem (most title words shared)."""
    new_title = _words(title)
    for issue in deps.case.issues:
        old_title = _words(issue.title)
        if not new_title or not old_title:
            continue
        shared = len(new_title & old_title) / min(len(new_title), len(old_title))
        overall = _words(f"{title} {detail}") & _words(f"{issue.title} {issue.detail}")
        if shared >= 0.6 or (shared >= 0.34 and len(overall) >= 6):
            return issue
    return None


@case_file_tools.tool
def add_requisition(
    ctx: RunContext[VerifyDeps],
    document: str,
    reason: str,
    affects: list[str],
    closes_leads: list[str] | None = None,
) -> str:
    """Note a document that is needed, then carry on with what you have. Never wait for it.

    Args:
        document: What is needed, e.g. "Partition deed of 2005 among B, B2, B3".
        reason: What it would establish.
        affects: Link, lead or issue ids it would settle.
        closes_leads: Open lead ids this requisition covers; they are resolved in the
            same call, so no separate resolve_lead is needed.
    """
    deps = ctx.deps
    closes_leads = closes_leads or []
    unknown = sorted(set(affects) - deps.case.known_ids())
    problems = [f"Unknown ids: {', '.join(unknown)}."] if unknown else []
    problems += ["Name at least one link, lead or issue it affects."] if not affects else []
    open_leads = {lead.id for lead in deps.case.leads if lead.status == "open"}
    problems += [
        f"{lead_id} is not an open lead." for lead_id in closes_leads if lead_id not in open_leads
    ]
    problems += _plain("document", document) + _plain("reason", reason)
    _require(problems)
    requisition = next(
        (
            item
            for item in deps.case.requisitions
            if item.status == "open" and normalize(item.document) == normalize(document)
        ),
        None,
    )
    if requisition is not None:
        requisition.affects = sorted({*requisition.affects, *affects, *closes_leads})
        reply = f"Already requested as {requisition.id}; added to what it affects."
    else:
        requisition = Requisition(
            id=deps.case.next_id("R"),
            document=document,
            reason=reason,
            affects=[*affects, *(lead for lead in closes_leads if lead not in affects)],
        )
        deps.case.requisitions.append(requisition)
        deps.emit("requisition", f"Document needed: {document}", requisition.id)
        reply = f"Added {requisition.id}."
    for lead_id in closes_leads:
        lead = deps.case.lead(lead_id)
        lead.status, lead.outcome = "resolved", "requisition"
        lead.resolution = f"Covered by the document request: {document}"
        deps.emit("lead", f"Followed up by requesting: {requisition.document}", lead_id)
    return reply + _digest(deps)


@case_file_tools.tool
def review_requisition(
    ctx: RunContext[VerifyDeps],
    requisition_id: str,
    settled: bool,
    note: str,
) -> str:
    """After examining a document that arrived for a requisition, say whether it settles it.

    Args:
        requisition_id: The requisition.
        settled: true if the document settles what was needed; false to keep it open.
        note: What the document showed.
    """
    deps = ctx.deps
    _require(_plain("note", note))
    requisition = deps.case.requisition(requisition_id)
    if requisition is None:
        raise ModelRetry(f"No requisition {requisition_id!r}.")
    if requisition.doc_id and not deps.case.documents.get(requisition.doc_id, None):
        raise ModelRetry(f"Its document {requisition.doc_id} is not in the case.")
    if requisition.doc_id:
        entry = deps.case.documents[requisition.doc_id]
        if not entry.examined and not entry.examination_error:
            raise ModelRetry(f"Examine {requisition.doc_id} before reviewing {requisition_id}.")
    requisition.status = "resolved" if settled else "open"
    deps.emit(
        "requisition",
        f"{'Requested document accepted' if settled else 'Requested document did not settle the request'}: {requisition.document}",
        requisition_id,
    )
    return f"{requisition_id} is {requisition.status}." + _digest(deps)


# -- Evidence toolset -------------------------------------------------------------

evidence_tools = FunctionToolset[VerifyDeps](id="evidence", max_retries=_TOOL_RETRIES)


@evidence_tools.tool
def read_pages(ctx: RunContext[VerifyDeps], doc_id: str, first_page: int, last_page: int) -> str:
    """Read specific pages of a document to settle a doubt. Use examine_document to
    read a whole document; this is for a targeted look.

    Args:
        doc_id: The document.
        first_page: First page to read.
        last_page: Last page to read (at most 8 pages per call).
    """
    deps = ctx.deps
    if doc_id not in deps.case.documents:
        raise ModelRetry(f"No document {doc_id!r}. Documents: {', '.join(deps.case.documents)}.")
    pages = split_pages(deps.text_of(doc_id))
    wanted = [n for n in sorted(pages) if first_page <= n <= last_page][:_MAX_PAGES_PER_READ]
    if not wanted:
        raise ModelRetry(f"{doc_id} has pages {min(pages, default=0)}-{max(pages, default=0)}.")
    filename = deps.case.documents[doc_id].filename or doc_id
    deps.emit("read", f"Reading {filename}, pages {wanted[0]}-{wanted[-1]}", doc_id)
    return "\n\n".join(f"--- Page {n} ---\n{pages[n]}" for n in wanted)
