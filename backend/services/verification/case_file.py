"""The Case File: the verification agent's durable memory and single contract.

Tools write it, gates read it, the report is written from it and the dashboard
shows it. Message history is only a log; everything the agent has established
lives here, so a run can be resumed or continued from this object alone.

Shape: one complete record per transfer (what proves it, how it connects, what
is wrong with it), the property as it stands today, and the documents. Results
and document requests are worked out by code from those records, never chosen
by the model, so they always agree with the evidence.

To change its shape, add the field with a default, bump ``SCHEMA_VERSION`` and
add a step to ``migrate``. Older case files then still load.
"""

from __future__ import annotations

import builtins
import hashlib
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.schemas.chain import DocumentedTransaction

SCHEMA_VERSION = 5

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

Severity = Literal["high", "medium", "low"]
TransferResult = Literal["verified", "verified_with_concerns", "documents_missing", "defective"]
PropertyType = Literal[
    "agricultural_land", "converted_plot", "layout_site", "house", "flat", "commercial", "other",
]  # fmt: skip
SectionName = Literal["encumbrances", "revenue_records", "tax_and_approvals"]
SECTIONS: tuple[SectionName, ...] = ("encumbrances", "revenue_records", "tax_and_approvals")
WINDOW_YEARS = 30  # how far back title is verified
PartyCapacity = Literal[
    "self", "gpa_holder", "guardian_of_minor", "legal_heir", "partner", "director",
    "trustee", "other",
]  # fmt: skip


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- Evidence -----------------------------------------------------------------


class Citation(_Model):
    """A passage on one page of one document. Gates check the quote is really there."""

    doc_id: Text
    page: int = Field(ge=1)
    quote: Text = Field(
        description="The fact's number from its examiner report (e.g. 'F3'), or exact words "
        "from the page."
    )


class Fact(_Model):
    """One cited fact taken from a document."""

    topic: Text = Field(description="Short label, e.g. 'registration number', 'extent'.")
    text: Text = Field(description="The fact in plain words.")
    page: int = Field(ge=1)
    quote: Text


class Party(_Model):
    name: Text
    role: Text = Field(description="vendor, purchaser, donor, donee, allottee, executant ...")
    capacity: PartyCapacity = "self"
    represented_by: str | None = None
    page: int = Field(ge=1)
    quote: Text


class ExaminerReport(_Model):
    """What the Document Examiner found after reading one document end to end."""

    doc_id: Text
    summary: Text
    instrument: list[Fact] = Field(
        default_factory=list,
        description="Type, registration number and date, office, stamp duty, execution.",
    )
    parties: list[Party] = Field(default_factory=list)
    schedule: list[Fact] = Field(
        default_factory=list, description="Survey/hissa, extent, boundaries, village."
    )
    consideration: list[Fact] = Field(default_factory=list)
    recitals: list[Fact] = Field(
        default_factory=list, description="Every earlier step of title the document states."
    )
    encumbrances: list[Fact] = Field(default_factory=list)
    restrictions: list[Fact] = Field(default_factory=list)
    answers: list[Fact] = Field(
        default_factory=list, description="Answers to the Lead's focus questions."
    )
    unexpected: list[Fact] = Field(
        default_factory=list,
        description="Anything outside the brief that a property lawyer would care about.",
    )

    def facts(self) -> list[Fact | Party]:
        """Every cited item in the report, in the order its fact numbers (F1, F2 ...) follow."""
        return [
            *self.instrument, *self.parties, *self.schedule, *self.consideration,
            *self.recitals, *self.encumbrances, *self.restrictions, *self.answers,
            *self.unexpected,
        ]  # fmt: skip

    def number_of(self, fact: Fact | Party) -> int:
        """The fact's number as the Lead sees it (F1 is 1)."""
        return next(i for i, item in enumerate(self.facts(), start=1) if item is fact)


class DocumentEntry(_Model):
    doc_id: str
    filename: str
    document_type: str
    summary: str | None = None
    text_hash: str | None = None
    examined: bool = False
    report: ExaminerReport | None = None
    examination_error: str | None = Field(
        default=None, description="Why the document could not be examined; a report limitation."
    )


# -- What the Lead records -----------------------------------------------------


