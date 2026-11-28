"""Gates: rules in code that the verification agent cannot skip.

Each gate is a small pure function that returns a list of problems (empty when
it passes). Gates are grouped in lists, so adding a rule means adding one
function to a list plus a test. A failed gate is sent back to the model, which
must fix the problem before it can continue. Gates enforce process only; what
proves a transfer is the model's judgment, guided by the playbooks.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from backend.domain.chain_continuity import (
    ENTITY_DOC_TYPES,
    entity_continuity_supported,
    names_connect,
)
from backend.schemas.chain import is_non_transfer, parse_date
from backend.services.verification.case_file import (
    SECTIONS,
    CaseFile,
    Citation,
    Fact,
    Transfer,
)
from backend.services.verification.pages import locate_quote, normalize, split_pages
from backend.shared.constants import (
    CHAIN_DEED_DOC_TYPES,
    CHAIN_HISTORY_DOC_TYPES,
    ENCUMBRANCE_CERTIFICATE,
)


@dataclass
class GateContext:
    """What gates may look at: the Case File and each document's OCR text."""

    case: CaseFile
    text_of: Callable[[str], str]


Gate = Callable[[GateContext], list[str]]


def is_deed_type(document_type: str) -> bool:
    return document_type.endswith("_DEED") or document_type in CHAIN_DEED_DOC_TYPES


# -- Similarity ---------------------------------------------------------------


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if len(word) >= 4}


def alike(title: str, detail: str, other_title: str, other_detail: str) -> bool:
    """Probably the same thing: most title words shared, or some plus much of the detail."""
    new_title, old_title = _words(title), _words(other_title)
    if not new_title or not old_title:
        return False
    shared = len(new_title & old_title) / min(len(new_title), len(old_title))
    overall = _words(f"{title} {detail}") & _words(f"{other_title} {other_detail}")
    return shared >= 0.6 or (shared >= 0.34 and len(overall) >= 6)


ACTIVE_REQUEST = ("open", "received")


def duplicate_requests(case: CaseFile) -> list[tuple[str, str]]:
    """Pairs of active requests that ask for the same document."""
    active = [item for item in case.requests if item.status in ACTIVE_REQUEST]
    return [
        (first.id, second.id)
        for index, first in enumerate(active)
        for second in active[index + 1 :]
        if alike(first.document, first.reason, second.document, second.reason)
    ]


# Text that joins several documents into one: "the deed; the Will", "set: A, B",
# "records plus the agreement", "completion and occupancy certificates", "CC, OC".
_DOCUMENT_NOUN = (
    r"(?:certificates?|deeds?|orders?|plans?|letters?|agreements?|records?|extracts?|receipts?|"
    r"reports?|statements?|affidavits?|declarations?|notices?|polic(?:y|ies)|sanctions?|approvals?|"
    r"permissions?|licen[cs]es?|registrations?|index(?:es)?|mutations?|sketch(?:es)?|maps?|cards?|"
    r"passbooks?|returns?|challans?|wills?|awards?|decrees?|judgments?|probates?|settlements?|"
    r"pattas?|khatas?|entries?|attorney|ec|rtc|cc|oc|gpa|noc)"
)
# "completion and occupancy certificates": the document word comes only at the end.
# "agreement" is left out so "sale and purchase agreement" is not read as two documents.
_QUALIFIED_DOCUMENT = (
    r"(?:certificates?|deeds?|orders?|plans?|letters?|records?|extracts?|receipts?|reports?|"
    r"statements?|affidavits?|declarations?|notices?|sanctions?|approvals?|permissions?|"
    r"licen[cs]es?|registrations?|index(?:es)?|mutations?|sketch(?:es)?|maps?|cards?|"
    r"passbooks?|returns?|challans?|wills?|awards?|decrees?|judgments?|probates?|settlements?|"
    r"pattas?|khatas?|entries?)"
)
SEVERAL_DOCUMENTS = re.compile(
    r"[;:]"
    r"|\b(?:plus|together with|along with|as well as|and any)\b"
    rf"|\b\w+\s+and\s+(?:\w+\s+){{1,3}}{_QUALIFIED_DOCUMENT}\b"
    rf"|\b{_DOCUMENT_NOUN}\b\s*,\s*(?:the\s+)?{_DOCUMENT_NOUN}\b"
    rf"|\b{_DOCUMENT_NOUN}\b.*\b(?:and|&)\b.*\b{_DOCUMENT_NOUN}\b",
    re.I,
)


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
        fact = None if page is not None else examiner_fact(entry.report, citation.quote)
        if fact is not None:
            # The Lead cited the examiner's wording of a verified fact: cite its real quote.
            citation.quote, citation.page = fact.quote, fact.page
            continue
        if page is None:
            problems.append(
                f"The quote {citation.quote[:80]!r} is not in {citation.doc_id}. "
                "Cite the fact's number (e.g. F3) or copy the exact words from the document."
            )
        elif page != citation.page:
            # OCR page markers are often missing; keep the real quote, fix its page.
            citation.page = page
    return problems


