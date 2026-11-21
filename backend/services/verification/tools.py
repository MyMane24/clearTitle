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
    WINDOW_YEARS,
    CheckResult,
    Citation,
    ClearCheck,
    Issue,
    Lead,
    LinkVerdict,
    LinkVerdictKind,
    NeededDocument,
    PropertyType,
    Requisition,
    Severity,
    WorkingLink,
)
from backend.services.verification.context import render_case_file
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.gates import (
    ACTIVE_REQUISITION,
    SEVERAL_DOCUMENTS,
    alike,
    chain_problems,
    citation_problems,
    duplicate_requisitions,
    link_evidence_problems,
    unexamined_documents,
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


def _order_problems(deps: VerifyDeps, link: WorkingLink) -> list[str]:
    """Transfers are verified oldest first, each connected to the one before it."""
    window = deps.case.window()
    if link not in window:
        return [
            f"{link.link_id} is older than the {WINDOW_YEARS}-year window; it needs no verdict. "
            f"Start from {window[0].link_id}."
        ]
    index = window.index(link)
    earlier = [item.link_id for item in window[:index] if item.verdict is None]
    if earlier:
        return [f"Verify the earlier transfers first, oldest first: {', '.join(earlier)}."]
    if index and not link.continues_previous and not link.break_note:
        return [
            f"Settle how ownership reached the transferors of {link.link_id} first: insert the "
            "missing transfer (succession, partition, ...) if any document reports it, or "
            "mark_break if none does."
        ]
    return []


def _needed_document_problems(
    deps: VerifyDeps, link_id: str, verdict: str, needed: list[NeededDocument]
) -> list[str]:
    """Each needed document is found with citations, or missing with its requisition."""
    if not needed:
        return ["List the documents that legally prove this transfer in needed_documents."]
    problems = []
    for item in needed:
        problems += _plain("needed document", item.document) + _plain("proves", item.proves)
        if item.status == "found":
            if not item.citations:
                problems.append(f"{item.document!r} is found but cites nothing. Cite it.")
            problems += citation_problems(deps.gate_context, item.citations)
            problems += link_evidence_problems(deps.gate_context, item.citations)
            continue
        requisition = deps.case.requisition(item.requisition_id or "")
        if requisition is None or requisition.status in ("resolved", "withdrawn"):
            problems.append(
                f"{item.document!r} is missing: add it with add_requisition first and give its "
                "requisition_id."
            )
        elif link_id not in requisition.affects:
            requisition.affects = [*requisition.affects, link_id]  # it is needed for this one too
    missing = [item for item in needed if item.status == "missing"]
    if verdict == "verified" and missing:
        problems.append("verified needs every needed document found.")
    if verdict == "unverified_missing_document" and not missing:
        problems.append("unverified_missing_document needs a missing needed document.")
    return problems


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


MAX_ISSUE_LINKS = 3  # one problem concerns one or a few transfers
TITLE_MAX, DETAIL_MAX = 70, 220  # what fits one finding card on the buyer's page


def _short(field: str, text: str | None, limit: int) -> list[str]:
    """Refuse buyer-facing text longer than the page shows."""
    if text and len(text) > limit:
        return [f"{field} is {len(text)} characters; keep it to {limit}. Buyers read short lines."]
    return []


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
    no_verdict = [link.link_id for link in case.window() if link.verdict is None]
    if no_verdict:
        parts.append(f"next transfer to verify: {no_verdict[0]} (then {len(no_verdict) - 1} more)")
    docs = unexamined_documents(case)
    if docs:
        parts.append(f"not yet examined: {', '.join(docs)}")
    open_leads = [lead.id for lead in case.leads if lead.status == "open"]
    if open_leads:
        parts.append(f"open leads: {', '.join(open_leads)}")
    breaks = [
        link.link_id
        for link in case.window()[1:]
        if not link.continues_previous and not link.break_note
    ]
    if breaks:
        parts.append(f"unrecorded break before: {', '.join(breaks)}")
    duplicates = duplicate_requisitions(case)
    if duplicates:
        parts.append("duplicate requests: " + ", ".join(f"{a}={b}" for a, b in duplicates))
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
    """Show the current Case File: chain, documents, leads, issues, requisitions,
    and what is still to do before the case can close. It is the source of truth.
    Call it once at the start; every change replies with what is still to do."""
    deps = ctx.deps
    fingerprint = deps.case.model_dump_json()
    if fingerprint == deps.last_view:
        return (
            "Nothing changed since your last view_case_file. Act on it: verify the next "
            "transfer, then call record_link_verdict." + _digest(deps)
        )
    deps.last_view = fingerprint
    return render_case_file(deps.case, deps.gate_context)


@case_file_tools.tool
def record_link_verdict(
    ctx: RunContext[VerifyDeps],
    link_id: str,
    verdict: LinkVerdictKind,
    summary: str,
    checks: list[CheckResult],
    property_type: PropertyType,
    extent: str,
    needed_documents: list[NeededDocument],
) -> str:
    """Record the verification result for one transfer. Verify transfers oldest first.

    Every check marked ok must cite the passage that proves it. An encumbrance
    certificate cannot be cited as proof of a transfer.

    Args:
        link_id: The transfer verified.
        verdict: verified (every check ok, no document missing), verified_with_concerns
            (some concern, none failed), unverified_missing_document (a needed
            document is missing), or defective (a check failed).
        summary: One or two sentences for the report.
        checks: The individual checks (vendor title, parties and capacity,
            schedule and extent, execution, registration, stamp duty, consideration).
        property_type: What this transfer conveyed, as its instrument describes it.
        extent: The extent conveyed, as the instrument states it.
        needed_documents: Every document that legally proves this transfer, as you
            judge it: found (cite the passages that show it proves this transfer) or
            missing (the requisition that asks for it).
    """
    deps = ctx.deps
    link = _link(deps, link_id)
    _require(_order_problems(deps, link))
    statuses = {check.status for check in checks}
    citations = [citation for check in checks for citation in check.citations]
    problems = _needed_document_problems(deps, link_id, verdict, needed_documents)
    problems += [
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
    if verdict != "unverified_missing_document" and not citations:
        problems.append(
            f"A {verdict} verdict must cite evidence. Reopen the saved examiner reports of "
            "this link's documents with examine_document (free) and cite their passages."
        )
    problems += citation_problems(deps.gate_context, citations)
    problems += link_evidence_problems(deps.gate_context, citations)
    problems += _plain("summary", summary)
    for check in checks:
        problems += _plain(f"Check {check.check!r} name", check.check)
        problems += _plain(f"Check {check.check!r} note", check.note)
    problems += _plain("extent", extent)
    _require(problems)
    link.verdict = LinkVerdict(
        verdict=verdict,
        summary=summary,
        checks=checks,
        property_type=property_type,
        extent=extent,
        needed_documents=needed_documents,
    )
    deps.emit(
        "verdict",
        f"{transfer_name(link).capitalize()}: {VERDICT_WORDS[verdict]}. {summary}",
        link_id,
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
        source: Where it was seen, e.g. "DOC_002 p.2" (internal; ids are fine here).
    """
    case = ctx.deps.case
    _require(_plain("text", text))
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
        title: A few words, at most 70 characters.
        detail: What is wrong and why it matters, at most 220 characters.
        link_ids: Links it concerns.
        citations: Passages that show it.
        distinct: Set true only if a similar existing issue is a different problem.
    """
    deps = ctx.deps
    link_ids, citations = link_ids or [], citations or []
    known = {link.link_id for link in deps.case.chain}
    problems = [f"No link {link_id!r}." for link_id in link_ids if link_id not in known]
    if len(link_ids) > MAX_ISSUE_LINKS:
        problems.append(
            f"An issue names at most {MAX_ISSUE_LINKS} transfers. Record each problem as its own "
            "issue (the unreleased mortgage, the unproven heirs, ...), not a summary of the case."
        )
    problems += citation_problems(deps.gate_context, citations)
    problems += _plain("title", title) + _plain("detail", detail)
    problems += _short("title", title, TITLE_MAX) + _short("detail", detail, DETAIL_MAX)
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
        detail: Replacement detail, if it changes (at most 220 characters).
        link_ids: Replacement list of links it concerns, if it changes.
    """
    deps = ctx.deps
    issue = next((item for item in deps.case.issues if item.id == issue_id), None)
    if issue is None:
        raise ModelRetry(f"No issue {issue_id!r}.")
    known = {link.link_id for link in deps.case.chain}
    problems = [f"No link {link_id!r}." for link_id in link_ids or [] if link_id not in known]
    if link_ids and len(link_ids) > MAX_ISSUE_LINKS:
        problems.append(f"An issue names at most {MAX_ISSUE_LINKS} transfers.")
    _require(problems)
    _require(_plain("detail", detail) + _short("detail", detail, DETAIL_MAX))
    issue.severity = severity or issue.severity
    issue.detail = detail or issue.detail
    issue.link_ids = link_ids if link_ids is not None else issue.link_ids
    deps.emit("issue", f"Issue updated ({issue.severity}): {issue.title}", issue_id)
    return f"Updated {issue_id}." + _digest(deps)


@case_file_tools.tool
def record_clear_check(
    ctx: RunContext[VerifyDeps], title: str, detail: str, citations: list[Citation]
) -> str:
    """Record a positive finding the buyer should see, e.g. "Owner name matches across
    documents" or "Encumbrance certificate reaches the present day". Cite what proves it.

    Args:
        title: A few words, at most 70 characters.
        detail: One or two short sentences, at most 220 characters.
        citations: Passages that prove it.
    """
    deps = ctx.deps
    problems = ["Cite the passages that prove it."] if not citations else []
    problems += citation_problems(deps.gate_context, citations)
    problems += _plain("title", title) + _plain("detail", detail)
    problems += _short("title", title, TITLE_MAX) + _short("detail", detail, DETAIL_MAX)
    _require(problems)
    same = next(
        (c for c in deps.case.clear_checks if alike(title, detail, c.title, c.detail)), None
    )
    if same is not None:
        return f"Not recorded: already noted as {same.id} ({same.title})."
    item = ClearCheck(id=deps.case.next_id("C"), title=title, detail=detail, citations=citations)
    deps.case.clear_checks.append(item)
    deps.emit("clear", f"Clear: {title}", item.id)
    return f"Recorded {item.id}." + _digest(deps)


def _similar_issue(deps: VerifyDeps, title: str, detail: str) -> Issue | None:
    """An existing issue that is probably the same problem."""
    return next(
        (issue for issue in deps.case.issues if alike(title, detail, issue.title, issue.detail)),
        None,
    )


def _similar_requisition(deps: VerifyDeps, document: str, reason: str) -> Requisition | None:
    """An open requisition that probably asks for the same document."""
    return next(
        (
            item
            for item in deps.case.requisitions
            if item.status in ACTIVE_REQUISITION
            and alike(document, reason, item.document, item.reason)
        ),
        None,
    )


@case_file_tools.tool
def add_requisition(
    ctx: RunContext[VerifyDeps],
    document: str,
    reason: str,
    affects: list[str],
    closes_leads: list[str] | None = None,
) -> str:
    """Request ONE missing document, then carry on with what you have. Never wait for it.

    Call once per document: the buyer gets one upload button per request. Asking again
    for a document already requested only extends that request; it never adds a row.

    Args:
        document: The one document needed, at most 150 characters, e.g. "Partition deed
            of 2005 among B, B2, B3".
        reason: One sentence, at most 160 characters: what it would prove.
        affects: The transfer (link id) it is needed for, plus any lead or issue ids it settles.
        closes_leads: Open lead ids this requisition covers; they are resolved in the
            same call, so no separate resolve_lead is needed.
    """
    deps = ctx.deps
    closes_leads = closes_leads or []
    unknown = sorted(set(affects) - deps.case.known_ids())
    problems = [f"Unknown ids: {', '.join(unknown)}."] if unknown else []
    anchors = {link.link_id for link in deps.case.chain} | {issue.id for issue in deps.case.issues}
    if not anchors & {*affects}:
        problems.append(
            "Name in affects the transfer (link id) this document is needed for, or the issue "
            "it settles."
        )
    open_leads = {lead.id for lead in deps.case.leads if lead.status == "open"}
    problems += [
        f"{lead_id} is not an open lead." for lead_id in closes_leads if lead_id not in open_leads
    ]
    if SEVERAL_DOCUMENTS.search(document):
        problems.append(
            "document names several documents. Request one document per call; call "
            "add_requisition again for each of the others."
        )
    problems += _plain("document", document) + _plain("reason", reason)
    problems += _short("document", document, 150) + _short("reason", reason, 160)
    _require(problems)
    requisition = next(
        (
            item
            for item in deps.case.requisitions
            if item.status in ACTIVE_REQUISITION and normalize(item.document) == normalize(document)
        ),
        None,
    ) or _similar_requisition(deps, document, reason)
    if requisition is not None:
        requisition.affects = sorted({*requisition.affects, *affects, *closes_leads})
        reply = (
            f"Already requested as {requisition.id} ({requisition.document}); added to what it "
            "affects. Do not request it again."
        )
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
def withdraw_requisition(
    ctx: RunContext[VerifyDeps], requisition_id: str, reason: str, replaced_by: str | None = None
) -> str:
    """Withdraw a request that is a duplicate, already uploaded, or not needed after all.

    Args:
        requisition_id: The request to withdraw.
        reason: Why, in one short sentence.
        replaced_by: For a duplicate, the request that covers it instead; what it affects
            and every verdict naming it move there.
    """
    deps = ctx.deps
    requisition = deps.case.requisition(requisition_id)
    if requisition is None or requisition.status != "open":
        raise ModelRetry(f"{requisition_id} is not an open requisition.")
    target = deps.case.requisition(replaced_by) if replaced_by else None
    if replaced_by and (target is None or target.status not in ACTIVE_REQUISITION):
        raise ModelRetry(f"{replaced_by} is not an active requisition.")
    _require(_plain("reason", reason))
    if target is not None:
        target.affects = sorted({*target.affects, *requisition.affects})
        for link in deps.case.chain:
            for needed in link.verdict.needed_documents if link.verdict else []:
                if needed.requisition_id == requisition_id:
                    needed.requisition_id = target.id
    requisition.status = "withdrawn"
    deps.emit("requisition", f"No longer needed: {requisition.document} ({reason})", requisition_id)
    return f"Withdrew {requisition_id}." + _digest(deps)


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