class ProofDocument(_Model):
    """One document that legally proves part of a transfer (or of the property today)."""

    name: Text = Field(description="One document, e.g. 'registered sale deed of 2010'.")
    proves: Text = Field(description="One line: what it proves here.")
    status: Literal["found", "missing"]
    citations: list[Citation] = Field(
        default_factory=list, description="found: the passages that show it proves this."
    )
    request_id: str | None = Field(
        default=None,
        description="missing: an existing request to reuse when another record already asks "
        "for the same document. Left out, the application files a request.",
    )


class Concern(_Model):
    """A problem in a transfer or in the property today, as the Lead judged it."""

    severity: Severity = Field(
        description="high: the documents show title is not valid; medium: title is clear only "
        "once it is put right; low: an observation."
    )
    text: Text = Field(description="One or two short sentences a buyer understands.")
    citations: list[Citation] = Field(default_factory=list)


class Connection(_Model):
    """How this transfer connects to the one before it."""

    ok: bool = Field(description="true: the transferors are the previous transfer's acquirers.")
    note: str = Field(default="", description="false: who is missing between which owners.")


class Property(_Model):
    """The property as this transfer's instrument describes it."""

    survey: str | None = Field(default=None, description="Survey, hissa, site or khata number.")
    extent: str | None = None
    type: PropertyType


class AddedBecause(_Model):
    """Why the Lead inserted a transfer the Phase A chain did not have."""

    note: Text
    citations: list[Citation] = Field(min_length=1)


class Transfer(_Model):
    """One transfer of the chain and, once the Lead has verified it, its full record."""

    id: str
    origin: Literal["phase_a", "verification"] = "phase_a"
    transaction: DocumentedTransaction
    added_because: AddedBecause | None = None
    # The record, set by record_transfer; ``summary`` is None until then.
    property: Property | None = None
    connects: Connection | None = None
    documents: list[ProofDocument] = Field(default_factory=list)
    concerns: list[Concern] = Field(default_factory=list)
    summary: str | None = None

    @builtins.property  # the field "property" shadows the builtin here
    def recorded(self) -> bool:
        return self.summary is not None

    def clear_record(self) -> None:
        self.property, self.connects, self.summary = None, None, None
        self.documents, self.concerns = [], []


class Section(_Model):
    """One part of the property as it stands today."""

    note: Text
    documents: list[ProofDocument] = Field(default_factory=list)
    concerns: list[Concern] = Field(default_factory=list)


class PropertyToday(_Model):
    encumbrances: Section | None = None
    revenue_records: Section | None = None
    tax_and_approvals: Section | None = None


class Request(_Model):
    """A document asked of the buyer. Filed and closed by the application, never the Lead."""

    id: str
    document: Text
    reason: Text
    needed_for: list[str] = Field(default_factory=list, description="Transfer ids or sections.")
    status: Literal["open", "received", "settled"] = "open"
    doc_id: str | None = None
    source: str | None = None


class SetAside(_Model):
    """An unexpected examiner finding the Lead judged irrelevant to title."""

    doc_id: str
    fact: str = Field(description="Its number in the examiner report, e.g. 'F7'.")
    reason: Text