_MIN_FACT_MATCH = 12


def examiner_fact(report, quote: str):
    """The examiner fact this citation means, when the Lead cited its number ("F3") or
    quoted the fact's wording (or a truncated copy of it) instead of the document's words.

    Every fact kept in an examiner report already has a quote that was found in the
    document, so citing the fact is citing that quote.
    """
    if report is None:
        return None
    numbered = re.match(r"\s*\[?F(\d+)\b", quote, re.IGNORECASE)
    if numbered:
        facts = report.facts()
        index = int(numbered.group(1)) - 1
        return facts[index] if 0 <= index < len(facts) else None
    wanted = normalize(quote).rstrip(" .…")
    if len(wanted) < _MIN_FACT_MATCH:
        return None
    for fact in report.facts():
        for wording in (getattr(fact, "text", ""), fact.quote):
            if wanted in normalize(wording):
                return fact
    return None


def proof_problems(ctx: GateContext, citations: list[Citation]) -> list[str]:
    """An encumbrance certificate is never verification evidence for a transfer."""
    return [
        f"{citation.doc_id} is an encumbrance certificate. It can point to a transfer "
        "but cannot prove it; cite the instrument or revenue record instead."
        for citation in citations
        if (entry := ctx.case.documents.get(citation.doc_id))
        and entry.document_type == ENCUMBRANCE_CERTIFICATE
    ]


def connection_problems(ctx: GateContext, previous: Transfer, transfer: Transfer) -> list[str]:
    """A transfer said to connect must be made by the previous transfer's acquirers."""
    acquirers = previous.transaction.transferees
    transferors = transfer.transaction.transferors
    if names_connect(acquirers, transferors):
        return []
    texts = {
        doc_id: ctx.text_of(doc_id)
        for doc_id, entry in ctx.case.documents.items()
        if entry.document_type in ENTITY_DOC_TYPES and entry.examined
    }
    if entity_continuity_supported(acquirers, transferors, texts):
        return []
    return [
        f"connects.ok is true, but the transferors ({', '.join(transferors) or 'none'}) are not "
        f"the previous transfer's acquirers ({', '.join(acquirers) or 'none'}). If a death, "
        "partition or release passed title to them, insert that transfer first; if no document "
        "shows how they got it, set connects.ok to false with a note. If the parties are "
        "recorded wrongly, correct them."
    ]


# -- Chain integrity ----------------------------------------------------------


def _dates_in_order(ctx: GateContext) -> list[str]:
    latest = None
    for transfer in ctx.case.transfers:
        transaction = transfer.transaction
        dated = parse_date(transaction.executed_date or transaction.registration_date)
        if dated is None:
            continue
        if latest and dated < latest[1]:
            return [f"{transfer.id} is dated before {latest[0]}; order transfers earliest first."]
        latest = (transfer.id, dated)
    return []


def _only_transfers(ctx: GateContext) -> list[str]:
    return [
        f"{transfer.id} ({transfer.transaction.transaction_type}) is not an ownership transfer; "
        "record it as a concern instead."
        for transfer in ctx.case.transfers
        if is_non_transfer(transfer.transaction.transaction_type)
    ]


def _evidence_status_matches_sources(ctx: GateContext) -> list[str]:
    problems = []
    for transfer in ctx.case.transfers:
        transaction = transfer.transaction
        types = {
            ctx.case.documents[ref.doc_id].document_type
            for ref in transaction.source_refs
            if ref.doc_id in ctx.case.documents
        }
        cited = {ref.doc_id for ref in transaction.source_refs}
        status = transaction.evidence_status
        if status == "corroborated" and len(cited) < 2:
            problems.append(f"{transfer.id}: corroborated needs two or more source documents.")
        elif status == "register_reported" and not types & CHAIN_HISTORY_DOC_TYPES:
            problems.append(f"{transfer.id}: register_reported needs a history document.")
        elif status in {"deed_reported", "recital_reported"} and not any(
            is_deed_type(kind) for kind in types
        ):
            problems.append(f"{transfer.id}: {status} needs a title deed as a source.")
    return problems


