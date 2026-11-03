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
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SCHEMA_VERSION = "3.0"


# -- controlled enums (§8, §10) ------------------------------------------------


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

    Unknown values fall back to PENDING (safe default - never silently marks a
    transaction verified).
    """
    raw = str(getattr(value, "value", value) or "").strip().upper().replace(" ", "_").replace("-", "_")
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


# -- report citations ----------------------------------------------------------


class CitedDocument(BaseModel):
    """A document (and optional observed page range) the report relies on."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(description="Existing uploaded document ID; required for traceability.")
    pages: str | None = Field(default=None, description="Observed page/range only; do not invent.")


class MissingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(
        description=(
            "Compact, directly readable label for the document/evidence needed: the document type "
            "plus only the identifiers that distinguish it (parties, date or document number, "
            "registration reference). Short, not a sentence; add a property identifier only when "
            "needed to distinguish among similar documents."
        )
    )
    reason: str | None = Field(
        default=None,
        description="One short direct line stating the evidence question this document must resolve.",
    )
    for_transaction: str | None = None


# -- transaction verification (§7 Output B, §9) --------------------------------


class TransactionVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tx_id: str
    sequence: int
    transaction_metadata: dict[str, Any] = Field(default_factory=dict)
    required_documents: list[MissingDocument] = Field(default_factory=list)
    reviewed_document_ids: list[str] = Field(default_factory=list)
    status: VerificationStatus
    report: str = Field(
        description=(
            "Markdown verification report for this transaction only: open with a "
            "bold one-line verdict, then short markdown sections named for what "
            "this transaction turned on - bullets for enumerable facts, prose "
            "for reasoning, bold decisive facts, inline citations of the form "
            "[doc_id] or [doc_id p.X-Y]. "
            "Must contain an '## Earlier transactions' section whenever an earlier "
            "chain link is unverified."
        )
    )
    cited_documents: list[CitedDocument] = Field(default_factory=list)
    verified_at: str | None = None
    schema_version: Literal["3.0"] = SCHEMA_VERSION

    @model_validator(mode="after")
    def check_result_invariants(self):
        seen = set()
        for item in self.required_documents:
            key = (item.document_type.strip().casefold(), (item.reason or "").strip().casefold())
            if key in seen:
                raise ValueError("required_documents contains a duplicate requirement")
            seen.add(key)
        if self.status in {VerificationStatus.PENDING, VerificationStatus.IN_PROGRESS, VerificationStatus.PENDING_NOT_VERIFIED} and self.verified_at:
            raise ValueError("verified_at must be null until verification is completed")
        if not self.report.strip():
            raise ValueError("report must not be empty")
        citation_keys = set()
        for item in self.cited_documents:
            key = (item.doc_id, item.pages or "")
            if key in citation_keys:
                raise ValueError("cited_documents contains a duplicate citation")
            citation_keys.add(key)
        if self.status == VerificationStatus.ISSUES_IDENTIFIED and not self.cited_documents:
            raise ValueError("ISSUES_IDENTIFIED requires at least one cited document")
        return self


# -- validation helpers --------------------------------------------------------


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


def _legacy_citation(ref: dict[str, Any]) -> str:
    pages = str(ref.get("pages") or "").strip()
    return f"[{ref.get('doc_id')} p.{pages}]" if pages else f"[{ref.get('doc_id')}]"


