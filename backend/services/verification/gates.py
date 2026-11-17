"""Gates: rules in code that the verification agent cannot skip.

Each gate is a small pure function that returns a list of problems (empty when
it passes). Gates are grouped in lists, so adding a rule means adding one
function to a list plus a test. A failed gate is sent back to the model, which
must fix the problem before it can continue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from backend.domain.chain_continuity import (
    ENTITY_DOC_TYPES,
    entity_continuity_supported,
    names_connect,
)
from backend.schemas.chain import is_non_transfer, parse_date
from backend.services.verification.case_file import CaseFile, Citation
from backend.services.verification.pages import locate_quote, split_pages
from backend.shared.constants import (
    CHAIN_DEED_DOC_TYPES,
    CHAIN_HISTORY_DOC_TYPES,
    ENCUMBRANCE_CERTIFICATE,
)


class GateError(ValueError):
    """A gate failed. The message tells the model what to fix."""


@dataclass
class GateContext:
    """What gates may look at: the Case File and each document's OCR text."""

    case: CaseFile
    text_of: Callable[[str], str]


Gate = Callable[[GateContext], list[str]]


def raise_if(problems: list[str]) -> None:
    """Raise one GateError listing every problem, if there are any."""
    if problems:
        raise GateError("Fix before continuing:\n- " + "\n- ".join(problems))


def is_deed_type(document_type: str) -> bool:
    return document_type.endswith("_DEED") or document_type in CHAIN_DEED_DOC_TYPES


# -- Evidence -----------------------------------------------------------------


def citation_problems(ctx: GateContext, citations: list[Citation]) -> list[str]:
    """Each citation must quote a page of a document examined end to end."""
    problems = []
    for citation in citations:
        entry = ctx.case.documents.get(citation.doc_id)
        if entry is None:
            problems.append(f"{citation.doc_id} is not a document of this case.")
            continue
        if not entry.examined:
            problems.append(
                f"{citation.doc_id} has not been examined end to end; examine it before citing it."
            )
            continue
        pages = split_pages(ctx.text_of(citation.doc_id))
        page = locate_quote(citation.quote, pages, citation.page)
        if page is None:
            problems.append(
                f"The quote {citation.quote[:80]!r} is not in {citation.doc_id}. "
                "Copy the exact words from the document."
            )
        elif page != citation.page:
            # OCR page markers are often missing; keep the real quote, fix its page.
            citation.page = page
    return problems


def link_evidence_problems(ctx: GateContext, citations: list[Citation]) -> list[str]:
    """An encumbrance certificate is never verification evidence for a transfer."""
    return [
        f"{citation.doc_id} is an encumbrance certificate. It can point to a transfer "
        "but cannot verify it; cite the instrument or revenue record instead."
        for citation in citations
        if (entry := ctx.case.documents.get(citation.doc_id))
        and entry.document_type == ENCUMBRANCE_CERTIFICATE
    ]


# -- Chain integrity ----------------------------------------------------------


def _first_link_does_not_continue(ctx: GateContext) -> list[str]:
    chain = ctx.case.chain
    if chain and chain[0].continues_previous:
        return [f"{chain[0].link_id} is the earliest link; it cannot continue a previous one."]
    return []


def _continuing_links_connect(ctx: GateContext) -> list[str]:
    problems = []
    chain = ctx.case.chain
    for previous, link in pairwise(chain):
        if not link.continues_previous:
            continue
        acquirers = previous.transaction.transferees
        transferors = link.transaction.transferors
        if names_connect(acquirers, transferors):
            continue
        if entity_continuity_supported(acquirers, transferors, _constitution_texts(ctx)):
            continue
        problems.append(
            f"{link.link_id} claims to continue {previous.link_id}, but its transferors "
            f"({', '.join(transferors)}) are not {previous.link_id}'s acquirers "
            f"({', '.join(acquirers)}). Insert the connecting transfer, or mark a break."
        )
    return problems


def _constitution_texts(ctx: GateContext) -> dict[str, str]:
    return {
        doc_id: ctx.text_of(doc_id)
        for doc_id, entry in ctx.case.documents.items()
        if entry.document_type in ENTITY_DOC_TYPES and entry.examined
    }


def _dates_in_order(ctx: GateContext) -> list[str]:
    latest = None
    for link in ctx.case.chain:
        transaction = link.transaction
        dated = parse_date(transaction.executed_date or transaction.registration_date)
        if dated is None:
            continue
        if latest and dated < latest[1]:
            return [f"{link.link_id} is dated before {latest[0]}; order links earliest first."]
        latest = (link.link_id, dated)
    return []


