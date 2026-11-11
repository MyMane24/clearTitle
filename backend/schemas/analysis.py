"""Canonical analysis-layer contracts (target architecture, Stage 1).

Single source of truth for the contracts introduced by the ClearTitle
redesign (docs/architecture/CLEARTITLE_TARGET_ARCHITECTURE.md §4):

* shared provenance + evidence-reference primitives,
* Phase A identity/chain canonical shapes,
* evidence requirements with stable identities (Stage 4 consumers),
* property-level consolidation (Phase C) and final opinion (Phase D).

`backend.services.agent_schemas` stays the Phase A/B *persistence* contract:
its existing v3.0 wire shapes are preserved; later stages validate against,
or additively extend, the models defined here. Free-form LLM output must
never reach persistence without passing one of these models first.

Identifier discipline (application-assigned only — never trusted from a
model): PA-TC-\\d{4} transactions, REQ-\\d{4} evidence requirements,
PF-\\d{3} property findings.
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
REQUIREMENT_ID_RE = r"REQ-\d{4}"
FINDING_ID_RE = r"PF-\d{3}"
# Per-dossier (Phase B) finding reference: distinct from the property-level PF- ids
# of consolidated findings so the two layers cannot be confused. A 4th digit exists
# only so allocation never fails a save after 999 distinct case findings;
# pre-existing TF-### ids are unchanged.
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


def new_requirement_id(sequence: int) -> str:
    """REQ-0001 style; `sequence` is the next app-assigned number for a case."""
    if sequence < 1 or sequence > 9999:
        raise ValueError(f"requirement sequence out of range: {sequence}")
    return f"REQ-{sequence:04d}"


def new_finding_id(sequence: int) -> str:
    if sequence < 1 or sequence > 999:
        raise ValueError(f"finding sequence out of range: {sequence}")
    return f"PF-{sequence:03d}"


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


class RequirementStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    AMBIGUOUS = "AMBIGUOUS"


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
    # Additive per C2 (§4.9); the §6.2 transition wiring applies them as of C3
    # (PENDING_EVIDENCE via the ladder, DISPUTED at birth/carried via records).
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    DISPUTED = "DISPUTED"


class PropertyEvidenceSufficiency(str, Enum):
    """Evidence-dimension label, separate from lifecycle status (§6.1)."""

    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNVERIFIABLE = "UNVERIFIABLE"


class OpinionVerdict(str, Enum):
    CLEAR_CONFIRMED = "CLEAR_CONFIRMED"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    NOT_VERIFIED = "NOT_VERIFIED"


class OpinionType(str, Enum):
    FINAL = "FINAL"
    PRELIMINARY = "PRELIMINARY"


class RunPhaseLabel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


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


# -- evidence requirements (stable identity) --------------------------------------


class RequirementMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: MatchStatus
    doc_id: str | None = None
    evidence_refs: list[DocumentEvidenceReference] = Field(default_factory=list)
    note: str | None = None


class EvidenceRequirement(BaseModel):
    """One requested document with a stable identity owned by one transaction."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=REQUIREMENT_ID_RE, description="Application-assigned.")
    owner_tx_id: str | None = Field(
        default=None,
        pattern=TX_ID_RE,
        description="Transaction that asked for this evidence, when known.",
    )
    document_type: str
    reason: str | None = None
    what_it_establishes: str | None = None
    status: RequirementStatus = RequirementStatus.OPEN
    match: RequirementMatch | None = None

    @model_validator(mode="after")
    def check_open_owner(self):
        if self.status is RequirementStatus.OPEN and not self.owner_tx_id:
            raise ValueError("an OPEN requirement must carry its owning transaction")
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


# -- Phase C consolidation ----------------------------------------------------------


class FindingLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tx_id: str = Field(pattern=TX_ID_RE)
    finding_index: int | None = Field(default=None, ge=0)
    finding_id: str | None = Field(
        default=None,
        description="Stable per-save TF-### reference alongside the positional fallback (§4.9).",
    )


