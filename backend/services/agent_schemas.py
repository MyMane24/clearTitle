"""Versioned output contracts for the ClearTitle verification agent.

Single source of truth for:

* the controlled verification-status enum (§8),
* the title-chain output schema (§7 Output A, §9),
* the transaction-verification output schema (§7 Output B, §9).

Schemas are Pydantic models (already a project dependency). They are used to
validate LLM output before persistence and to validate tool arguments. Nothing
else in the application should re-declare these shapes.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SCHEMA_VERSION = "2.1"
TITLE_CHAIN_SCHEMA_VERSION = "2.0"


# ── controlled enums (§8, §10) ────────────────────────────────────────────────


class VerificationStatus(str, Enum):
    """§8 — the only permitted transaction verification statuses."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED_WITH_AVAILABLE_EVIDENCE = "VERIFIED_WITH_AVAILABLE_EVIDENCE"
    ISSUES_IDENTIFIED = "ISSUES_IDENTIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    PENDING_NOT_VERIFIED = "PENDING_NOT_VERIFIED"


VERIFICATION_STATUS_VALUES = tuple(s.value for s in VerificationStatus)


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

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    pages: str | None = None
    passage: str | None = None


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    details: str
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence(self):
        if not self.evidence:
            raise ValueError("findings must cite at least one evidence reference")
        return self


class MissingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    schema_version: Literal["2.0"] = TITLE_CHAIN_SCHEMA_VERSION


# ── transaction verification (§7 Output B, §9) ────────────────────────────────


class TransactionVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tx_id: str
    sequence: int
    transaction_metadata: dict[str, Any] = Field(default_factory=dict)
    required_documents: list[MissingDocument] = Field(default_factory=list)
    reviewed_document_ids: list[str] = Field(default_factory=list)
    status: VerificationStatus
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    verified_at: str | None = None
    schema_version: Literal["2.1"] = SCHEMA_VERSION

    @model_validator(mode="after")
    def reject_duplicate_requirements(self):
        seen = set()
        for item in self.required_documents:
            key = (item.document_type.strip().casefold(), (item.reason or "").strip().casefold())
            if key in seen:
                raise ValueError("required_documents contains a duplicate requirement")
            seen.add(key)
        if self.status in {VerificationStatus.PENDING, VerificationStatus.IN_PROGRESS, VerificationStatus.PENDING_NOT_VERIFIED} and self.verified_at:
            raise ValueError("verified_at must be null until verification is completed")
        if self.status == VerificationStatus.ISSUES_IDENTIFIED and not self.findings:
            raise ValueError("ISSUES_IDENTIFIED requires at least one evidence-backed finding")
        return self


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


def _legacy_evidence(items: Any) -> list[dict[str, Any]]:
    refs = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("doc_id"):
            continue
        ref = {
            "doc_id": str(item["doc_id"]),
            "pages": item.get("pages") or item.get("page"),
            "passage": item.get("passage"),
        }
        ref = {key: value for key, value in ref.items() if value is not None}
        key = (ref["doc_id"], ref.get("pages"), ref.get("passage"))
        if key not in seen:
            seen.add(key)
            refs.append(ref)
    return refs