def _only_transfers(ctx: GateContext) -> list[str]:
    return [
        f"{link.link_id} ({link.transaction.transaction_type}) is not an ownership transfer; "
        "record it as a related event or an issue instead."
        for link in ctx.case.chain
        if is_non_transfer(link.transaction.transaction_type)
    ]


def _evidence_status_matches_sources(ctx: GateContext) -> list[str]:
    problems = []
    for link in ctx.case.chain:
        transaction = link.transaction
        types = {
            ctx.case.documents[ref.doc_id].document_type
            for ref in transaction.source_refs
            if ref.doc_id in ctx.case.documents
        }
        cited = {ref.doc_id for ref in transaction.source_refs}
        status = transaction.evidence_status
        if status == "corroborated" and len(cited) < 2:
            problems.append(f"{link.link_id}: corroborated needs two or more source documents.")
        elif status == "register_reported" and not types & CHAIN_HISTORY_DOC_TYPES:
            problems.append(f"{link.link_id}: register_reported needs a history document.")
        elif status in {"deed_reported", "recital_reported"} and not any(
            is_deed_type(kind) for kind in types
        ):
            problems.append(f"{link.link_id}: {status} needs a title deed as a source.")
    return problems


CHAIN_GATES: list[Gate] = [
    _first_link_does_not_continue,
    _continuing_links_connect,
    _dates_in_order,
    _only_transfers,
    _evidence_status_matches_sources,
]


def chain_problems(ctx: GateContext) -> list[str]:
    return [problem for gate in CHAIN_GATES for problem in gate(ctx)]


# -- Closure ------------------------------------------------------------------


def _every_link_has_a_verdict(ctx: GateContext) -> list[str]:
    return [
        f"{link.link_id} has no verdict; record one with record_link_verdict."
        for link in ctx.case.chain
        if link.verdict is None
    ]


def _every_break_is_recorded(ctx: GateContext) -> list[str]:
    return [
        f"{link.link_id} does not continue the previous link and no break is recorded. "
        "Insert the connecting transfer, or mark the break with its reason."
        for link in ctx.case.chain[1:]
        if not link.continues_previous and not link.break_note
    ]


def _no_open_leads(ctx: GateContext) -> list[str]:
    return [
        f"Lead {lead.id} is open: {lead.text}. Resolve it with evidence, a requisition, "
        "or a reason it does not affect title."
        for lead in ctx.case.leads
        if lead.status == "open"
    ]


def _every_document_examined(ctx: GateContext) -> list[str]:
    unexamined = [
        doc_id
        for doc_id, entry in ctx.case.documents.items()
        if not entry.examined and not entry.examination_error
    ]
    return [f"Not yet examined: {', '.join(unexamined)}."] if unexamined else []


def _requisitions_name_what_they_affect(ctx: GateContext) -> list[str]:
    known = ctx.case.known_ids()
    return [
        f"Requisition {item.id} refers to unknown ids: {', '.join(sorted(set(item.affects) - known))}."
        for item in ctx.case.requisitions
        if set(item.affects) - known
    ]


def _missing_document_verdicts_have_requisitions(ctx: GateContext) -> list[str]:
    requested = {
        target for item in ctx.case.requisitions if item.status == "open" for target in item.affects
    }
    return [
        f"{link.link_id} is unverified for a missing document, but no open requisition "
        "names it. Add the requisition."
        for link in ctx.case.chain
        if link.verdict
        and link.verdict.verdict == "unverified_missing_document"
        and link.link_id not in requested
    ]


def _arrived_documents_reviewed(ctx: GateContext) -> list[str]:
    return [
        f"A document arrived for requisition {item.id} ({item.doc_id}); examine it and "
        "call review_requisition."
        for item in ctx.case.requisitions
        if item.status == "fulfilled"
    ]


CLOSURE_GATES: list[Gate] = [
    chain_problems,
    _every_link_has_a_verdict,
    _every_break_is_recorded,
    _no_open_leads,
    _every_document_examined,
    _requisitions_name_what_they_affect,
    _missing_document_verdicts_have_requisitions,
    _arrived_documents_reviewed,
]


def closure_problems(ctx: GateContext) -> list[str]:
    return [problem for gate in CLOSURE_GATES for problem in gate(ctx)]