class SourceObservation(BaseModel):
    """Immutable per-observation provenance persisted with a finding (§4.8).

    ``observed_in`` records the exact input hash that observed the source,
    ``revision``/``verified_at`` stay at their defaults until the repository
    persists per-tx save counters/clock values for them (no invention).
    """

    model_config = ConfigDict(extra="forbid")

    tf_id: str = Field(pattern=TX_FINDING_ID_RE, description="Application-assigned TF id at its source dossier.")
    tx_id: str = Field(pattern=TX_ID_RE)
    title: str = ""
    text_excerpt: str | None = None
    evidence_refs: list[DocumentEvidenceReference] = Field(default_factory=list)
    observed_in: str = ""
    revision: int = 0
    verified_at: str | None = None


class TransitionEvent(BaseModel):
    """One lifecycle/audit event, app-written only (D5, D6).

    Wire shape ``{at, from, to, reason, refs[], decided_by}`` (§6.2); serialized
    forms use ``from_status``/``to_status`` keys.
    """

    model_config = ConfigDict(extra="forbid")

    at: str
    from_status: str | None = Field(default=None)
    to_status: str | None = Field(default=None)
    reason: str = ""
    refs: list[str] = Field(
        default_factory=list,
        description="Related identifiers (PF/TF/tx) or entries like ``doc_id#pages``.",
    )
    decided_by: str = ""


class Correlation(BaseModel):
    """Related-but-not-same record (§9). Declared additively in C2, persisted
    from C3; field names follow the §8.1 wire shape (``type``/``from_pf``/
    ``to_pf``/``rationale``/``determined_by``). Edges are rebuilt every ok run
    and never feed the input hash."""

    model_config = ConfigDict(extra="forbid")

    type: str = Literal[
        "RELATED", "DEPENDS_ON", "CONFLICTS_WITH", "MERGED_INTO", "SPLIT_FROM",
    ]
    from_pf: str
    to_pf: str | None = Field(
        default=None,
        description="Container-level edges (DEPENDS_ON) may omit the target finding.",
    )
    rationale: str = ""
    determined_by: str = "deterministic"


class RequirementsDigest(BaseModel):
    """Requirement-ledger counts by status (§8.1 coverage block)."""

    model_config = ConfigDict(extra="forbid")

    open: int = 0
    satisfied: int = 0
    withdrawn: int = 0


class CoverageDossier(BaseModel):
    """One strictly-read transaction row in the coverage block (§8.1)."""

    model_config = ConfigDict(extra="forbid")

    tx_id: str = Field(pattern=TX_ID_RE)
    revision: int = 0
    status: str | None = None
    terminal: bool = False


class Coverage(BaseModel):
    """What the findings set actually covers (§7.2/§8.1)."""

    model_config = ConfigDict(extra="forbid")

    phase_a_hash: str | None = None
    dossiers: list[CoverageDossier] = Field(default_factory=list)
    requirements: RequirementsDigest = Field(default_factory=RequirementsDigest)
    input_snapshot: dict = Field(default_factory=dict)
    chain_length: int = 0


class Integrity(BaseModel):
    """Materialized run-integrity registers (§8.1 — Option B, from C3)."""

    model_config = ConfigDict(extra="forbid")

    input_state: str | None = None
    malformed_observations: list = Field(default_factory=list)
    excluded_evidence_refs: list = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)


class Readiness(BaseModel):
    """Container-level readiness statement (§7.2)."""

    model_config = ConfigDict(extra="forbid")

    state: str = Literal["COMPLETE", "PARTIAL"]
    pending_tx_ids: list[str] = Field(default_factory=list)
    skipped_tx_ids: list[str] = Field(default_factory=list)
    unverified_tx_ids: list[str] = Field(default_factory=list)
    open_requirement_ids: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    """Cross-transaction contradiction surfaced by Phase C."""

    model_config = ConfigDict(extra="forbid")

    description: str
    sides: list[FindingLink] = Field(min_length=2)
    severity: Severity = Severity.CAUTION
    resolution_guidance: str | None = None
    contradiction_key: str | None = Field(
        default=None,
        description="Deterministic content key (normalized description + sorted sides); reruns refresh, never duplicate (§5.1-5).",
    )
    related_pf_ids: list[str] = Field(default_factory=list)


class ConsolidationProvenance(Provenance):
    model_config = ConfigDict(extra="forbid")

    phase_a_hash: str | None = None
    dossier_refs: list[FindingLink] = Field(default_factory=list)
    source_hashes: SourceHashes | None = None
    dedup_keys: list[str] = Field(
        default_factory=list,
        description="Application-assigned content-identity keys of the consolidated sources.",
    )