CHAIN_GATES: list[Gate] = [_dates_in_order, _only_transfers, _evidence_status_matches_sources]


def chain_problems(ctx: GateContext) -> list[str]:
    return [problem for gate in CHAIN_GATES for problem in gate(ctx)]


# -- Unexpected findings ------------------------------------------------------


def all_citations(case: CaseFile) -> Iterator[Citation]:
    """Every citation the Lead has recorded anywhere in the Case File."""
    for transfer in case.transfers:
        if transfer.added_because:
            yield from transfer.added_because.citations
        for doc in transfer.documents:
            yield from doc.citations
        for concern in transfer.concerns:
            yield from concern.citations
    for name in SECTIONS:
        section = case.section(name)
        if section is None:
            continue
        for doc in section.documents:
            yield from doc.citations
        for concern in section.concerns:
            yield from concern.citations


def unused_unexpected(case: CaseFile) -> list[tuple[str, str, Fact]]:
    """Unexpected examiner findings neither cited anywhere nor set aside.

    Returns ``(doc_id, "F7", fact)`` for each, so nothing the examiner flagged is
    silently ignored.
    """
    cited = {(c.doc_id, normalize(c.quote)) for c in all_citations(case)}
    set_aside = {(item.doc_id, item.fact.upper()) for item in case.set_aside}
    unused = []
    for doc_id, entry in case.documents.items():
        if not entry.report:
            continue
        for fact in entry.report.unexpected:
            number = f"F{entry.report.number_of(fact)}"
            if (doc_id, normalize(fact.quote)) in cited or (doc_id, number) in set_aside:
                continue
            unused.append((doc_id, number, fact))
    return unused


# -- Closure ------------------------------------------------------------------


def unexamined_documents(case: CaseFile) -> list[str]:
    """Uploaded documents not yet examined (unreadable ones are a limitation instead)."""
    return [
        doc_id
        for doc_id, entry in case.documents.items()
        if not entry.examined and not entry.examination_error
    ]


def _every_transfer_recorded(ctx: GateContext) -> list[str]:
    """Every transfer from the root to the current owner has its record."""
    return [
        f"{transfer.id} is not verified yet; record it with record_transfer."
        for transfer in ctx.case.window()
        if not transfer.recorded
    ]


def _property_today_recorded(ctx: GateContext) -> list[str]:
    missing = [name for name in SECTIONS if ctx.case.section(name) is None]
    if not missing:
        return []
    return [
        f"The property today is not recorded for: {', '.join(missing)} (record_property_today)."
    ]


def _every_document_examined(ctx: GateContext) -> list[str]:
    docs = unexamined_documents(ctx.case)
    return [f"Documents not yet examined: {', '.join(docs)}."] if docs else []


def _received_documents_used(ctx: GateContext) -> list[str]:
    return [
        f"A document arrived for request {item.id} ({item.document} -> {item.doc_id}). Examine "
        f"it, then record again: {', '.join(item.needed_for)}."
        for item in ctx.case.requests
        if item.status == "received"
    ]


def _no_duplicate_requests(ctx: GateContext) -> list[str]:
    return [
        f"Requests {first} and {second} ask for the same document. Record again the transfers "
        f"that list {second}, giving request_id {first} for that missing document."
        for first, second in duplicate_requests(ctx.case)
    ]


def _unexpected_followed_up(ctx: GateContext) -> list[str]:
    return [
        f"Unexpected finding {doc_id} {number} ({fact.text[:100]}) is not followed up: cite it in "
        "a transfer or the property today, or set_aside it with a reason."
        for doc_id, number, fact in unused_unexpected(ctx.case)
    ]


CLOSURE_GATES: list[Gate] = [
    chain_problems,
    _every_document_examined,
    _every_transfer_recorded,
    _property_today_recorded,
    _received_documents_used,
    _no_duplicate_requests,
    _unexpected_followed_up,
]


def closure_problems(ctx: GateContext) -> list[str]:
    return [problem for gate in CLOSURE_GATES for problem in gate(ctx)]
