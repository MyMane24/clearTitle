"""Canonical analysis-layer contracts (target architecture, Stage 1).

Single source of truth for the contracts introduced by the ClearTitle
redesign (docs/architecture/CLEARTITLE_TARGET_ARCHITECTURE.md §4):

* shared provenance + evidence-reference primitives,
* Phase A identity/chain canonical shapes,
* evidence requirements with stable identities (Stage 4 consumers).

`backend.services.agent_schemas` stays the Phase A/B *persistence* contract:
its existing v3.0 wire shapes are preserved; later stages validate against,
or additively extend, the models defined here. Free-form LLM output must
never reach persistence without passing one of these models first.

Identifier discipline (application-assigned only — never trusted from a
model): PA-TC-\\d{4} transactions and REQ-\\d{4} evidence requirements.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ANALYSIS_CONTRACT_VERSION = "1.0"

TX_ID_RE = r"PA-TC-\d{4}"
# Per-dossier (Phase B) finding reference. A 4th digit exists only so
# allocation never fails a save after 999 findings; pre-existing TF-### ids
# are unchanged.
TX_FINDING_ID_RE = r"TF-\d{3,4}"

# Application-assigned transaction identifiers that are allowed to survive
# renumbering: the current PA-TC ids plus LEGACY-* assignments made at the
# legacy read boundary. Any id a model supplies by itself is foreign.
ASSIGNED_TX_ID_PATTERN = re.compile(r"^(?:PA-TC-\d{4}|LEGACY-.+)$")


def is_assigned_tx_id(value: object) -> bool:
    """True only for application-assigned transaction identifiers."""
    return isinstance(value, str) and bool(ASSIGNED_TX_ID_PATTERN.match(value))


def content_hash(payload: object) -> str:
    """Deterministic sha256 over canonical JSON (sorted keys, no extra space)."""
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def phase_a_hash(payload: object) -> str:
    """Stable sha256 over canonical ``property_identity`` + ``title_chain``.

    Hash integrity is about the structured chain, so prose (``title_chain_graph``)
    and any unrelated/app-owned keys are excluded. Deterministic: only the content
    of those two keys (canonical JSON, sorted keys) participates.
    """
    data = payload if isinstance(payload, dict) else {}
    return content_hash({
        "property_identity": data.get("property_identity"),
        "title_chain": data.get("title_chain"),
    })


def new_tx_finding_id(sequence: int) -> str:
    """App-assigned dossier-finding reference (TF-001 / TF-1000 style), per case.

    Width-3 through TF-999 keeps every historical id byte-identical; 1000-9999
    render at natural width so exhausting the three-digit counter degrades to
    four-digit ids instead of failing the save.
    """
    if sequence < 1 or sequence > 9999:
        raise ValueError(f"transaction finding sequence out of range: {sequence}")
    return f"TF-{sequence:03d}" if sequence <= 999 else f"TF-{sequence}"


# -- controlled enumerations ----------------------------------------------------


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TransferCategory(str, Enum):
    """Coarse Stage-5 correlation category over Phase A entry types."""

    TRANSFER = "TRANSFER"
    EVENT = "EVENT"
    ENCUMBRANCE = "ENCUMBRANCE"
    CONVERSION = "CONVERSION"
    OTHER = "OTHER"


class EntrySourceKind(str, Enum):
    """How a Phase A entry is known: examined instrument vs recital vs inference."""

    DOCUMENT = "DOCUMENT"
    RECITAL = "RECITAL"
    INFERRED = "INFERRED"


class Significance(str, Enum):
    """Verification dimension of a dossier finding (evidence-grounded only)."""

    ESTABLISHED = "ESTABLISHED"
    SUPPORTED = "SUPPORTED"
    CONTESTED = "CONTESTED"
    UNRESOLVED = "UNRESOLVED"


class FindingCategory(str, Enum):
    PROPERTY_IDENTITY = "property_identity"
    REGISTRATION = "registration"
    AUTHORITY = "authority"
    ENCUMBRANCE = "encumbrance"
    LIABILITY = "liability"
    CONVERSION = "conversion"
    BUILDING = "building"
    LITIGATION = "litigation"
    CHAIN_GAP = "chain_gap"
    OTHER = "other"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    CAUTION = "CAUTION"
    POSITIVE = "POSITIVE"
    INFORMATION = "INFORMATION"


class PropertyFindingStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"
    # Additive members; persisted findings carrying these values keep validating.
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    DISPUTED = "DISPUTED"


class RunPhaseLabel(str, Enum):
    A = "A"
    B = "B"


class RunPhaseStatus(str, Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


# -- shared primitives ----------------------------------------------------------


class Provenance(BaseModel):
    """Traceability carried by every persisted analysis artifact."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = ANALYSIS_CONTRACT_VERSION
    run_id: str | None = Field(default=None, description="AnalysisRunMetadata.run_id when known.")
    model: str | None = None
    prompt_version: str | None = None
    created_at: str | None = None