class CaseFile(_Model):
    schema_version: int = SCHEMA_VERSION
    case_id: str
    version: int = 0
    phase_a_hash: str | None = None
    transfers: list[Transfer] = Field(default_factory=list)
    property_today: PropertyToday = Field(default_factory=PropertyToday)
    requests: list[Request] = Field(default_factory=list)
    set_aside: list[SetAside] = Field(default_factory=list)
    documents: dict[str, DocumentEntry] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
    report_basis: dict[str, Any] | None = Field(
        default=None,
        description="Results and requests when the last report was written; the next report "
        "lists what changed since then.",
    )

    def next_id(self, prefix: str) -> str:
        """A new id such as ``R3``; never reused within this case file."""
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}{self.counters[prefix]}"

    def transfer(self, transfer_id: str) -> Transfer | None:
        return next((item for item in self.transfers if item.id == transfer_id), None)

    def request(self, request_id: str) -> Request | None:
        return next((item for item in self.requests if item.id == request_id), None)

    def section(self, name: str) -> Section | None:
        return getattr(self.property_today, name)

    def records(self) -> list[tuple[str, list[ProofDocument]]]:
        """Every recorded set of documents, keyed by transfer id or section name."""
        records = [(t.id, t.documents) for t in self.transfers if t.recorded]
        records += [
            (name, section.documents) for name in SECTIONS if (section := self.section(name))
        ]
        return records

    def window_start(self, this_year: int | None = None) -> int:
        """Index of the root: the latest transfer dated at or before 30 years ago.

        Title is verified from the root to the current owner. When no transfer is
        that old, the root is the earliest. Undated transfers never become the root.
        """
        cutoff = (this_year or date.today().year) - WINDOW_YEARS
        start = 0
        for index, transfer in enumerate(self.transfers):
            year = transfer_year(transfer)
            if year is not None and year <= cutoff:
                start = index
        return start

    def window(self, this_year: int | None = None) -> list[Transfer]:
        """The transfers to verify, root first."""
        return self.transfers[self.window_start(this_year) :]

    def before_root(self, transfer: Transfer) -> bool:
        return self.transfers.index(transfer) < self.window_start()


# -- Worked out by code ---------------------------------------------------------


def transfer_result(transfer: Transfer) -> TransferResult | None:
    """A recorded transfer's result, from its documents, concerns and connection.

    The legal judgment (what proves the transfer, what is wrong and how badly) is
    the Lead's; this only turns it into one word, the same way every time.
    """
    if not transfer.recorded:
        return None
    missing = any(doc.status == "missing" for doc in transfer.documents)
    broken = transfer.connects is not None and not transfer.connects.ok
    if any(c.severity == "high" for c in transfer.concerns) or (broken and not missing):
        return "defective"
    if missing:
        return "documents_missing"
    if transfer.concerns:
        return "verified_with_concerns"
    return "verified"


def section_ok(section: Section | None) -> bool | None:
    """True when a recorded section has no concern and no missing document."""
    if section is None:
        return None
    return not section.concerns and all(doc.status == "found" for doc in section.documents)


# -- Construction and migration ----------------------------------------------


def _year(text: str | None) -> int | None:
    match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", text or "")
    return int(match.group(1)) if match else None


def transfer_year(transfer: Transfer) -> int | None:
    """The year a transfer was executed (or registered), if its date names one."""
    transaction = transfer.transaction
    return _year(transaction.executed_date or transaction.registration_date)


