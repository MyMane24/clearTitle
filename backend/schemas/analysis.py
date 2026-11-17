"""Canonical Phase A contracts and identifier helpers.

* shared provenance + evidence-reference primitives,
* Phase A property identity and chain shapes,
* application-assigned transaction identifiers and content hashes.

Free-form LLM output must never reach persistence without passing one of these
models first. Transaction ids (``PA-TC-\\d{4}``) are application-assigned only —
never trusted from a model.
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


__all__ = [
    "ANALYSIS_CONTRACT_VERSION",
    "ASSIGNED_TX_ID_PATTERN",
    "TX_ID_RE",
    "ConfidenceLevel",
    "DocumentEvidenceReference",
    "EntrySourceKind",
    "PropertyIdentity",
    "PropertyIdentityDetail",
    "Provenance",
    "TitleChainEntry",
    "TitleChainEvent",
    "TransferCategory",
    "content_hash",
    "is_assigned_tx_id",
    "phase_a_hash",
]
