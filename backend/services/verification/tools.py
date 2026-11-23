"""The Lead Examiner's tools, grouped into toolsets.

The Lead verifies one transfer at a time and writes its whole record in one call
(``record_transfer``), then records the property as it stands today. Document
requests are filed and closed by the application from the records' missing
documents. Every tool checks its input with the gates first; a failed check
becomes a ``ModelRetry`` telling the model what to fix, and the Case File is
left unchanged.
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
    AddedBecause,
    CaseFile,
    Citation,
    Concern,
    Connection,
    ProofDocument,
    Property,
    Request,
    Section,
    SectionName,
    SetAside,
    Transfer,
    transfer_result,
)
from backend.services.verification.context import render_case_file
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.gates import (
    ACTIVE_REQUEST,
    SEVERAL_DOCUMENTS,
    alike,
    chain_problems,
    citation_problems,
    connection_problems,
    duplicate_requests,
    proof_problems,
    unexamined_documents,
    unused_unexpected,
)
from backend.services.verification.pages import normalize, split_pages

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EvidenceStatus = Literal["corroborated", "register_reported", "deed_reported", "recital_reported"]

_MAX_PAGES_PER_READ = 8
_TOOL_RETRIES = 5
NAME_MAX, PROVES_MAX, CONCERN_MAX, SUMMARY_MAX = 150, 160, 220, 300


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


class TransferCorrection(_Input):
    """Details of the transfer that the chain recorded wrongly. Leave a field out to keep it."""

    transaction_type: str | None = None
    transaction_number: str | None = None
    executed_date: str | None = None
    registration_date: str | None = None
    transferors: list[Text] | None = None
    transferees: list[Text] | None = None
    survey_number: str | None = None
    consideration: str | None = None


class SetAsideItem(_Input):
    doc_id: str
    fact: str = Field(description="The unexpected finding's number, e.g. 'F7'.")
    reason: Text = Field(description="Why it does not affect title, in one short sentence.")


# -- Words for the buyer ----------------------------------------------------------

RESULT_WORDS = {
    "verified": "verified",
    "verified_with_concerns": "verified with concerns",
    "documents_missing": "waiting for documents",
    "defective": "defective",
    # Results saved before schema 5, still read by report versioning.
    "unverified_missing_document": "waiting for documents",
}
SECTION_WORDS = {
    "encumbrances": "Encumbrances",
    "revenue_records": "Revenue records",
    "tax_and_approvals": "Tax and approvals",
}
# Internal ids must never appear in text a buyer reads.
_INTERNAL_ID = re.compile(r"\b(?:PA-TC-\d+|VL-\d+|DOC_\d+|R\d{1,3})\b")


def transfer_name(transfer: Transfer) -> str:
    """A transfer named the way a buyer would: "the sale of 2019"."""
    transaction = transfer.transaction
    match = re.search(
        r"(19|20)\d{2}", transaction.executed_date or transaction.registration_date or ""
    )
    year = f" of {match.group(0)}" if match else ""
    kind = transaction.transaction_type.replace("_", " ").lower()
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


def _short(field: str, text: str | None, limit: int) -> list[str]:
    """Refuse buyer-facing text longer than the page shows."""
    if text and len(text) > limit:
        return [f"{field} is {len(text)} characters; keep it to {limit}. Buyers read short lines."]
    return []


# -- helpers ------------------------------------------------------------------


def _require(problems: list[str]) -> None:
    if problems:
        raise ModelRetry("Not saved. Fix and call again:\n- " + "\n- ".join(problems))


def _transfer(deps: VerifyDeps, transfer_id: str) -> Transfer:
    transfer = deps.case.transfer(transfer_id)
    if transfer is None:
        known = ", ".join(item.id for item in deps.case.transfers)
        raise ModelRetry(f"No transfer {transfer_id!r}. Transfers: {known}.")
    return transfer


def _source_refs(deps: VerifyDeps, citations: list[Citation]) -> list[SourceRef]:
    seen: dict[str, SourceRef] = {}
    for citation in citations:
        entry = deps.case.documents[citation.doc_id]
        seen.setdefault(citation.doc_id, SourceRef(doc_id=entry.doc_id, filename=entry.filename))
    return list(seen.values())


def _order_problems(case: CaseFile, transfer: Transfer) -> list[str]:
    """Transfers are verified oldest first, from the root."""
    window = case.window()
    if transfer not in window:
        return [
            f"{transfer.id} is older than the root ({WINDOW_YEARS}-year search); it needs no "
            f"record. Start from {window[0].id}."
        ]
    earlier = [item.id for item in window[: window.index(transfer)] if not item.recorded]
    if earlier:
        return [f"Verify the earlier transfers first, oldest first: {', '.join(earlier)}."]
    return []


def _document_problems(
    deps: VerifyDeps, documents: list[ProofDocument], *, proves_a_transfer: bool
) -> list[str]:
    """Each document is one document; found ones cite real passages, missing ones may
    name an active request to reuse."""
    problems = []
    for doc in documents:
        problems += _plain("document name", doc.name) + _plain("proves", doc.proves)
        problems += _short("document name", doc.name, NAME_MAX)
        problems += _short("proves", doc.proves, PROVES_MAX)
        if doc.status == "found":
            if not doc.citations:
                problems.append(f"{doc.name!r} is found but cites nothing. Cite its passages.")
            problems += citation_problems(deps.gate_context, doc.citations)
            if proves_a_transfer:
                problems += proof_problems(deps.gate_context, doc.citations)
            continue
        if SEVERAL_DOCUMENTS.search(doc.name):
            problems.append(
                f"{doc.name!r} names several documents. List each missing document on its own: "
                "the buyer gets one upload button per document."
            )
        request = deps.case.request(doc.request_id) if doc.request_id else None
        if doc.request_id and (request is None or request.status not in ACTIVE_REQUEST):
            problems.append(f"{doc.request_id} is not an open request; leave request_id out.")
        if request is not None and request.status == "received":
            entry = deps.case.documents.get(request.doc_id or "")
            if entry is not None and not entry.examined and not entry.examination_error:
                problems.append(
                    f"A document arrived for {request.id} ({request.doc_id}). Examine it before "
                    "recording this document as still missing."
                )
    return problems


def _concern_problems(deps: VerifyDeps, concerns: list[Concern]) -> list[str]:
    problems = []
    for concern in concerns:
        problems += _plain("concern", concern.text) + _short("concern", concern.text, CONCERN_MAX)
        problems += citation_problems(deps.gate_context, concern.citations)
    return problems


def _matching_request(case: CaseFile, doc: ProofDocument) -> Request | None:
    """An active request that asks for the same document."""
    for request in case.requests:
        if request.status not in ACTIVE_REQUEST:
            continue
        if normalize(request.document) == normalize(doc.name) or alike(
            doc.name, doc.proves, request.document, request.reason
        ):
            return request
    return None


def _file_requests(deps: VerifyDeps, key: str, documents: list[ProofDocument]) -> None:
    """Give every missing document a request: the one named, an active request for the
    same document, or a new one. A request whose arrived document did not settle it
    opens again."""
    case = deps.case
    for doc in documents:
        if doc.status != "missing":
            continue
        request = (case.request(doc.request_id) if doc.request_id else None) or _matching_request(
            case, doc
        )
        if request is None:
            request = Request(id=case.next_id("R"), document=doc.name, reason=doc.proves)
            case.requests.append(request)
            deps.emit("requisition", f"Document needed: {doc.name}", request.id)
        elif request.status == "received":
            deps.emit(
                "requisition",
                f"The uploaded document did not settle: {request.document}",
                request.id,
            )
            request.status, request.doc_id = "open", None
        doc.request_id = request.id
        if key not in request.needed_for:
            request.needed_for.append(key)
    listed = {doc.request_id for doc in documents if doc.status == "missing"}
    for request in case.requests:
        if key in request.needed_for and request.id not in listed:
            request.needed_for.remove(key)
    _close_unneeded_requests(deps)


def _close_unneeded_requests(deps: VerifyDeps) -> None:
    """A request no record needs any more is dropped if nothing arrived for it, or
    settled when its document arrived and the records no longer list it as missing."""
    for request in list(deps.case.requests):
        if request.needed_for or request.status == "settled":
            continue
        if request.status == "received":
            request.status = "settled"
            deps.emit("requisition", f"Requested document accepted: {request.document}", request.id)
        else:
            deps.case.requests.remove(request)


def _clear_next(deps: VerifyDeps, index: int, why: str) -> None:
    """The transfer now at ``index`` connects to a different transfer: its record is stale."""
    if index < len(deps.case.transfers) and deps.case.transfers[index].recorded:
        transfer = deps.case.transfers[index]
        transfer.clear_record()
        deps.emit("chain", f"Re-checking {transfer_name(transfer)}: {why}", transfer.id)


def _change_chain(deps: VerifyDeps, change) -> None:
    """Apply a chain change, keeping it only if the chain gates still pass."""
    before = [transfer.model_copy(deep=True) for transfer in deps.case.transfers]
    try:
        change()
        problems = chain_problems(deps.gate_context)
    except (ValueError, TypeError) as error:
        deps.case.transfers = before
        raise ModelRetry(f"Not saved: {error}") from error
    if problems:
        deps.case.transfers = before
        _require(problems)


def _digest(deps: VerifyDeps) -> str:
    """One line of what is still to do before closing, appended to every change.

    It lets the Lead keep track without calling view_case_file after each step.
    """
    case = deps.case
    parts = []
    docs = unexamined_documents(case)
    if docs:
        parts.append(f"not yet examined: {', '.join(docs)}")
    pending = [transfer.id for transfer in case.window() if not transfer.recorded]
    if pending:
        parts.append(f"next transfer to verify: {pending[0]} (then {len(pending) - 1} more)")
    else:
        sections = [name for name in SECTION_WORDS if case.section(name) is None]
        if sections:
            parts.append(f"record the property today: {', '.join(sections)}")
    arrived = [item.id for item in case.requests if item.status == "received"]
    if arrived:
        parts.append(f"documents arrived for: {', '.join(arrived)}")
    unexpected = unused_unexpected(case)
    if unexpected:
        parts.append(
            "unexpected findings to follow up: "
            + ", ".join(f"{doc_id} {number}" for doc_id, number, _ in unexpected[:8])
        )
    duplicates = duplicate_requests(case)
    if duplicates:
        parts.append("duplicate requests: " + ", ".join(f"{a}={b}" for a, b in duplicates))
    return f"\nStill to do: {'; '.join(parts)}." if parts else "\nNothing left: you may close."


# -- Case File toolset ----------------------------------------------------------

case_file_tools = FunctionToolset[VerifyDeps](id="case_file", max_retries=_TOOL_RETRIES)


@case_file_tools.tool
def view_case_file(ctx: RunContext[VerifyDeps]) -> str:
    """Show the current Case File: the transfers and their records, the property today,
    the documents, the requests, and what is still to do before the case can close.
    Call it once at the start; every change replies with what is still to do."""
    deps = ctx.deps
    fingerprint = deps.case.model_dump_json()
    if fingerprint == deps.last_view:
        return (
            "Nothing changed since your last view_case_file. Act on it: verify the next "
            "transfer and record it with record_transfer." + _digest(deps)
        )
    deps.last_view = fingerprint
    return render_case_file(deps.case, deps.gate_context)


@case_file_tools.tool
def record_transfer(
    ctx: RunContext[VerifyDeps],
    transfer_id: str,
    property: Property,
    documents: list[ProofDocument],
    summary: str,
    connects: Connection | None = None,
    concerns: list[Concern] | None = None,
    correction: TransferCorrection | None = None,
) -> str:
    """Record the whole verification of one transfer. Verify transfers oldest first.

    The application works out the result from what you record: any high concern, or
    a break with no missing document, makes it defective; otherwise any missing
    document makes it waiting for documents; otherwise any concern makes it verified
    with concerns; otherwise it is verified. Each missing document becomes a request
    to the buyer. Recording a transfer again replaces its record.

    Args:
        transfer_id: The transfer verified.
        property: The property as this transfer's instrument describes it.
        documents: Every document that legally proves this transfer, as you judge it:
            found (cite the passages that show it proves this transfer; an encumbrance
            certificate never proves a transfer) or missing.
        summary: One or two sentences for the buyer: what the transfer is and, for a
            concern or defect, what is wrong.
        connects: Whether the transferors are the previous transfer's acquirers. Not
            needed for the root, which is verified on its own instrument.
        concerns: Every problem in this transfer, each once, most serious first.
        correction: Details the chain recorded wrongly (parties, date, number, survey),
            supported by the found documents' citations.
    """
    deps = ctx.deps
    case = deps.case
    concerns = concerns or []
    transfer = _transfer(deps, transfer_id)
    _require(_order_problems(case, transfer))
    window = case.window()
    is_root = window.index(transfer) == 0
    checked = transfer.model_copy(deep=True)
    if correction is not None:
        updates = correction.model_dump(exclude_none=True)
        if not any(doc.status == "found" for doc in documents):
            _require(["A correction must rest on a found document's citations."])
        checked.transaction = DocumentedTransaction.model_validate(
            {**transfer.transaction.model_dump(), **updates}
        )
    problems = []
    if not documents:
        problems.append("List the documents that legally prove this transfer.")
    problems += _document_problems(deps, documents, proves_a_transfer=True)
    problems += _concern_problems(deps, concerns)
    problems += _plain("summary", summary) + _short("summary", summary, SUMMARY_MAX)
    problems += _plain("extent", property.extent)
    if not is_root and connects is None:
        problems.append("Say whether this transfer connects to the previous one (connects).")
    if connects is not None and not is_root:
        if connects.ok:
            previous = window[window.index(transfer) - 1]
            problems += connection_problems(deps.gate_context, previous, checked)
        elif not connects.note.strip():
            problems.append("A break needs a note: who is missing between which owners.")
        problems += _plain("connects.note", connects.note)
    _require(problems)

    def apply() -> None:
        transfer.transaction = checked.transaction

    if correction is not None:
        _change_chain(deps, apply)
        deps.emit("chain", f"Corrected the details of {transfer_name(transfer)}", transfer_id)
    transfer.property = property
    transfer.connects = None if is_root else connects
    transfer.documents = documents
    transfer.concerns = concerns
    transfer.summary = summary
    _file_requests(deps, transfer_id, documents)
    result = transfer_result(transfer)
    deps.emit(
        "verdict",
        f"{transfer_name(transfer).capitalize()}: {RESULT_WORDS[result]}. {summary}",
        transfer_id,
    )
    requests = [doc.request_id for doc in documents if doc.status == "missing"]
    asked = f" Requests: {', '.join(requests)}." if requests else ""
    return f"Recorded {transfer_id}: {result}.{asked}" + _digest(deps)


@case_file_tools.tool
def record_property_today(
    ctx: RunContext[VerifyDeps],
    section: SectionName,
    note: str,
    documents: list[ProofDocument],
    concerns: list[Concern] | None = None,
) -> str:
    """Record one part of the property as it stands today, after the last transfer.

    Args:
        section: encumbrances (every mortgage or charge released, the EC reaching the
            present day, attachments, pending cases), revenue_records (RTC, mutation,
            khata name the current owner) or tax_and_approvals (tax paid; conversion,
            layout and building approvals).
        note: One or two sentences for the buyer on what was found.
        documents: The documents that show it: found (cited) or missing.
        concerns: Every problem found, each once.
    """
    deps = ctx.deps
    concerns = concerns or []
    pending = [transfer.id for transfer in deps.case.window() if not transfer.recorded]
    problems = [f"Verify every transfer first: {', '.join(pending)}."] if pending else []
    problems += _document_problems(deps, documents, proves_a_transfer=False)
    problems += _concern_problems(deps, concerns)
    problems += _plain("note", note) + _short("note", note, SUMMARY_MAX)
    _require(problems)
    setattr(
        deps.case.property_today,
        section,
        Section(note=note, documents=documents, concerns=concerns),
    )
    _file_requests(deps, section, documents)
    words = (
        "in order"
        if not concerns and all(d.status == "found" for d in documents)
        else "see concerns"
    )
    deps.emit("verdict", f"{SECTION_WORDS[section]}: {words}. {note}", section)
    return f"Recorded {section}." + _digest(deps)


@case_file_tools.tool
def insert_transfer(
    ctx: RunContext[VerifyDeps],
    after_transfer_id: str | None,
    transfer: NewTransfer,
    reason: str,
    citations: list[Citation],
) -> str:
    """Add a transfer the chain is missing, e.g. a succession or partition a recital or
    history entry reports. The transfer after it must then be verified again.

    Args:
        after_transfer_id: Insert after this transfer; null to insert before the first.
        transfer: The transfer. Its sources are the cited documents.
        reason: Why the chain needs it, in one sentence for the buyer.
        citations: Passages that report the transfer.
    """
    deps = ctx.deps
    problems = ["Cite the passages that report the transfer."] if not citations else []
    problems += citation_problems(deps.gate_context, citations)
    problems += _plain("reason", reason)
    _require(problems)
    case = deps.case
    index = (
        0
        if after_transfer_id is None
        else case.transfers.index(_transfer(deps, after_transfer_id)) + 1
    )
    new = Transfer(
        id=case.next_id("VL-"),
        origin="verification",
        transaction=DocumentedTransaction(
            **transfer.model_dump(), source_refs=_source_refs(deps, citations)
        ),
        added_because=AddedBecause(note=reason, citations=citations),
    )
    _change_chain(deps, lambda: case.transfers.insert(index, new))
    deps.emit("chain", f"Added a transfer to the chain: {transfer_name(new)}. {reason}", new.id)
    _clear_next(deps, index + 1, f"{transfer_name(new)} was added before it")
    return f"Inserted {new.id}." + _digest(deps)


@case_file_tools.tool
def remove_transfer(
    ctx: RunContext[VerifyDeps], transfer_id: str, reason: str, citations: list[Citation]
) -> str:
    """Remove a transfer that is a duplicate or not a transfer of this property.

    Args:
        transfer_id: The transfer to remove.
        reason: Why it does not belong in the chain.
        citations: Passages that show it.
    """
    deps = ctx.deps
    transfer = _transfer(deps, transfer_id)
    problems = ["Cite the passages that show it does not belong."] if not citations else []
    problems += citation_problems(deps.gate_context, citations)
    problems += _plain("reason", reason)
    _require(problems)
    index = deps.case.transfers.index(transfer)
    _change_chain(deps, lambda: deps.case.transfers.remove(transfer))
    for request in deps.case.requests:
        if transfer_id in request.needed_for:
            request.needed_for.remove(transfer_id)
    _close_unneeded_requests(deps)
    deps.emit("chain", f"Removed {transfer_name(transfer)} from the chain: {reason}", transfer_id)
    _clear_next(deps, index, f"{transfer_name(transfer)} was removed before it")
    return f"Removed {transfer_id}." + _digest(deps)


@case_file_tools.tool
def set_aside(ctx: RunContext[VerifyDeps], items: list[SetAsideItem]) -> str:
    """Set aside unexpected examiner findings that do not affect title, each with a reason.
    Every other unexpected finding must be cited in a transfer or the property today.

    Args:
        items: The findings, by document and fact number, with the reason for each.
    """
    deps = ctx.deps
    open_facts = {(doc_id, number) for doc_id, number, _ in unused_unexpected(deps.case)}
    problems = []
    for item in items:
        number = item.fact.strip().upper()
        if (item.doc_id, number) not in open_facts:
            problems.append(
                f"{item.doc_id} {number} is not an unexpected finding still to follow up."
            )
        problems += _plain("reason", item.reason)
    _require(problems)
    for item in items:
        deps.case.set_aside.append(
            SetAside(doc_id=item.doc_id, fact=item.fact.strip().upper(), reason=item.reason)
        )
    deps.emit("lead", f"Set aside {len(items)} unexpected finding(s) as not affecting title", None)
    return f"Set aside {len(items)}." + _digest(deps)


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