def text_hash(text: str) -> str:
    """Fingerprint of a document's OCR text, used to reuse examiner reports."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def from_phase_a(case_id: str, agent_result: dict, documents: list[dict]) -> CaseFile:
    """Start a Case File from the saved Phase A chain and the case's documents.

    Args:
        case_id: The case.
        agent_result: The saved chain, as returned by ``agent_repo.get_agent_result``.
        documents: The case's documents, as returned by ``agent_repo.get_agent_documents``.
            Only fully processed (``structured``) documents are included.
    """
    transfers = [
        Transfer(
            id=str(link.get("tx_id") or f"PA-{index}"),
            transaction=DocumentedTransaction.model_validate(link["documented_transaction"]),
        )
        for index, link in enumerate(agent_result.get("title_chain") or [], start=1)
    ]
    return CaseFile(
        case_id=case_id,
        phase_a_hash=agent_result.get("phase_a_hash"),
        transfers=transfers,
        documents={
            document["doc_id"]: document_entry(document)
            for document in documents
            if document.get("status") == "structured"
        },
    )


def document_entry(document: dict) -> DocumentEntry:
    return DocumentEntry(
        doc_id=document["doc_id"],
        filename=str(document.get("filename") or ""),
        document_type=str(document.get("document_type") or ""),
        summary=document.get("summary"),
    )


def _root_index(transactions: list[dict]) -> int:
    """``CaseFile.window_start`` for stored transactions (used while migrating)."""
    cutoff = date.today().year - WINDOW_YEARS
    start = 0
    for index, transaction in enumerate(transactions):
        year = _year(transaction.get("executed_date") or transaction.get("registration_date"))
        if year is not None and year <= cutoff:
            start = index
    return start


def _to_v5(data: dict) -> dict:
    """Schema 4 to 5: links with verdicts, issues, leads and requisitions become one
    record per transfer plus application-filed requests.

    Each verdict's needed documents, summary and property become the record; issues
    naming one to three transfers become their concerns; a break becomes
    ``connects.ok = false``. Issues naming no transfer, summary issues naming more
    than three (the old report ignored those too) and leads are dropped: the next
    run records the property today and follows up unexpected findings again.
    """
    issues = [issue for issue in data.get("issues") or [] if len(issue.get("link_ids") or []) <= 3]
    links = data.get("chain") or []
    root = _root_index([link["transaction"] for link in links])
    transfers = []
    for index, link in enumerate(links):
        verdict = link.get("verdict") or None
        transfer: dict = {
            "id": link["link_id"],
            "origin": link.get("origin", "phase_a"),
            "transaction": link["transaction"],
        }
        if verdict:
            concerns = [
                {"severity": issue["severity"], "text": f"{issue['title']}: {issue['detail']}"}
                for issue in issues
                if link["link_id"] in (issue.get("link_ids") or [])
            ]
            kind = verdict.get("verdict")
            if kind == "defective" and not any(c["severity"] == "high" for c in concerns):
                concerns.append({"severity": "high", "text": verdict["summary"]})
            if kind == "verified_with_concerns" and not concerns:
                concerns.append({"severity": "medium", "text": verdict["summary"]})
            transfer.update(
                property={
                    "type": verdict.get("property_type") or "other",
                    "extent": verdict.get("extent"),
                },
                connects=None
                if index <= root  # the root is verified on its own instrument
                else {
                    "ok": bool(link.get("continues_previous", True)),
                    "note": link.get("break_note") or "",
                },
                documents=[
                    {
                        "name": doc["document"],
                        "proves": doc["proves"],
                        "status": doc["status"],
                        "citations": doc.get("citations") or [],
                        "request_id": doc.get("requisition_id"),
                    }
                    for doc in verdict.get("needed_documents") or []
                ],
                concerns=concerns,
                summary=verdict["summary"],
            )
        transfers.append(transfer)
    ids = {transfer["id"] for transfer in transfers}
    status = {"open": "open", "fulfilled": "received", "resolved": "settled"}
    requests = [
        {
            "id": item["id"],
            "document": item["document"],
            "reason": item["reason"],
            "needed_for": [ref for ref in item.get("affects") or [] if ref in ids],
            "status": status[item["status"]],
            "doc_id": item.get("doc_id"),
            "source": item.get("source"),
        }
        for item in data.get("requisitions") or []
        if item.get("status") in status
    ]
    kept = {
        key: value
        for key, value in data.items()
        if key not in ("chain", "issues", "leads", "requisitions")
    }
    return {**kept, "transfers": transfers, "requests": requests, "schema_version": 5}


def migrate(data: dict) -> dict:
    """Upgrade stored Case File JSON to ``SCHEMA_VERSION``, one step at a time."""
    version = int(data.get("schema_version") or 1)
    if version > SCHEMA_VERSION:
        raise ValueError(f"case file schema {version} is newer than this code ({SCHEMA_VERSION})")
    if version == 1:  # 2026-11-21: drop fields nothing read
        data = {
            key: value for key, value in data.items() if key not in ("tasks", "property_identity")
        }
        data["chain"] = [
            {
                key: value
                for key, value in link.items()
                if key not in ("amendments", "related_events")
            }
            for link in data.get("chain") or []
        ]
        data["schema_version"] = version = 2
    if version == 2:  # 2026-11-23: verdicts no longer carry a checks list
        for link in data.get("chain") or []:
            if isinstance(link.get("verdict"), dict):
                link["verdict"] = {k: v for k, v in link["verdict"].items() if k != "checks"}
        data["schema_version"] = version = 3
    if version == 3:  # 2026-11-23: no clear checks; the report finds what checked out
        data.pop("clear_checks", None)
        data["schema_version"] = version = 4
    if version == 4:  # 2026-11-23: one complete record per transfer
        data = _to_v5(data)
        version = 5
    return data


def load(data: dict) -> CaseFile:
    """Validate stored Case File JSON, migrating it first."""
    return CaseFile.model_validate(migrate(dict(data)))