class PropertyFinding(BaseModel):
    """One consolidated, property-level finding behind one stable ID."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(pattern=FINDING_ID_RE, description="Application-assigned.")
    category: FindingCategory
    title: str = Field(max_length=120)
    description: str
    severity: Severity
    status: PropertyFindingStatus = PropertyFindingStatus.OPEN
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    affected_tx_ids: list[str] = Field(default_factory=list)
    documents: list[DocumentEvidenceReference] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    implication: str | None = Field(
        default=None,
        description="Why the finding matters — grounded in sourced facts, never invented.",
    )
    required_customer_action: str | None = None
    resolution_evidence: list[DocumentEvidenceReference] = Field(default_factory=list)
    consolidation: ConsolidationProvenance | None = None
    # Additive C2 identity/lifecycle contract (§4.9, OD-1 subset). All fields
    # default so persisted v1 containers keep validating (no DDL, no migration).
    identity_key: str | None = Field(
        default=None,
        description="Canonical v2 identity key: A|… / B|… / M|sha256, app-derived only.",
    )
    identity_basis: str | None = None  # anchors | textual | model_merge
    identity_confidence: ConfidenceLevel | None = None
    identity_missing_attributes: list[str] = Field(default_factory=list)
    identity_supporting: list[str] = Field(default_factory=list)
    source_observations: list[SourceObservation] = Field(default_factory=list)
    lifecycle_events: list[TransitionEvent] = Field(default_factory=list)
    superseede_reason: str | None = Field(
        default=None,
        description="Set only when status is SUPERSEDED: de_observed | merged_into:<PF-xxx> | split_replaced.",
    )
    evidence_sufficiency: PropertyEvidenceSufficiency | None = Field(
        default=None,
        description="Evidence dimension, app-derived; UNVERIFIABLE is reserved (§6.1).",
    )

    @model_validator(mode="after")
    def check_finding_lifecycle(self):
        if not self.description.strip():
            raise ValueError("finding description must not be empty")
        if self.status is PropertyFindingStatus.RESOLVED and not self.resolution_evidence:
            raise ValueError("a RESOLVED finding requires resolution evidence")
        for tx_id in self.affected_tx_ids:
            if not re.fullmatch(TX_ID_RE, tx_id):
                raise ValueError(f"affected_tx_ids carries an invalid transaction ID: {tx_id!r}")
        if self.severity is Severity.CRITICAL and not (self.implication and self.documents):
            raise ValueError(
                "a CRITICAL finding requires sourced document evidence and a "
                "defect-grounded implication; missing evidence alone is never a defect"
            )
        return self


class FindingDraft(BaseModel):
    """Model-proposed consolidation group (Phase C); the application assembles
    identity, affected transactions, document coverage, and provenance."""

    model_config = ConfigDict(extra="forbid")

    members: list[int] = Field(
        min_length=1,
        description="Candidate indexes into the deterministic candidate list (>= 1; empty groups are refused, §6-D5a).",
    )
    category: FindingCategory = FindingCategory.OTHER
    title: str = Field(max_length=120)
    description: str
    severity: Severity = Severity.CAUTION
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    implication: str | None = None
    required_customer_action: str | None = None
    evidence_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_draft(self):
        if not self.description.strip():
            raise ValueError("draft description must not be empty")
        if not self.title.strip():
            raise ValueError("draft title must not be empty")
        for index in self.members:
            if index < 0:
                raise ValueError("draft members reference candidates by non-negative index")
        return self


class ContradictionDraft(BaseModel):
    """Model-proposed contradiction draft; sides resolve app-side."""

    model_config = ConfigDict(extra="forbid")

    members: list[int] = Field(
        description="Indexes of the conflicting candidates (at least two)."
    )
    description: str
    severity: Severity = Severity.CAUTION
    resolution_guidance: str | None = None

    @model_validator(mode="after")
    def check_contradiction_draft(self):
        if not self.description.strip():
            raise ValueError("contradiction description must not be empty")
        return self


class ConsolidationDraftResult(BaseModel):
    """Wire shape of the Phase C named draft response before app assembly."""

    model_config = ConfigDict(extra="forbid")

    findings: list[FindingDraft] = Field(default_factory=list)
    contradictions: list[ContradictionDraft] = Field(default_factory=list)
    unresolved_dependencies: list[str] = Field(default_factory=list)
    # OD-4 additive: propose-only RELATED pairs over candidate indexes (§9).
    # Strictly advisory: the application re-validates every pair against its
    # own output map and drops + registers any that fails.
    related_pairs: list[list[int]] = Field(default_factory=list)


class PropertyConsolidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[PropertyFinding] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    unresolved_dependencies: list[str] = Field(default_factory=list)
    provenance: ConsolidationProvenance
    # Additive C3 container blocks (§8.1, Option B) — present on v2 results.
    coverage: Coverage | None = None
    integrity: Integrity | None = None
    readiness: Readiness | None = None
    correlations: list[Correlation] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_finding_ids(self):
        seen: set[str] = set()
        for item in self.findings:
            if item.finding_id in seen:
                raise ValueError(f"duplicate finding ID in consolidation: {item.finding_id}")
            seen.add(item.finding_id)
        return self


# -- Phase D final opinion -----------------------------------------------------------


class OutstandingItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_ids: list[str] = Field(default_factory=list)
    skipped_tx_ids: list[str] = Field(default_factory=list)
    unverified_tx_ids: list[str] = Field(default_factory=list)


class FindingReference(BaseModel):
    """Customer report reference to a consolidated finding — never a re-narration."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(pattern=FINDING_ID_RE)
    one_line: str | None = None


class FinalDueDiligenceOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: OpinionVerdict
    report_type: OpinionType
    executive_assessment: str
    property_identity: PropertyIdentity
    ownership_history_summary: str
    overall_assessment: str
    critical_findings: list[FindingReference] = Field(default_factory=list)
    caution_findings: list[FindingReference] = Field(default_factory=list)
    positive_findings: list[FindingReference] = Field(default_factory=list)
    encumbrance_assessment: str | None = None
    conversion_layout_assessment: str | None = None
    building_assessment: str | None = None
    outstanding: OutstandingItems = Field(default_factory=OutstandingItems)
    limitations: list[str] = Field(default_factory=list)
    recommended_conditions: list[str] = Field(default_factory=list)
    final_opinion: str
    source_hashes: SourceHashes
    provenance: Provenance

    @model_validator(mode="after")
    def check_opinion_completeness(self):
        for field_name in ("executive_assessment", "ownership_history_summary", "overall_assessment", "final_opinion"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} must not be empty")
        dropped = self.report_type is OpinionType.FINAL and (
            self.outstanding.skipped_tx_ids or self.outstanding.unverified_tx_ids or self.outstanding.requirement_ids
        )
        if dropped:
            raise ValueError("a FINAL opinion must not carry outstanding items; disclose them in a PRELIMINARY one")
        return self


class FinalReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    report_type: OpinionType
    generated_at: str
    model: str | None = None
    prompt_version: str | None = None
    contract_version: str = ANALYSIS_CONTRACT_VERSION
    source_hashes: SourceHashes
    pdf_available: bool = False
    superseded: bool = False


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
    "Contradiction",
    "DocumentEvidenceReference",
    "DossierScope",
    "EffectivityStatus",
    "EntrySourceKind",
    "EvidenceBasis",
    "EvidenceRequirement",
    "FinalDueDiligenceOpinion",
    "FinalReportMetadata",
    "FindingCategory",
    "FindingLink",
    "FindingReference",
    "FINDING_ID_RE",
    "MatchStatus",
    "OpinionType",
    "OpinionVerdict",
    "OutstandingItems",
    "PropertyConsolidationResult",
    "PropertyFinding",
    "PropertyFindingStatus",
    "FindingDraft",
    "ContradictionDraft",
    "ConsolidationDraftResult",
    "PropertyIdentity",
    "PropertyIdentityDetail",
    "Provenance",
    "REQUIREMENT_ID_RE",
    "RequirementMatch",
    "RequirementStatus",
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
    "new_finding_id",
    "new_requirement_id",
    "new_tx_finding_id",
    "phase_a_hash",
]