def _legacy_report_prose(source: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    """Convert legacy summary/findings prose into one markdown report.

    Returns (report, cited_documents, status). Issues identified without any
    retained citation are downgraded to inconclusive.
    """
    summaries = [str(value).strip() for value in (source.get("summary"), source.get("conclusion")) if value and str(value).strip()]
    summary = summaries[0] if summaries else ""
    for alternate in summaries[1:]:
        if alternate.casefold() not in summary.casefold():
            summary = f"{summary} {alternate}".strip()
    supporting = _legacy_evidence(source.get("supporting_evidence"))
    contradictory = _legacy_evidence(source.get("contradictory_evidence"))

    cited: list[dict[str, Any]] = []
    seen_citations: set[tuple[str, str]] = set()

    def citation(ref: dict[str, Any]) -> str:
        doc_id = str(ref.get("doc_id") or "")
        pages = str(ref.get("pages") or "")
        key = (doc_id, pages)
        if doc_id and key not in seen_citations:
            seen_citations.add(key)
            cited.append({"doc_id": doc_id, "pages": ref.get("pages")})
        return _legacy_citation({"doc_id": doc_id, "pages": pages})

    findings_bullets: list[str] = []
    finding_texts: list[str] = []
    unreferenced_details: list[str] = []

    def add_bullet(title: str, details: str, refs: list[dict[str, Any]]) -> None:
        citations = " ".join(citation(ref) for ref in refs if ref.get("doc_id"))
        label = f"**{title}** — " if title else ""
        text = " ".join(part for part in (details.strip(), citations) if part).strip()
        findings_bullets.append(f"- {label}{text}")
        finding_texts.append(f"{title} {details}".strip())

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
        add_bullet(title or "Evidence finding", " ".join(details), refs)

    # Keep legacy stand-alone evidence pointers visible without repeating refs
    # that already support a finding. Conflicts remain one bullet citing both.
    extra_support = [ref for ref in supporting if (str(ref.get("doc_id")), str(ref.get("pages") or "")) not in seen_citations]
    if extra_support:
        context = " ".join(str(ref.get("passage") or "") for ref in extra_support).strip()
        add_bullet("Additional evidence reviewed", context or "The cited record was reviewed for this transaction.", extra_support)
    conflict_refs = [ref for ref in contradictory if (str(ref.get("doc_id")), str(ref.get("pages") or "")) not in seen_citations]
    if conflict_refs:
        context = " ".join(str(ref.get("passage") or "") for ref in conflict_refs).strip()
        add_bullet("Contradictory evidence", context or "The cited records contain a material contradiction requiring review.", conflict_refs)

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
        if folded in summary.casefold() or summary.casefold() in folded or any(folded in prior.casefold() for prior in finding_texts):
            continue
        if any(phrase in folded or folded in phrase for phrase in requirement_phrases):
            continue
        if any(text.casefold() == prior.casefold() for prior in qualifiers):
            continue
        qualifiers.append(text)
    if unreferenced_details:
        qualifiers.extend(text for text in unreferenced_details if text and text.casefold() not in summary.casefold())
    status = normalize_status(source.get("status"))
    if status == VerificationStatus.ISSUES_IDENTIFIED.value and not cited:
        qualifiers.append("The legacy record marked issues identified but did not retain an evidence-backed citation; its status is therefore inconclusive under schema 3.0.")
        status = VerificationStatus.INCONCLUSIVE.value

    report_sections: list[str] = []
    if summary:
        report_sections.append(f"## Conclusion\n\n{summary}")
    if findings_bullets:
        report_sections.append("## Findings\n\n" + "\n".join(findings_bullets))
    if qualifiers:
        report_sections.append("## Material qualifications\n\n" + "\n".join(f"- {qualifier}" for qualifier in qualifiers))
    return "\n\n".join(report_sections) or "No verification report was recorded in this legacy result.", cited, status


def normalize_transaction_verification(data: Any) -> dict[str, Any]:
    """Deterministically adapt legacy rows to the v3.0 result contract.

    This is a read/update-boundary adapter only; it never rewrites stored rows.
    It consolidates legacy prose into one markdown ``report`` and retains source
    pointers as ``cited_documents``.
    """
    if not isinstance(data, dict):
        raise SchemaValidationError("TransactionVerification", ["result must be an object"])
    source = dict(data)
    if not str(source.get("tx_id") or "").strip():
        identity = json.dumps(source, sort_keys=True, ensure_ascii=False, default=str)
        source["tx_id"] = f"LEGACY-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    metadata = dict(source.get("transaction_metadata") or {})
    if isinstance(metadata.get("transaction_type"), str):
        metadata["transaction_type"] = re.sub(
            r"\s*\(EC entry;\s*instrument not supplied\)",
            "",
            metadata["transaction_type"],
            flags=re.IGNORECASE,
        ).strip()
    # Metadata used only to echo narrative/evidence already present in the report is
    # deliberately excluded from the canonical presentation contract.
    for key in ("summary_points", "source_refs", "related_events"):
        metadata.pop(key, None)

    existing_report = str(source.get("report") or "").strip()
    if existing_report:
        # Already stored under schema 3.0: pass the report through unchanged and
        # retain only well-formed citations.
        report = existing_report
        cited = []
        seen_citations: set[tuple[str, str]] = set()
        for item in source.get("cited_documents") or []:
            if not isinstance(item, dict) or not item.get("doc_id"):
                continue
            key = (str(item["doc_id"]), item.get("pages") or "")
            if key not in seen_citations:
                seen_citations.add(key)
                cited.append({"doc_id": str(item["doc_id"]), "pages": item.get("pages")})
        status = normalize_status(source.get("status"))
    else:
        report, cited, status = _legacy_report_prose(source)

    required = [
        *(source.get("required_documents") or []),
        *(source.get("missing_documents") or []),
    ]
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
    complete = status in {
        VerificationStatus.VERIFIED_WITH_AVAILABLE_EVIDENCE.value,
        VerificationStatus.ISSUES_IDENTIFIED.value,
        VerificationStatus.INCONCLUSIVE.value,
    }
    payload = {
        "tx_id": source.get("tx_id"),
        "sequence": source.get("sequence") or _sequence_from_id(source.get("tx_id")),
        "status": status,
        "report": report,
        "cited_documents": cited,
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