class DocumentEvidenceReference(BaseModel):
    """A document (and optional page/range or quoted passage) cited as evidence."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(description="Existing uploaded document ID; the application verifies it exists.")
    filename: str | None = None
    pages: str | None = Field(default=None, description="Observed page/range only; do not invent.")
    passage: str | None = None
    evidence_type: str | None = Field(
        default=None,
        description="What kind of evidence this is (original_instrument, recital, register_extract, …).",
    )
    relation: Literal["supports", "contradicts", "contextualizes"] | None = Field(
        default=None,
        description="How the reference relates to the finding it accompanies.",
    )

    @model_validator(mode="after")
    def check_doc_id(self):
        if not self.doc_id.strip():
            raise ValueError("doc_id must not be empty")
        return self


class SourceHashes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_a: str | None = None
    case_result: str | None = None
    findings: str | None = None


# -- dossier scope + dimensions (Phase B, additive) -------------------------------


class DossierScope(BaseModel):
    """What the dossier was verified against — app-assigned, never model-sent."""

    model_config = ConfigDict(extra="forbid")

    phase_a_hash: str | None = Field(
        default=None, description="phase_a_hash of the chain at verification time."
    )
    chain_context_hash: str | None = Field(
        default=None,
        description="Hash of the persisted upstream chain-context record (None for the root).",
    )


class EffectivityStatus(str, Enum):
    """How far a dossier examined the evidence it selected."""

    NOT_EXAMINED = "NOT_EXAMINED"
    PARTIALLY_EXAMINED = "PARTIALLY_EXAMINED"
    FULLY_EXAMINED = "FULLY_EXAMINED"
    EXAMINED_UNVERIFIED = "EXAMINED_UNVERIFIED"


class EvidenceBasis(str, Enum):
    """Aggregate basis of a dossier's statements: instruments vs recitals."""

    DIRECT = "DIRECT"
    RECITAL = "RECITAL"
    MIXED = "MIXED"
    UNDETERMINED = "UNDETERMINED"


# -- Phase A canonical shapes ----------------------------------------------------


class PropertyIdentityDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    source_refs: list[DocumentEvidenceReference] = Field(min_length=1)
    confidence: ConfidenceLevel | None = None


class PropertyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    details: list[PropertyIdentityDetail] = Field(min_length=1)
    unresolved: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class TitleChainEvent(BaseModel):
    """Related property event recorded from evidence (mutation, EC entry, layout order, …)."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    date: str | None = None
    parties: list[str] = Field(default_factory=list)
    source_refs: list[DocumentEvidenceReference] = Field(default_factory=list)
    is_inferred: bool = False


class TitleChainEntry(BaseModel):
    """Canonical Phase A chain link (flat form; persistence keeps the nested
    `documented_transaction` wire shape — Stage 2 bridges on save)"""

    model_config = ConfigDict(extra="forbid")

    tx_id: str = Field(pattern=TX_ID_RE, description="Application-assigned; never model-generated.")
    sequence: int = Field(ge=1)
    transaction_type: str
    category: TransferCategory | None = None

    transferors: list[str] = Field(default_factory=list)
    transferees: list[str] = Field(default_factory=list)
    executed_date: str | None = None
    registration_date: str | None = None
    registration_number: str | None = None

    property_type: str | None = Field(
        default=None, description="Kind of property this link transfers (e.g. Agricultural land, Open plot, Apartment unit)."
    )
    survey_number: str | None = None
    plot_number: str | None = None
    site_flat_number: str | None = None
    cts_number: str | None = None
    parent_survey_number: str | None = Field(
        default=None, description="Parent R.S. parcel; divergent subdivisions stay explicit."
    )

    schedule_description: str | None = None
    extent: str | None = None
    consideration: str | None = None
    registration_office: str | None = Field(
        default=None, description="Sub-registrar / registration office stated by the instrument or its record."
    )

    source: EntrySourceKind = EntrySourceKind.DOCUMENT
    source_doc_ids: list[str] = Field(min_length=1)
    recital_references: list[str] = Field(
        default_factory=list,
        description="Historical instruments known only through recitals — never evidence.",
    )
    related_events: list[TitleChainEvent] = Field(default_factory=list)
    upstream_tx_ids: list[str] = Field(
        default_factory=list,
        description="Application-stamped links to earlier chain entries this transfer continues (empty when the chain link is unsupported)."
    )
    confidence: ConfidenceLevel | None = None
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_upstream_ids(self):
        for tx_id in self.upstream_tx_ids:
            if not re.fullmatch(TX_ID_RE, tx_id):
                raise ValueError(f"upstream_tx_ids carries an invalid transaction ID: {tx_id!r}")
        return self


# -- verification dossier dimensions (Phase B, additive) ---------------------------


class VerificationFinding(BaseModel):
    """One evidence-grounded verification observation inside a dossier.

    ``finding_id`` and ``transaction_id`` are application-stamped at save time
    (never trusted from a model output); ``finding_id`` stays stable for the
    same content identity across dossier updates.
    """

    model_config = ConfigDict(extra="forbid")

    significance: Significance
    category: FindingCategory = FindingCategory.OTHER
    title: str = Field(max_length=120)
    text: str
    evidence: list[DocumentEvidenceReference] = Field(default_factory=list)
    is_legal_defect: bool = False
    severity: Severity = Severity.INFORMATION
    status: PropertyFindingStatus = PropertyFindingStatus.OPEN
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    finding_id: str = Field(
        default="",
        description="TF-nnn, assigned by the application; must not be set by the model.",
    )
    transaction_id: str = Field(
        default="",
        description="Owning transaction; stamped by the application = the dossier's tx_id.",
    )
    affected_parties: list[str] = Field(default_factory=list)
    legal_or_property_implication: str | None = Field(
        default=None,
        description="Why the finding matters for title or the property — grounded in the cited facts.",
    )
    recommended_action: str | None = None
    resolution_evidence: list[DocumentEvidenceReference] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(
        default_factory=list,
        description="When no evidence reference can be cited: the records whose absence is the gap.",
    )

    @model_validator(mode="after")
    def check_finding_grounding(self):
        if not self.text.strip():
            raise ValueError("finding text must not be empty")
        if self.significance in {Significance.ESTABLISHED, Significance.SUPPORTED} and not self.evidence:
            raise ValueError(f"{self.significance.value} findings require at least one evidence reference")
        if self.is_legal_defect and self.significance is Significance.UNRESOLVED:
            raise ValueError("an UNRESOLVED finding cannot assert a legal defect")
        if self.finding_id and not re.fullmatch(TX_FINDING_ID_RE, self.finding_id):
            raise ValueError(f"finding_id must match {TX_FINDING_ID_RE} when supplied: {self.finding_id!r}")
        if self.transaction_id and not re.fullmatch(TX_ID_RE, self.transaction_id):
            raise ValueError(f"transaction_id must match {TX_ID_RE} when supplied: {self.transaction_id!r}")
        if self.status is PropertyFindingStatus.RESOLVED and not self.resolution_evidence:
            raise ValueError("a RESOLVED finding requires resolution evidence")
        if self.severity is Severity.CRITICAL and not (
            self.legal_or_property_implication and self.evidence
        ):
            raise ValueError(
                "a CRITICAL finding requires cited evidence and a defect-grounded implication; "
                "missing evidence alone is never a defect"
            )
        return self


# -- run metadata ----------------------------------------------------------------------


class AnalysisRunPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: RunPhaseLabel
    status: RunPhaseStatus
    model: str | None = None
    prompt_version: str | None = None


class AnalysisRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=8, description="Application-assigned UUID for this agent run.")
    case_id: str = Field(min_length=1)
    started_at: str
    finished_at: str | None = None
    phases: list[AnalysisRunPhase] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "ANALYSIS_CONTRACT_VERSION",
    "AnalysisRunMetadata",
    "AnalysisRunPhase",
    "ASSIGNED_TX_ID_PATTERN",
    "ConfidenceLevel",
    "DocumentEvidenceReference",
    "DossierScope",
    "EffectivityStatus",
    "EntrySourceKind",
    "EvidenceBasis",
    "FindingCategory",
    "PropertyFindingStatus",
    "PropertyIdentity",
    "PropertyIdentityDetail",
    "Provenance",
    "RunPhaseLabel",
    "RunPhaseStatus",
    "Severity",
    "Significance",
    "SourceHashes",
    "TitleChainEntry",
    "TitleChainEvent",
    "TransferCategory",
    "TX_FINDING_ID_RE",
    "TX_ID_RE",
    "VerificationFinding",
    "content_hash",
    "is_assigned_tx_id",
    "new_tx_finding_id",
    "phase_a_hash",
]
