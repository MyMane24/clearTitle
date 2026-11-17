"""The Case File: the verification agent's durable memory and single contract.

Tools write it, gates read it, the report is written from it and the dashboard
shows it. Message history is only a log; everything the agent has established
lives here, so a run can be resumed or continued from this object alone.

To change its shape, add the field with a default, bump ``SCHEMA_VERSION`` and
add a step to ``migrate``. Older case files then still load.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.schemas.chain import DocumentedTransaction, RelatedEvent

SCHEMA_VERSION = 1

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

LinkVerdictKind = Literal[
    "verified", "verified_with_concerns", "unverified_missing_document", "defective"
]
CheckStatus = Literal["ok", "concern", "failed", "not_verifiable"]
Severity = Literal["high", "medium", "low"]
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
    quote: Text = Field(description="Exact words copied from that page of the OCR text.")


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
        """Every cited item in the report."""
        return [
            *self.instrument, *self.parties, *self.schedule, *self.consideration,
            *self.recitals, *self.encumbrances, *self.restrictions, *self.answers,
            *self.unexpected,
        ]  # fmt: skip


# -- Case state ---------------------------------------------------------------


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


class CheckResult(_Model):
    check: Text = Field(description="e.g. vendor title, extent, registration, stamp duty.")
    status: CheckStatus
    note: Text
    citations: list[Citation] = Field(default_factory=list)


class LinkVerdict(_Model):
    verdict: LinkVerdictKind
    summary: Text
    checks: list[CheckResult] = Field(min_length=1)


class WorkingLink(_Model):
    """One link of the chain being verified."""

    link_id: str
    origin: Literal["phase_a", "verification"] = "phase_a"
    continues_previous: bool
    break_note: str | None = Field(
        default=None, description="Why no recorded transfer connects this link to the previous."
    )
    transaction: DocumentedTransaction
    related_events: list[RelatedEvent] = Field(default_factory=list)
    verdict: LinkVerdict | None = None
    amendments: list[str] = Field(default_factory=list)


class Lead(_Model):
    """Something discovered that must be followed up before the case can close."""

    id: str
    text: Text
    source: Text
    status: Literal["open", "resolved"] = "open"
    outcome: Literal["evidence", "requisition", "not_material"] | None = None
    resolution: str | None = None


class Issue(_Model):
    id: str
    severity: Severity
    title: Text
    detail: Text
    link_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class Requisition(_Model):
    """A document that is needed. It records what is needed, never how it is obtained."""

    id: str
    document: Text
    reason: Text
    affects: list[str] = Field(min_length=1, description="Link, lead or issue ids.")
    status: Literal["open", "fulfilled", "resolved"] = "open"
    doc_id: str | None = None
    source: str | None = None


class Task(_Model):
    id: str
    text: Text
    status: Literal["pending", "in_progress", "done"] = "pending"


class CaseFile(_Model):
    schema_version: int = SCHEMA_VERSION
    case_id: str
    version: int = 0
    phase_a_hash: str | None = None
    property_identity: dict[str, Any] = Field(default_factory=dict)
    chain: list[WorkingLink] = Field(default_factory=list)
    documents: dict[str, DocumentEntry] = Field(default_factory=dict)
    leads: list[Lead] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    requisitions: list[Requisition] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)

    def next_id(self, prefix: str) -> str:
        """A new id such as ``L3``; never reused within this case file."""
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}{self.counters[prefix]}"

    def link(self, link_id: str) -> WorkingLink | None:
        return next((link for link in self.chain if link.link_id == link_id), None)

    def lead(self, lead_id: str) -> Lead | None:
        return next((lead for lead in self.leads if lead.id == lead_id), None)

    def requisition(self, requisition_id: str) -> Requisition | None:
        return next((item for item in self.requisitions if item.id == requisition_id), None)

    def known_ids(self) -> set[str]:
        """Every id a requisition or report may refer to."""
        return {
            *(link.link_id for link in self.chain),
            *(lead.id for lead in self.leads),
            *(issue.id for issue in self.issues),
            *(item.id for item in self.requisitions),
        }


# -- Construction and migration ----------------------------------------------


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
    chain = [
        WorkingLink(
            link_id=str(link.get("tx_id") or f"PA-{index}"),
            continues_previous=bool(link.get("continues_previous")),
            transaction=DocumentedTransaction.model_validate(link["documented_transaction"]),
            related_events=[
                RelatedEvent.model_validate(event) for event in link.get("related_events") or []
            ],
        )
        for index, link in enumerate(agent_result.get("title_chain") or [], start=1)
    ]
    return CaseFile(
        case_id=case_id,
        phase_a_hash=agent_result.get("phase_a_hash"),
        property_identity=agent_result.get("property_identity") or {},
        chain=chain,
        documents={
            document["doc_id"]: DocumentEntry(
                doc_id=document["doc_id"],
                filename=str(document.get("filename") or ""),
                document_type=str(document.get("document_type") or ""),
                summary=document.get("summary"),
            )
            for document in documents
            if document.get("status") == "structured"
        },
    )


def migrate(data: dict) -> dict:
    """Upgrade stored Case File JSON to ``SCHEMA_VERSION``, one step at a time."""
    version = int(data.get("schema_version") or 1)
    if version > SCHEMA_VERSION:
        raise ValueError(f"case file schema {version} is newer than this code ({SCHEMA_VERSION})")
    # Add one block per version, e.g.:
    # if version == 1:
    #     data = {**data, "new_field": default, "schema_version": 2}
    #     version = 2
    return data


def load(data: dict) -> CaseFile:
    """Validate stored Case File JSON, migrating it first."""
    return CaseFile.model_validate(migrate(dict(data)))
