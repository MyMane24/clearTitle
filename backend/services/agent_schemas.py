"""Versioned output contracts for the ClearTitle verification agent.

Single source of truth for:

* the controlled verification-status enum (§8),
* the durable TODO-state enum (§10),
* the title-chain output schema (§7 Output A, §9),
* the transaction-verification output schema (§7 Output B, §9).

Schemas are Pydantic models (already a project dependency). They are used to
validate LLM output before persistence and to validate tool arguments. Nothing
else in the application should re-declare these shapes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

SCHEMA_VERSION = "1.0"


# ── controlled enums (§8, §10) ────────────────────────────────────────────────


class VerificationStatus(str, Enum):
    """§8 — the only permitted transaction verification statuses."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED_WITH_AVAILABLE_EVIDENCE = "VERIFIED_WITH_AVAILABLE_EVIDENCE"
    ISSUES_IDENTIFIED = "ISSUES_IDENTIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    PENDING_NOT_VERIFIED = "PENDING_NOT_VERIFIED"


class TodoState(str, Enum):
    """§10 — durable checklist task states."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


VERIFICATION_STATUS_VALUES = tuple(s.value for s in VerificationStatus)
TODO_STATE_VALUES = tuple(s.value for s in TodoState)


def normalize_status(value: Any) -> str:
    """Coerce any LLM/legacy status string to a permitted ``VerificationStatus``.

    Unknown values fall back to PENDING (safe default — never silently marks a
    transaction verified).
    """
    raw = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "VERIFIED": VerificationStatus.VERIFIED_WITH_AVAILABLE_EVIDENCE.value,
        "VERIFIED_WITH_EVIDENCE": VerificationStatus.VERIFIED_WITH_AVAILABLE_EVIDENCE.value,
        "ISSUES": VerificationStatus.ISSUES_IDENTIFIED.value,
        "FLAG": VerificationStatus.ISSUES_IDENTIFIED.value,
        "ISSUE_FOUND": VerificationStatus.ISSUES_IDENTIFIED.value,
        "MISSING_EVIDENCE": VerificationStatus.PENDING_NOT_VERIFIED.value,
        "PENDING_NOT_VERIFIED": VerificationStatus.PENDING_NOT_VERIFIED.value,
        "UNVERIFIED": VerificationStatus.INCONCLUSIVE.value,
    }
    raw = aliases.get(raw, raw)
    return raw if raw in VERIFICATION_STATUS_VALUES else VerificationStatus.PENDING.value


# ── evidence + findings ───────────────────────────────────────────────────────


class EvidenceRef(BaseModel):
    """A pointer to actual retrieved evidence. Never fabricated."""

    doc_id: str
    page: str | None = None
    passage: str | None = None
    note: str | None = None


class Finding(BaseModel):
    description: str
    significance: str | None = None
    source_refs: list[EvidenceRef] = Field(default_factory=list)
    explanation: str | None = None


class MissingDocument(BaseModel):
    document_type: str
    reason: str | None = None
    for_transaction: str | None = None


# ── Output A: title chain (§7, §9) ────────────────────────────────────────────


class TransactionEntry(BaseModel):
    """One ownership transaction in the chronological chain.

    ``tx_id`` is the stable internal identifier the frontend links results to;
    it must not change across report updates.
    """

    tx_id: str
    sequence: int
    document_type: str | None = None
    transaction_type: str | None = None
    executed_date: str | None = None
    registration_number: str | None = None
    registration_date: str | None = None
    vendors: list[str] = Field(default_factory=list)
    purchasers: list[str] = Field(default_factory=list)
    party_locations: list[str] = Field(default_factory=list)
    survey_number: str | None = None
    plot_number: str | None = None
    site_flat_number: str | None = None
    property_location: str | None = None
    market_value: str | None = None
    consideration: str | None = None
    schedule_property: str | None = None
    conveyed_portion: str | None = None
    source_doc_ids: list[str] = Field(default_factory=list)
    inferred: bool = False
    uncertainty: list[str] = Field(default_factory=list)


class TitleChain(BaseModel):
    property_identity: dict[str, Any] = Field(default_factory=dict)
    transactions: list[TransactionEntry] = Field(default_factory=list)
    title_story: str = ""
    unresolved: list[str] = Field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


# ── transaction verification (§7 Output B, §9) ────────────────────────────────


class TransactionVerification(BaseModel):
    tx_id: str
    status: VerificationStatus
    conclusion: str = ""
    reasoning: str = ""
    findings: list[Finding] = Field(default_factory=list)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    contradictory_evidence: list[EvidenceRef] = Field(default_factory=list)
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    impact: str | None = None
    unresolved: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    rule_versions: list[str] = Field(default_factory=list)
    verified_at: str = ""
    schema_version: str = SCHEMA_VERSION


# ── todo (§10) ────────────────────────────────────────────────────────────────


class Todo(BaseModel):
    todo_id: str
    case_id: str
    tx_id: str
    description: str = ""
    state: TodoState = TodoState.PENDING
    required_evidence: list[str] = Field(default_factory=list)
    updated_at: str = ""


# ── validation helpers ────────────────────────────────────────────────────────


class SchemaValidationError(RuntimeError):
    """Raised when model output cannot be validated into a schema."""

    def __init__(self, model: str, errors: list[str]):
        self.model = model
        self.errors = errors
        super().__init__(f"{model} validation failed: {'; '.join(errors)}")


def _validate(model_cls, data: Any):
    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        errors = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise SchemaValidationError(model_cls.__name__, errors) from e


def validate_title_chain(data: Any) -> TitleChain:
    return _validate(TitleChain, data)


def validate_transaction_verification(data: Any) -> TransactionVerification:
    return _validate(TransactionVerification, data)