def normalize_transaction_verification(data: Any) -> dict[str, Any]:
    """Deterministically adapt v2.0/legacy rows to the v2.1 result contract.

    This is a read/update-boundary adapter only; it never rewrites stored rows.
    It consolidates legacy prose into summary/findings and retains source pointers.
    """
    if not isinstance(data, dict):
        raise SchemaValidationError("TransactionVerification", ["result must be an object"])
    source = dict(data)
    if not str(source.get("tx_id") or "").strip():
        identity = json.dumps(source, sort_keys=True, ensure_ascii=False, default=str)
        source["tx_id"] = f"LEGACY-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    metadata = dict(source.get("transaction_metadata") or {})
    # Metadata used only to echo narrative/evidence already present in findings is
    # deliberately excluded from the v2.1 presentation contract.
    for key in ("summary_points", "source_refs", "related_events"):
        metadata.pop(key, None)

    summaries = [str(value).strip() for value in (source.get("summary"), source.get("conclusion")) if value and str(value).strip()]
    summary = summaries[0] if summaries else ""
    for alternate in summaries[1:]:
        if alternate.casefold() not in summary.casefold():
            summary = f"{summary} {alternate}".strip()
    supporting = _legacy_evidence(source.get("supporting_evidence"))
    contradictory = _legacy_evidence(source.get("contradictory_evidence"))
    findings = []
    cited = set()
    unreferenced_details = []

    for old in source.get("findings") or []:
        if not isinstance(old, dict):
            continue
        observation = str(old.get("details") or old.get("description") or "").strip()
        title = str(old.get("title") or _legacy_finding_title(observation)).strip()
        if not old.get("title") and title.casefold() == observation.casefold():
            title = "Evidence finding"
        details_parts = [observation, old.get("significance"), old.get("explanation")]
        details = []
        for part in details_parts:
            text = str(part or "").strip()
            if text and text.casefold() not in {title.casefold(), summary.casefold()} and text.casefold() not in {p.casefold() for p in details}:
                details.append(text)
        refs = _legacy_evidence(old.get("evidence") or old.get("source_refs"))
        if not details and title:
            details = [title]
        if not refs:
            unreferenced_details.extend(details)
            continue
        findings.append({"title": title or "Evidence finding", "details": " ".join(details), "evidence": refs})
        cited.update((r["doc_id"], r.get("pages")) for r in refs)

    # Keep legacy stand-alone evidence pointers visible without repeating refs
    # that already support a finding. Conflicts remain one finding citing both.
    extra_support = [ref for ref in supporting if (ref["doc_id"], ref.get("pages")) not in cited]
    if extra_support:
        context = " ".join(ref.get("passage", "") for ref in extra_support).strip()
        findings.append({"title": "Additional evidence reviewed", "details": context or "The cited record was reviewed for this transaction.", "evidence": extra_support})
    if contradictory:
        conflict_refs = [ref for ref in contradictory if (ref["doc_id"], ref.get("pages")) not in cited]
        if conflict_refs:
            context = " ".join(ref.get("passage", "") for ref in conflict_refs).strip()
            findings.append({"title": "Contradictory evidence", "details": context or "The cited records contain a material contradiction requiring review.", "evidence": conflict_refs})

    qualifiers = []
    old_requirements = [*(source.get("required_documents") or []), *(source.get("missing_documents") or [])]
    requirement_phrases = [
        str(value).strip().casefold()
        for item in old_requirements if isinstance(item, dict)
        for value in (item.get("document_type"), item.get("reason"))
        if value and str(value).strip()
    ]
    for value in [source.get("impact"), *(source.get("unresolved") or []), *(source.get("limitations") or [])]:
        text = str(value or "").strip()
        folded = text.casefold()
        if not text or (
            ("ocr is imperfect" in folded or "no legal determination" in folded)
            and ("verify the original" in folded or "authenticity assessment" in folded)
        ):
            continue
        if folded in summary.casefold() or summary.casefold() in folded or any(folded in f["details"].casefold() for f in findings):
            continue
        if any(phrase in folded or folded in phrase for phrase in requirement_phrases):
            continue
        if any(text.casefold() == prior.casefold() for prior in qualifiers):
            continue
        qualifiers.append(text)
    if unreferenced_details:
        qualifiers.extend(text for text in unreferenced_details if text and text.casefold() not in summary.casefold())
    status = normalize_status(source.get("status"))
    if status == VerificationStatus.ISSUES_IDENTIFIED.value and not findings:
        qualifiers.append("The legacy record marked issues identified but did not retain an evidence-backed finding; its status is therefore inconclusive under schema 2.1.")
        status = VerificationStatus.INCONCLUSIVE.value
    if qualifiers:
        summary = " ".join(part for part in (summary, "Material qualifications: " + " ".join(qualifiers)) if part).strip()

    required = source.get("required_documents")
    if required is None:
        required = source.get("missing_documents") or []
    merged_required = []
    seen_requirements = set()
    for item in required:
        if not isinstance(item, dict):
            continue
        normalized = {
            "document_type": str(item.get("document_type") or item.get("type") or "").strip(),
            "reason": item.get("reason"),
            "for_transaction": item.get("for_transaction") or source.get("tx_id"),
        }
        normalized = {key: value for key, value in normalized.items() if value is not None}
        key = (normalized.get("document_type", "").casefold(), str(normalized.get("reason") or "").casefold())
        if normalized["document_type"] and key not in seen_requirements:
            seen_requirements.add(key)
            merged_required.append(normalized)
    if source.get("missing_documents") and source.get("required_documents"):
        for item in source["missing_documents"]:
            if not isinstance(item, dict):
                continue
            candidate = {"document_type": str(item.get("document_type") or item.get("type") or "").strip(), "reason": item.get("reason"), "for_transaction": item.get("for_transaction") or source.get("tx_id")}
            key = (candidate["document_type"].casefold(), str(candidate.get("reason") or "").casefold())
            if candidate["document_type"] and key not in seen_requirements:
                seen_requirements.add(key)
                merged_required.append({k: v for k, v in candidate.items() if v is not None})

    complete = status in {
        VerificationStatus.VERIFIED_WITH_AVAILABLE_EVIDENCE.value,
        VerificationStatus.ISSUES_IDENTIFIED.value,
        VerificationStatus.INCONCLUSIVE.value,
    }
    payload = {
        "tx_id": source.get("tx_id"),
        "sequence": source.get("sequence") or _sequence_from_id(source.get("tx_id")),
        "status": status,
        "summary": summary or "No verification summary was recorded in this legacy result.",
        "findings": findings,
        "required_documents": merged_required,
        "reviewed_document_ids": list(dict.fromkeys(source.get("reviewed_document_ids") or [])),
        "transaction_metadata": metadata,
        "verified_at": (source.get("verified_at") or None) if complete else None,
        "schema_version": SCHEMA_VERSION,
    }
    return validate_transaction_verification(payload).model_dump()


def _sequence_from_id(tx_id: Any) -> int:
    value = str(tx_id or "")
    try:
        return int(value.removeprefix("PA-TC-")) if value.startswith("PA-TC-") else 0
    except ValueError:
        return 0


def _legacy_finding_title(description: str) -> str:
    words = description.split()
    if not words:
        return "Evidence finding"
    if len(words) <= 7:
        return description
    return " ".join(words[:7]).rstrip(".,;:") + "…"


def validate_transaction_verification(data: Any) -> TransactionVerification:
    return _validate(TransactionVerification, data)
