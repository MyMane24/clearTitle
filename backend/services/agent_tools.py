"""Tools exposed to the ClearTitle verification agent.

The LLM investigates ONLY through these tools. Handlers are thin wrappers over
existing repositories/services; they validate arguments, persist through the
authoritative stores, and return compact JSON results.

The application (not the model) assigns stable transaction ids and persists each
transaction result before advancing workflow state.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from backend.database.repositories import agent_repo as repo
from backend.logger import get_logger
from backend.schemas.analysis import VerificationFinding, content_hash, is_assigned_tx_id
from backend.services import case_memory, chain_identity
from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    SchemaValidationError,
    TransactionVerification,
    VerificationStatus,
    normalize_status,
    normalize_transaction_verification,
    validate_transaction_verification,
)
from pydantic import ValidationError

logger = get_logger(__name__)

_DEFAULT_TEXT_CHARS = 40000
_TEXT_CAP = 200000


def _is_phase_a_only_document(document: dict) -> bool:
    """ECs discover chain links in Phase A; they are not Phase B evidence."""
    document_type = re.sub(r"[\s-]+", "_", str(document.get("document_type") or "").strip().upper())
    filename = str(document.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1]
    filename_stem = re.sub(r"[\s-]+", "_", filename.rsplit(".", 1)[0].strip().upper())
    return document_type in {"EC", "ENCUMBRANCE_CERTIFICATE"} or filename_stem in {
        "EC", "ENCUMBRANCE_CERTIFICATE",
    }


def _without_source_refs(value):
    """Keep Phase A facts/events but hide provenance references from Phase B."""
    if isinstance(value, dict):
        return {
            key: _without_source_refs(item)
            for key, item in value.items()
            if key != "source_refs"
        }
    if isinstance(value, list):
        return [_without_source_refs(item) for item in value]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolContext:
    """Mutable state shared across one agent run."""

    def __init__(self, case_id: str, docs: list[dict], chain: dict | None = None,
                 current_tx_id: str | None = None, phase_a_chain: list[dict] | None = None,
                 run_id: str | None = None,
                 fresh_reverification: bool = False,
                 phase_a_hash: str | None = None):
        self.case_id = case_id
        self.run_id = run_id or str(uuid4())
        self.docs = docs
        self.by_id = {d["doc_id"]: d for d in docs}
        self.chain = chain or {}
        self.phase_a_chain = phase_a_chain or []
        self.phase_a_hash = phase_a_hash
        self.current_tx_id = current_tx_id
        self.fresh_reverification = fresh_reverification
        self.evidence_requirements: list[dict] = []
        self.listed_document_ids: set[str] = set()
        self.documents_listed = False
        self.selected_document_ids: set[str] = set()
        self.read_text_ranges: dict[str, list[tuple[int, int, int]]] = {}
        self.document_text_cache: dict[str, str] = {}
        self.saved_phase_a_result: dict | None = None
        self.saved_results: list[dict] = []
        self.rejected_findings: list[dict] = []
        self.missing_requests: list[dict] = []
        self.result_error: str | None = None
        self.finished = False
        self.tool_result_cache: dict[str, dict] = {}
        self.tool_call_fingerprints: dict[str, int] = {}
        self.tool_call_counts: dict[str, int] = {}
        self.repeated_tool_calls = 0
        self.additional_model_calls = 0
        self.additional_model_calls_used = False
        # Working notes the model keeps while reading (they survive OCR pruning)
        # and the OCR ranges already cleared from the session history.
        self.observations: list[dict] = []
        self.pruned_ranges: dict[str, set[tuple[int, int]]] = {}


# -- JSON schema for tools: generated from the canonical Pydantic contract ------


def _inline_refs(value: object, definitions: dict) -> object:
    if isinstance(value, list):
        return [_inline_refs(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        definition = definitions.get(ref.rsplit("/", 1)[-1], {})
        return _inline_refs(definition, definitions)
    return {key: _inline_refs(item, definitions) for key, item in value.items() if key != "$defs"}


def _verification_props() -> dict:
    schema = TransactionVerification.model_json_schema()
    inlined = _inline_refs(schema, schema.get("$defs", {}))
    props = {key: value for key, value in inlined.items() if key not in {"$schema", "title"}}
    for field in APP_OWNED_RESULT_FIELDS:
        props.get("properties", {}).pop(field, None)
        required = props.get("required") or []
        if field in required:
            required.remove(field)
    return props


# Dossier fields the persistence contract accepts but the model never supplies:
# they are app-assigned and overwritten at save. `findings` is model-emittable
# from the verification stage onward (prompt-instructed); `scope` and
# `revision` stay app-only, always overwritten at save.
APP_OWNED_RESULT_FIELDS = ["scope", "revision"]

# Finding-level fields the application stamps (task §5): never trusted from the
# model, always assigned when the dossier result is canonicalized.
APP_OWNED_FINDING_FIELDS = ("finding_id", "transaction_id")


class RegistryReadUnavailable(Exception):
    """The strict historical read for Phase B finding-id allocation failed.

    Deliberately not a SchemaValidationError: the arguments were valid — the
    registry read (database failure, corrupt payload) is what made identity
    assignment unsafe, and handlers translate this into a retryable abort in
    the same shape Phase A uses.
    """


def _validated_findings(ctx: ToolContext, tx_id: str, payload: dict) -> list[dict]:
    """Per-finding validation before persistence (task §6).

    Accepted findings are stamped with app-owned ids and written back into
    ``payload["findings"]``; rejected ones are excluded, logged with enough
    context to diagnose them, and echoed in the save response so the model gets
    a chance to correct them. One invalid finding never erases good ones.
    """
    raw_findings = payload.get("findings")
    if raw_findings is None:
        payload["findings"] = []
        ctx.rejected_findings = []
        return []
    if not isinstance(raw_findings, list):
        raise SchemaValidationError("TransactionVerification", ["findings must be a list of finding objects"])
    accepted: list[dict] = []
    rejected_findings: list[dict] = []
    for index, item in enumerate(raw_findings):
        if not isinstance(item, dict):
            rejected_findings.append({"index": index, "issues": ["finding must be an object"]})
            continue
        finding = {key: value for key, value in item.items() if key not in APP_OWNED_FINDING_FIELDS}
        if not finding.get("evidence") and not finding.get("evidence_gaps"):
            rejected_findings.append({"index": index, "issues": [
                "a finding without evidence references must explicitly declare its evidence_gaps "
                "(a missing document is not itself evidence of a legal defect)"
            ]})
            continue
        if finding.get("finding_id") or finding.get("transaction_id"):
            logger.warning(
                "finding_ids_ignored model-supplied finding_id/transaction_id stripped tx_id=%s index=%s", tx_id, index
            )
        try:
            validated = VerificationFinding.model_validate(finding).model_dump()
        except ValidationError as error:
            issues = [
                f"{'.'.join(str(location) for location in err['loc'])}: {err['msg']}"
                for err in error.errors()
            ]
            rejected_findings.append({"index": index, "issues": issues})
            continue
        unknown_doc_ids = sorted({
            str(ref.get("doc_id"))
            for key in ("evidence", "resolution_evidence")
            for ref in validated.get(key) or []
            if ref.get("doc_id") and str(ref["doc_id"]) not in ctx.by_id
        })
        if unknown_doc_ids:
            issues = [f"evidence cites documents outside this case: {unknown_doc_ids}"]
            rejected_findings.append({"index": index, "issues": issues})
            continue
        accepted.append(validated)
    try:
        prior_rows = repo.list_persisted_transaction_results(ctx.case_id)
    except Exception as error:
        # Identity correctness needs the persisted registry: a failed or corrupt
        # read is an unknown state and numbering against it could reissue an id
        # another dossier already carries. Nothing has mutated or persisted yet,
        # so the save aborts here; after the database recovers the retry
        # reconciles finding ids against the real history.
        logger.warning("finding_registry_unavailable case_id=%s error=%s", ctx.case_id, error)
        raise RegistryReadUnavailable(
            "cannot safely assign transaction finding ids: persisted transaction "
            f"results could not be read ({error}). Nothing was saved; retry after "
            "the database recovers — finding ids will be reconciled against the "
            "persisted history."
        ) from error
    registry, used_numbers = chain_identity.finding_registry(prior_rows)
    chain_identity.assign_finding_ids(tx_id, accepted, registry, used_numbers)
    for finding in accepted:
        finding["transaction_id"] = tx_id
    payload["findings"] = accepted
    ctx.rejected_findings = rejected_findings
    if rejected_findings:
        logger.warning(
            "findings_rejected run_id=%s case_id=%s tx_id=%s count=%d (excluded from the persisted result)",
            ctx.run_id, ctx.case_id, tx_id, len(rejected_findings),
        )
    return rejected_findings



_LIST_DOCS = {
    "name": "list_documents",
    "description": "Search all uploaded document filenames, types, and summaries. Returns all records and explicit likely candidates for each recorded evidence requirement. Candidate matches are discovery leads, not documentary proof.",
    "parameters": {"type": "object", "properties": {}},
}
_DOC_META = {
    "name": "get_document_metadata",
    "description": "Get metadata and structured extraction for one document.",
    "parameters": {"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]},
}
_DOC_TEXT = {
    "name": "get_document_text",
    "description": "Read one chunk of a selected document's merged OCR directly from the database. Request max_chars=200000 on the first call to reduce pagination; if has_more is true, continue from next_start_char until complete.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doc_id": {"type": "string"},
            "start_char": {"type": "integer"},
            "max_chars": {"type": "integer"},
        },
        "required": ["doc_id"],
    },
}
_SAVE_PHASE_A = {
    "name": "save_phase_a_result",
    "description": "Save the completed Phase A property identity and title-chain graph. Preserve the supplied result without rewriting it.",
    "parameters": {
        "type": "object",
        "properties": {"result": {"type": "object"}},
        "required": ["result"],
    },
}
_FINISH = {"name": "finish", "description": "Signal that this stage is complete.", "parameters": {"type": "object", "properties": {}}}
_LIST_TX = {"name": "list_transactions", "description": "List the title-chain transactions.", "parameters": {"type": "object", "properties": {}}}
_GET_TX = {
    "name": "get_transaction",
    "description": "Get one transaction by tx_id, with its saved verification result if any.",
    "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}}, "required": ["tx_id"]},
}
_RECORD_REQUIREMENTS = {
    "name": "record_evidence_requirements",
    "description": "Before searching document summaries, record the specific evidence needed based on the transaction details and verification skill.",
    "parameters": {"type": "object", "properties": {
        "requirements": {"type": "array", "minItems": 1, "items": {
            "type": "object", "properties": {
                "document_type": {"type": "string"}, "reason": {"type": "string"},
            }, "required": ["document_type", "reason"],
        }},
    }, "required": ["requirements"]},
}
_SELECT_DOCUMENTS = {
    "name": "select_documents",
    "description": "After reading saved summaries, select candidate document IDs to inspect. Selections accumulate during this transaction; later calls do not deselect previously selected documents. Only selected IDs can be fetched as OCR text.",
    "parameters": {"type": "object", "properties": {
        "doc_ids": {"type": "array", "items": {"type": "string"}},
    }, "required": ["doc_ids"]},
}
_SAVE_RESULT = {
    "name": "save_transaction_result",
    "description": "Persist one complete result conforming to the canonical TransactionVerification schema.",
    "parameters": _verification_props(),
}
_canonical_result_schema = _verification_props()
_REQ_MISSING = {
    "name": "request_missing_documents",
    "description": "Pause this transaction and save a canonical PENDING_NOT_VERIFIED result with outstanding required_documents.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tx_id": _canonical_result_schema["properties"]["tx_id"],
            "sequence": _canonical_result_schema["properties"]["sequence"],
            "status": {"type": "string", "enum": ["PENDING_NOT_VERIFIED"]},
            "report": _canonical_result_schema["properties"]["report"],
            "cited_documents": _canonical_result_schema["properties"]["cited_documents"],
            "required_documents": _canonical_result_schema["properties"]["required_documents"],
        },
        "required": ["tx_id", "sequence", "report", "required_documents"],
    },
}
_REQUEST_MORE_CALLS = {
    "name": "request_additional_verification_calls",
    "description": "Request one bounded extension to the verification call budget. Use only when a concrete, material evidence-checking step remains; state that step. At most one extension is granted, up to the hard cap.",
    "parameters": {"type": "object", "additionalProperties": False, "properties": {
        "next_step": {"type": "string", "minLength": 12, "maxLength": 400},
    }, "required": ["next_step"]},
}
_RECORD_OBSERVATION = {
    "name": "record_observation",
    "description": (
        "Keep a working note about a selected document you have read: one material fact "
        "(parties, shares, numbers, dates, schedule, authority, restrictions) with its page and a short "
        "verbatim quote. Raw OCR is cleared from the session after review, so these notes are your "
        "memory of what the document says. Record each material fact once, soon after reading it."
    ),
    "parameters": {"type": "object", "additionalProperties": False, "properties": {
        "doc_id": {"type": "string"},
        "pages": {"type": "string"},
        "fact": {"type": "string", "maxLength": 300},
        "quote": {"type": "string", "maxLength": 400},
    }, "required": ["doc_id", "fact"]},
}
PHASE_A_TOOLS = [_LIST_DOCS, _DOC_TEXT, _SAVE_PHASE_A, _FINISH]
VERIFY_TOOLS = [_GET_TX, _RECORD_REQUIREMENTS,
                _LIST_DOCS, _DOC_META, _SELECT_DOCUMENTS, _DOC_TEXT, _RECORD_OBSERVATION, _REQUEST_MORE_CALLS,
                _SAVE_RESULT, _REQ_MISSING, _FINISH]


def tools_for(phase: str) -> list[dict]:
    return {"phase_a": PHASE_A_TOOLS,
            "verify": VERIFY_TOOLS}.get(phase, [])


# -- helpers -------------------------------------------------------------------


def _find_tx(ctx: ToolContext, tx_id: str) -> dict | None:
    return next((t for t in (ctx.chain or {}).get("transactions") or [] if t.get("tx_id") == tx_id), None)


def _phase_a_entry_for_id(ctx: ToolContext, tx_id: str) -> dict | None:
    matched = next((entry for entry in ctx.phase_a_chain if entry.get("tx_id") == tx_id), None)
    if matched is not None:
        return matched
    if not tx_id.startswith("PA-TC-"):
        return None
    try:
        position = int(tx_id.removeprefix("PA-TC-"))
    except ValueError:
        return None
    if position < 1 or position > len(ctx.phase_a_chain):
        return None
    return ctx.phase_a_chain[position - 1]


# -- handlers ------------------------------------------------------------------


def _h_list_documents(ctx: ToolContext, args: dict) -> dict:
    if ctx.current_tx_id and not ctx.evidence_requirements:
        return {"error": "record evidence requirements from the transaction and verification skill before searching summaries"}
    all_documents = [
        {
            "doc_id": d["doc_id"], "filename": d.get("filename") or "",
            "document_type": d.get("document_type") or "",
            "status": d.get("status") or "unknown",
            "summary": d.get("summary") or "(summary unavailable)",
        }
        for d in ctx.docs
        if not _is_phase_a_only_document(d)
    ]
    documents = all_documents
    ctx.listed_document_ids = {d["doc_id"] for d in documents}
    ctx.documents_listed = True
    result = {"documents": documents}
    if ctx.current_tx_id:
        result["scope"] = (
            "Only transaction-supporting documents are listed. Encumbrance certificates are used "
            "during title-chain construction, not as transaction-verification evidence. Select only "
            "documents whose summaries match the active transaction's recorded evidence requirements."
        )
    return result


def _h_record_requirements(ctx: ToolContext, args: dict) -> dict:
    if not ctx.current_tx_id:
        return {"error": "load the transaction before recording evidence requirements"}
    requirements = args.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return {"error": "requirements must be a non-empty list"}
    normalized = []
    for item in requirements:
        if not isinstance(item, dict) or not str(item.get("document_type") or "").strip() or not str(item.get("reason") or "").strip():
            return {"error": "each requirement needs a document_type and a reason"}
        normalized.append({"document_type": item["document_type"].strip(), "reason": item["reason"].strip()})
    if ctx.documents_listed and normalized != ctx.evidence_requirements:
        return {"error": "evidence requirements are locked after document search; start a controlled new transaction review for changed requirements"}
    ctx.evidence_requirements = normalized
    return {"recorded": True, "requirements": normalized}


def _h_select_documents(ctx: ToolContext, args: dict) -> dict:
    if ctx.current_tx_id and (not ctx.evidence_requirements or not ctx.documents_listed):
        return {"error": "record evidence requirements and search summaries before selecting documents"}
    doc_ids = args.get("doc_ids")
    if not isinstance(doc_ids, list) or any(doc_id not in ctx.listed_document_ids for doc_id in doc_ids):
        return {"error": "select only document IDs returned by list_documents"}
    ctx.selected_document_ids.update(doc_ids)
    logger.info(
        "agent_documents_selected run_id=%s tx_id=%s doc_ids=%s",
        ctx.run_id, ctx.current_tx_id, sorted(ctx.selected_document_ids),
    )
    return {"selected": sorted(ctx.selected_document_ids)}


def _h_doc_metadata(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    if ctx.current_tx_id and not ctx.documents_listed:
        return {"error": "search document summaries before retrieving candidate metadata"}
    if ctx.current_tx_id and doc_id not in ctx.listed_document_ids:
        return {"error": "inspect metadata only for a candidate returned by list_documents"}
    meta = repo.get_document_metadata(ctx.case_id, doc_id)
    if not meta:
        return {"error": f"no document {doc_id!r} in case"}
    # Structured extraction is not documentary evidence and must not be offered
    # to the verification model as a substitute for the stored OCR text.
    return {key: value for key, value in meta.items() if key != "structured_data"}


def _h_doc_text(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    if doc_id not in ctx.by_id:
        return {"error": f"no document {doc_id!r} in case"}
    if ctx.current_tx_id and doc_id not in ctx.selected_document_ids:
        return {"error": "select this document based on its summary before reading OCR text"}
    if ctx.current_tx_id and ctx.by_id[doc_id].get("status") not in {"structured", "complete", "completed"}:
        return {"error": "document OCR/processing is not complete; request it or wait for processing"}
    max_chars = min(max(int(args.get("max_chars") or _DEFAULT_TEXT_CHARS), 1), _TEXT_CAP)
    start_char = max(int(args.get("start_char") or 0), 0)
    if doc_id not in ctx.document_text_cache:
        ctx.document_text_cache[doc_id] = repo.get_document_raw_text(ctx.case_id, doc_id)
    text = ctx.document_text_cache[doc_id]
    if not text:
        return {"error": f"no stored OCR text is available for {doc_id!r}; the document cannot be verified from its summary"}
    end_char = min(start_char + max_chars, len(text))
    cleared = ctx.pruned_ranges.get(doc_id, set())
    if any(start_char < prior_end and end_char > prior_start
           for prior_start, prior_end, _ in ctx.read_text_ranges.get(doc_id, [])
           if (prior_start, prior_end) not in cleared):
        return {
            "error": "requested OCR range overlaps text already retrieved; request an unread range using next_start_char"
        }
    ctx.read_text_ranges.setdefault(doc_id, []).append((start_char, end_char, len(text)))
    logger.info(
        "agent_ocr_range run_id=%s tx_id=%s doc_id=%s start=%s end=%s total=%s",
        ctx.run_id, ctx.current_tx_id, doc_id, start_char, end_char, len(text),
    )
    return {
        "doc_id": doc_id,
        "total_chars": len(text),
        "start_char": start_char,
        "next_start_char": end_char if end_char < len(text) else None,
        "has_more": end_char < len(text),
        "text": text[start_char:end_char],
    }


def _has_read_full_text(ctx: ToolContext, doc_id: str) -> bool:
    ranges = ctx.read_text_ranges.get(doc_id, [])
    if not ranges:
        return False
    total_chars = ranges[0][2]
    if any(total != total_chars for _, _, total in ranges):
        return False
    cursor = 0
    for start, end, _ in sorted(ranges):
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor >= total_chars


def _h_record_observation(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    fact = " ".join(str(args.get("fact") or "").split())
    if not ctx.current_tx_id:
        return {"error": "observations are recorded during transaction verification only"}
    if doc_id not in ctx.by_id:
        return {"error": f"no document {doc_id!r} in case"}
    if doc_id not in ctx.read_text_ranges:
        return {"error": "read the document's OCR before recording an observation about it"}
    if not fact:
        return {"error": "fact must not be empty"}
    quote = " ".join(str(args.get("quote") or "").split())
    text = " ".join(str(ctx.document_text_cache.get(doc_id) or "").split()).casefold()
    ctx.observations.append({
        "doc_id": doc_id, "pages": str(args.get("pages") or "").strip() or None,
        "fact": fact[:300], "quote": quote[:400] or None,
    })
    result = {"recorded": True, "notes_total": len(ctx.observations)}
    if quote:
        # OCR is noisy, so a miss is information for the model, not a rejection.
        result["quote_found_in_ocr"] = quote.casefold() in text
    return result


def _h_save_phase_a_result(ctx: ToolContext, args: dict) -> dict:
    result = args.get("result")
    if not isinstance(result, dict):
        return {"error": "result must be an object"}
    if not isinstance(result.get("property_identity"), dict):
        return {"error": "result.property_identity must be an object containing the target property identity"}
    if not isinstance(result["property_identity"].get("details"), list):
        return {"error": "result.property_identity.details must be a list"}
    if "unresolved" in result["property_identity"]:
        return {"error": "do not add an unresolved field to property_identity"}
    if not isinstance(result.get("title_chain_graph"), str) or not result["title_chain_graph"].strip():
        return {"error": "result.title_chain_graph must contain the readable title-chain graph"}
    chain = result.get("title_chain")
    if not isinstance(chain, list) or not chain:
        return {"error": "result.title_chain must contain the ordered ownership chain"}

    def validate_citations(refs, where):
        if not isinstance(refs, list) or not refs:
            return f"{where} must contain at least one source reference"
        cited_filenames = []
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("doc_id"), str) or not ref["doc_id"].strip():
                return f"{where} references must contain document IDs"
            document = ctx.by_id.get(ref["doc_id"])
            if not document:
                return f"{where} references a document outside this case"
            filename = ref.get("filename")
            if not isinstance(filename, str) or filename != document.get("filename"):
                return f"{where} must preserve the exact PDF filename for {ref['doc_id']}"
            cited_filenames.append(filename)
        return cited_filenames

    seen_transaction_numbers: set[str] = set()
    for index, entry in enumerate(chain):
        if not isinstance(entry, dict):
            return {"error": f"result.title_chain[{index}] must be an object"}
        # Model-supplied transaction ids are never trusted (master rule): the
        # application assigns stable ids below, keyed on content identity.
        entry.pop("tx_id", None)
        if entry.get("chain_position") != index + 1:
            return {"error": "title_chain must be numbered from earliest supported root to current/latest owner"}
        if "unresolved" in entry:
            return {"error": f"do not add an unresolved field to title_chain[{index}]"}
        transaction = entry.get("documented_transaction")
        if not isinstance(transaction, dict) or not transaction:
            return {"error": f"title_chain[{index}].documented_transaction must contain the open-ended transaction details"}
        transaction.pop("tx_id", None)
        transaction.pop("upstream_tx_ids", None)
        if not isinstance(transaction.get("transaction_type"), str) or not transaction["transaction_type"].strip():
            return {"error": f"title_chain[{index}].documented_transaction must identify the transaction_type"}
        if "executed_date" not in transaction:
            return {"error": f"title_chain[{index}].documented_transaction must include executed_date (null if not stated)"}
        if "transaction_number" not in transaction:
            return {"error": f"title_chain[{index}].documented_transaction must include transaction_number (null if not stated)"}
        transaction_number = transaction.get("transaction_number")
        if transaction_number:
            registration_ref = str(transaction_number).strip().casefold()
            if registration_ref in seen_transaction_numbers:
                return {
                    "error": f"duplicate transaction_number {transaction_number!r}; merge duplicate document copies into one chronological chain entry"
                }
            seen_transaction_numbers.add(registration_ref)
        for field in ("transferors", "transferees"):
            if field in transaction and transaction[field] is not None and not chain_identity._string_list_ok(transaction[field]):
                return {"error": f"title_chain[{index}].documented_transaction.{field} must be a list of party names (or null)"}
        for field in (
            "registration_date", "registration_office", "property_type", "property_schedule", "consideration",
            "survey_number", "plot_number", "site_flat_number", "cts_number",
        ):
            if field in transaction and transaction[field] is not None and not isinstance(transaction[field], str):
                return {"error": f"title_chain[{index}].documented_transaction.{field} must be a string or null"}
        points = transaction.get("summary_points")
        if not isinstance(points, list) or not points:
            return {"error": f"title_chain[{index}].documented_transaction.summary_points must contain plain-language facts"}
        for point_index, point in enumerate(points):
            if not isinstance(point, str) or not point.strip():
                return {"error": f"title_chain[{index}].documented_transaction.summary_points[{point_index}] must be a plain-language sentence"}
        transaction_refs = validate_citations(
            transaction.get("source_refs"), f"title_chain[{index}].documented_transaction.source_refs"
        )
        if isinstance(transaction_refs, str):
            return {"error": transaction_refs}
        related_events = entry.get("related_events") or []
        if not isinstance(related_events, list):
            return {"error": f"title_chain[{index}].related_events must be a list"}
        for event_index, event in enumerate(related_events):
            if not isinstance(event, dict):
                return {"error": f"title_chain[{index}].related_events[{event_index}] must be an object"}
            if not isinstance(event.get("summary_points"), list) or not event["summary_points"]:
                return {"error": f"title_chain[{index}].related_events[{event_index}] must contain plain-language summary_points"}
            for point_index, point in enumerate(event["summary_points"]):
                if not isinstance(point, str) or not point.strip():
                    return {"error": f"title_chain[{index}].related_events[{event_index}].summary_points[{point_index}] must be a plain-language sentence"}
            event_refs = validate_citations(
                event.get("source_refs"), f"title_chain[{index}].related_events[{event_index}].source_refs"
            )
            if isinstance(event_refs, str):
                return {"error": event_refs}
    source_ids = set(ctx.by_id)
    referenced_ids = _collect_document_ids(result)
    unknown_ids = sorted(referenced_ids - source_ids)
    if unknown_ids:
        return {"error": "result references documents outside this case", "doc_ids": unknown_ids}

    # App-owned stable identity (task §3): preserve earlier ids for entries the
    # evidence identifies as the same transaction; everything else gets the
    # next id unused across the case's chain and persisted transaction results,
    # so no historical result is ever re-associated with a different transaction.
    # Historical identity reads are strictly required: a failed read is an
    # unknown state, not an empty one, and numbering from empty could reissue a
    # persisted transaction's id to a different transaction. The abort happens
    # before any mutation below (chain ids, upstream links, persistence), so
    # nothing is saved; once the database recovers the retry reconciles ids
    # through the normal content matcher.
    try:
        prior_chain = repo.get_persisted_title_chain_entries(ctx.case_id)
        prior_rows = repo.list_persisted_transaction_results(ctx.case_id)
    except Exception as error:
        logger.warning("phase_a_identity_reads_failed case_id=%s error=%s", ctx.case_id, error)
        return {
            "error": (
                "cannot safely assign transaction ids: historical identity state "
                f"could not be read ({error}). Nothing was saved; no chain or "
                "verification result was written. Retry after the database "
                "recovers — ids will then be reconciled against the persisted history."
            ),
            "retryable": True,
        }
    taken_ids = {
        str(item.get("tx_id"))
        for item in prior_rows
        if isinstance(item, dict) and is_assigned_tx_id(item.get("tx_id"))
    }
    identity_notes = chain_identity.assign_chain_tx_ids(chain, prior_chain, taken_ids)
    identity_notes += chain_identity.attach_upstream_ids(chain)
    if identity_notes:
        logger.info("phase_a_identity_assignment case_id=%s notes=%s", ctx.case_id, identity_notes)

    repo.save_phase_a_result(case_id=ctx.case_id, result=result)
    ctx.saved_phase_a_result = result
    ctx.finished = True
    return {
        "saved": True,
        "transaction_ids": [entry.get("tx_id") for entry in chain],
        "identity_notes": identity_notes,
    }


def _collect_document_ids(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"doc_id", "source_doc_id"} and isinstance(item, str):
                found.add(item)
            else:
                found.update(_collect_document_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_document_ids(item))
    return found


def _h_list_transactions(ctx: ToolContext, args: dict) -> dict:
    if ctx.phase_a_chain:
        return {"transactions": [
            {
                "tx_id": entry.get("tx_id") or f"PA-TC-{index:04d}",
                "sequence": index,
                "type": (entry.get("documented_transaction") or {}).get("transaction_type"),
                "executed_date": (entry.get("documented_transaction") or {}).get("executed_date"),
                "transaction_number": (entry.get("documented_transaction") or {}).get("transaction_number"),
            }
            for index, entry in enumerate(ctx.phase_a_chain, start=1)
        ]}
    return {"transactions": [
        {"tx_id": t.get("tx_id"), "sequence": t.get("sequence"),
         "type": t.get("transaction_type"), "executed_date": t.get("executed_date"),
         "vendors": t.get("transferors") or t.get("vendors"),
         "purchasers": t.get("transferees") or t.get("purchasers")}
        for t in (ctx.chain or {}).get("transactions") or []
    ]}


def _h_get_transaction(ctx: ToolContext, args: dict) -> dict:
    tx_id = str(args.get("tx_id") or ctx.current_tx_id or "")
    if ctx.current_tx_id and tx_id != ctx.current_tx_id:
        return {"error": "only the active transaction may be loaded during verification"}
    tx = _find_tx(ctx, tx_id)
    if tx is not None:
        return {
            "transaction": _without_source_refs(tx),
            "verification_result": _prior_result_for_agent(ctx, tx_id, int(tx.get("sequence") or 0)),
        }
    entry = _phase_a_entry_for_id(ctx, tx_id)
    if entry is None:
        return {"error": f"no transaction {tx_id!r} in chain"}
    transaction = dict(entry.get("documented_transaction") or {})
    transaction.update({"tx_id": tx_id, "sequence": entry.get("chain_position")})
    transaction["related_events"] = entry.get("related_events") or []
    return {
        "transaction": _without_source_refs(transaction),
        "verification_result": _prior_result_for_agent(ctx, tx_id, int(entry.get("chain_position") or 0)),
    }


def _prior_result_for_agent(ctx: ToolContext, tx_id: str, sequence: int) -> dict | None:
    if ctx.fresh_reverification and tx_id == ctx.current_tx_id:
        return None
    raw = repo.get_transaction_result(ctx.case_id, tx_id)
    if not raw:
        return None
    return _legacy_result(raw, tx_id=tx_id, sequence=sequence)


def _dedupe(items: list[dict], *, requirement: bool = False) -> list[dict]:
    seen = set()
    unique = []
    for item in items:
        if requirement:
            key = (
                str(item.get("document_type") or "").strip().casefold(),
                str(item.get("reason") or "").strip().casefold(),
            )
        else:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _validate_missing_requirements(ctx: ToolContext, requirements: list[dict]) -> dict | None:
    """Workflow-order and ownership checks only.

    The agent itself decides from the summaries whether a required document is
    already uploaded; the application keeps no keyword matcher and issues no
    candidate suggestions.
    """
    if not ctx.current_tx_id:
        return {"error": "no transaction under investigation"}
    if not ctx.evidence_requirements or not ctx.documents_listed:
        return {"error": "record the active transaction's requirements and search document summaries before requesting missing evidence"}
    for item in requirements:
        if item.get("for_transaction") and item["for_transaction"] != ctx.current_tx_id:
            return {
                "error": "required_documents must belong to the active transaction; do not attach another transaction's document request",
                "active_tx_id": ctx.current_tx_id,
                "requested_for_transaction": item["for_transaction"],
            }
    return None


def _legacy_result(previous: dict, *, tx_id: str, sequence: int) -> dict:
    """Adapt an existing result for resume without changing its persisted row."""
    result = dict(previous or {})
    result.setdefault("tx_id", tx_id)
    result.setdefault("sequence", sequence)
    result.setdefault("status", "PENDING")
    return normalize_transaction_verification(result)


_MAX_REPORT_CHARS = 4000


def _result_compactness_errors(payload: dict) -> list[str]:
    """Reject a runaway report and duplicated requirement rationales."""
    report = str(payload.get("report") or "").strip()
    errors = []

    def sentences(text: str) -> list[str]:
        # Heading lines are structure, not sentences; dropping them keeps
        # repetition checks aligned with the report prose.
        without_headings = re.sub(r"(?m)^#{1,6}\s+.*$", " ", text.strip())
        protected = re.sub(
            r"\b(?:R\.S|No|sq|ft|Mr|Mrs|Ms|Dr|Smt|Shri|St|CD|etc)\.",
            lambda match: match.group().replace(".", "<DOT>"),
            without_headings,
            flags=re.IGNORECASE,
        )
        protected = re.sub(
            r"\b(?:[A-Za-z]\.){2,}",
            lambda match: match.group().replace(".", "<DOT>"),
            protected,
        )
        return [
            part.replace("<DOT>", ".").strip()
            for part in re.split(r"(?<=[.!?])\s+", protected)
            if part.strip()
        ]

    def normalized(text: str) -> str:
        return re.sub(r"\W+", " ", text.casefold()).strip()

    if len(report) > _MAX_REPORT_CHARS:
        errors.append(
            f"report exceeds {_MAX_REPORT_CHARS} characters; rewrite it as a short verification "
            "report (verdict line, then one-line bullets per check) that states outcomes "
            "and issues instead of retelling the transaction"
        )

    # Keep complete required-document names and evidence descriptions. They are
    # actionable data, not disposable prose. Do not shorten these fields to solve
    # repetition; revise only the rationale when it duplicates the report.
    report_sentences = {normalized(sentence) for sentence in sentences(report)}
    for index, requirement in enumerate(payload.get("required_documents") or []):
        reason = str(requirement.get("reason") or "").strip()
        reason_sentences = {normalized(sentence) for sentence in sentences(reason)}
        if reason_sentences & report_sentences:
            errors.append(
                f"required_documents[{index}].reason repeats a report sentence; "
                "write a short rationale for why this specific evidence is needed, "
                "without changing or abbreviating document_type"
            )

    return errors


def _upstream_chain_context(case_id: str, phase_a_chain: list[dict], sequence: int) -> dict:
    """DB-truth digest of upstream links that have not been verified.

    Persisted into ``transaction_metadata.chain_context`` at save time so every
    result records which earlier chain links its assessment depends on. A link
    counts as unverified when it has no saved result, is still pending/in
    progress, or carries a non-terminal verification checkpoint.
    """
    unverified = []
    index: dict[tuple[str, str, str], str] = {}
    try:
        index = repo.requirement_ids_index(case_id)
    except Exception:
        logger.warning("requirement id index unavailable for %s (non-fatal)", case_id)
    for entry in phase_a_chain or []:
        entry_sequence = int(entry.get("chain_position") or entry.get("sequence") or 0)
        if not entry_sequence or entry_sequence >= sequence:
            continue
        upstream_id = entry.get("tx_id") or f"PA-TC-{entry_sequence:04d}"
        result = repo.get_transaction_result(case_id, upstream_id) or {}
        status = normalize_status(result.get("status")) if result else "PENDING"
        checkpoint = (result.get("transaction_metadata") or {}).get("_verification_checkpoint")
        if (
            status in {"VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE"}
            and not checkpoint
        ):
            continue
        missing = [
            {"document_type": item.get("document_type"), "reason": item.get("reason")}
            for item in (result.get("required_documents") or []) if isinstance(item, dict)
        ]
        for item in missing:
            requirement_id = index.get(repo.requirement_content_key(
                upstream_id, item.get("document_type"), item.get("reason")
            ))
            if requirement_id:
                item["requirement_id"] = requirement_id
        unverified.append({
            "tx_id": upstream_id,
            "status": status,
            "missing": missing,
        })
    return {"upstream_unverified": unverified}


DEPENDENCY_SECTION_HEADING = "## Earlier transactions"
# Legacy saved reports may still carry the old jargon heading; both match so the
# refresh flow finds and migrates them.
_DEPENDENCY_SECTION_PATTERN = re.compile(
    r"(?ims)^##\s+(?:earlier transactions|upstream dependency)\s*$\n?(.*?)(?=^##\s|\Z)"
)


def _has_dependency_section(report: str) -> bool:
    return bool(_DEPENDENCY_SECTION_PATTERN.search(str(report or "")))


def _split_dependency_section(report: str) -> tuple[str, str]:
    """Split a report into (report without the dependency section, its body)."""
    text = str(report or "").strip()
    match = _DEPENDENCY_SECTION_PATTERN.search(text)
    if not match:
        return text, ""
    without = (text[:match.start()] + text[match.end():]).strip()
    return without, match.group(1).strip()


def _with_dependency_section(report: str, body: str) -> str:
    """Return the report with the dependency section set to `body` (appended if absent)."""
    base, _ = _split_dependency_section(report)
    section = f"{DEPENDENCY_SECTION_HEADING}\n\n{str(body or '').strip()}".strip()
    return f"{base}\n\n{section}".strip() if base else section


def _normalize_request_label(value) -> str:
    return " ".join(str(value or "").split()).casefold()


# Words any two different documents may share; only a name outside this set
# (an authority, project or place) makes two differently worded requests
# comparable.
_GENERIC_REQUEST_WORDS = frozenset(
    "sale deed agreement partition gift release mutation extract record certificate "
    "approval layout plan khata tax receipt succession will power attorney "
    "encumbrance conversion order deposit memorandum family tree map survey "
    "subdivision correlation card possession occupancy completion entry register "
    "index no of the for and or to with".split()
)

# A "Doc. No. X" value is a registered-instrument identifier; two requests
# carrying different values are different documents even when everything else
# matches.
_DOC_NUMBER = re.compile(r"doc(?:ument)?\s*no\.?\s*[:#]?\s*([a-z0-9/-]+)")


def _kind_head(label: str) -> list[str]:
    """Leading words before the first identifier token, e.g. ['buda', 'layout']."""
    head = []
    for token in re.findall(r"[a-z0-9]+", label.casefold()):
        if any(ch.isdigit() for ch in token):
            break
        head.append(token)
    return head


def _digit_tokens(label: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", label) if any(c.isdigit() for c in t)}


def _requests_match(submitted: str, earlier: str) -> bool:
    """True when a submitted request names a document an earlier link already requested.

    Exact after case/whitespace normalization; otherwise the same distinctive
    document kind with a shared identifier (a re-worded 'BUDA layout approval'
    that adds the approval number), or two shared identifiers plus a shared
    distinctive word such as the survey numbers and the village name in two
    wordings of one survey-correlation request. Generic kind heads ('sale
    deed') never fuzzy-match because two different sale deeds share those
    words, and conflicting document numbers defeat the match (same-day deeds
    with consecutive registration numbers stay separate).
    """
    left, right = _normalize_request_label(submitted), _normalize_request_label(earlier)
    if left == right:
        return True
    doc_numbers_left = set(_DOC_NUMBER.findall(left))
    doc_numbers_right = set(_DOC_NUMBER.findall(right))
    if doc_numbers_left and doc_numbers_right and doc_numbers_left.isdisjoint(doc_numbers_right):
        return False
    head_left, head_right = _kind_head(left), _kind_head(right)
    distinctive = (set(head_left) | set(head_right)) - _GENERIC_REQUEST_WORDS
    digits = _digit_tokens(left) & _digit_tokens(right)
    if len(head_left) >= 2 and len(head_right) >= 2 and head_left[:2] == head_right[:2] and distinctive and digits:
        return True
    shared_word = any(
        len(word) >= 4 and word not in _GENERIC_REQUEST_WORDS
        for word in set(re.findall(r"[a-z]+", left)) & set(re.findall(r"[a-z]+", right))
    )
    return len(digits) >= 2 and shared_word


def _earlier_requests(case_id: str, sequence: int) -> list[tuple[str, str, str]]:
    """(label, normalized label, requester tx id) for every earlier link's request.

    The model re-files an earlier link's outstanding request even when the
    upstream context lists it verbatim; the tool refuses the duplicate so the
    model itself removes it and states reliance in the report instead.
    """
    requests: list[tuple[str, str, str]] = []
    if sequence <= 1:
        return requests
    for item in repo.list_transaction_results(case_id):
        result_sequence = int(item.get("sequence") or 0)
        if not result_sequence or result_sequence >= sequence:
            continue
        tx_id = str(item.get("tx_id") or "")
        for requirement in item.get("required_documents") or []:
            label = str(requirement.get("document_type") or "").strip()
            if label and tx_id:
                requests.append((label, _normalize_request_label(label), tx_id))
    return requests


def _available_document_request_errors(ctx: ToolContext, requirements: list[dict]) -> list[str]:
    """Refuse requests for records the case already holds, matched by identifier.

    Under duplicate-refusal pressure the model padded its request list with the
    deed it had just read; a registration/transaction number is a unique
    identifier, so a request label containing one that belongs to a case
    document is a request for that document.
    """
    identifiers: dict[str, str] = {}
    for entry in ctx.phase_a_chain or []:
        transaction = entry.get("documented_transaction") or {}
        refs = [
            str(ref.get("filename") or ref.get("doc_id") or "")
            for ref in (transaction.get("source_refs") or []) if isinstance(ref, dict)
        ]
        holder = ", ".join(filter(None, refs)) or "the case documents"
        for key in ("transaction_number", "registration_number", "document_number"):
            value = _normalize_request_label(transaction.get(key))
            if value:
                identifiers.setdefault(value, holder)
    errors = []
    for requirement in requirements:
        label = _normalize_request_label(requirement.get("document_type"))
        for identifier, holder in identifiers.items():
            if identifier in label:
                errors.append(
                    "%s is already available in the case (%s); never request an available "
                    "document — assess it directly instead" % (
                        requirement.get("document_type"), holder,
                    )
                )
                break
    return errors


_COMPLETED_STATUSES = {"VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE"}


def _validate_handoff(
    ctx: ToolContext, payload: dict, previous: dict, sequence: int, *, force_pending: bool,
) -> None:
    """The handoff is the next transaction's memory: keep it present and honest.

    Model-authored parts (established facts, open issues, note) are validated:
    every fact's document must have been read in full this run (or be a citation
    the saved result already retained). What the model leaves out of a completed
    result - the holders after this transaction and an unambiguous continuity
    label - is derived deterministically. ``stale`` is app-owned.
    """
    handoff = payload.get("handoff")
    handoff = dict(handoff) if isinstance(handoff, dict) else {}
    handoff["stale"] = False
    status = normalize_status(payload.get("status"))
    if not force_pending and status in _COMPLETED_STATUSES:
        retained = {
            ref.get("doc_id") for ref in previous.get("cited_documents") or [] if isinstance(ref, dict)
        }
        issues = []
        for index, fact in enumerate(handoff.get("established") or []):
            doc_id = fact.get("doc_id") if isinstance(fact, dict) else None
            if not doc_id:
                continue
            if doc_id not in ctx.by_id:
                issues.append(f"handoff.established[{index}] cites a document outside this case: {doc_id}")
            elif doc_id not in retained and not (
                doc_id in ctx.selected_document_ids and _has_read_full_text(ctx, doc_id)
            ):
                issues.append(
                    f"handoff.established[{index}] cites a document whose complete OCR was not reviewed: {doc_id}"
                )
        if issues:
            raise SchemaValidationError("TransactionVerification", issues)
        entry = _phase_a_entry_for_id(ctx, ctx.current_tx_id or "") or {}
        previous_entry = ctx.phase_a_chain[sequence - 2] if 1 < sequence <= len(ctx.phase_a_chain) + 1 else None
        previous_result = None
        if previous_entry is not None:
            try:
                previous_result = repo.get_transaction_result(
                    ctx.case_id, str(previous_entry.get("tx_id") or f"PA-TC-{sequence - 1:04d}")
                )
            except Exception:
                logger.warning("previous result unavailable for handoff derivation %s", ctx.case_id)
        handoff = case_memory.derive_handoff(
            handoff, sequence=sequence, entry=entry,
            previous_result=previous_result, previous_entry=previous_entry,
        )
        handoff["stale"] = False
    payload["handoff"] = handoff


def _canonical_verification(ctx: ToolContext, args: dict, *, force_pending: bool = False) -> dict:
    tx_id = ctx.current_tx_id
    if not tx_id:
        raise SchemaValidationError("TransactionVerification", ["no transaction under investigation"])
    active_transaction = _find_tx(ctx, tx_id) or {}
    active_entry = _phase_a_entry_for_id(ctx, tx_id) or {}
    expected_sequence = int(
        active_transaction.get("sequence")
        or active_entry.get("sequence")
        or active_entry.get("chain_position")
        or (tx_id.removeprefix("PA-TC-") if tx_id.startswith("PA-TC-") else 0)
    )
    if args.get("tx_id") != tx_id:
        raise SchemaValidationError("TransactionVerification", ["tx_id does not match the active transaction"])
    if args.get("sequence") != expected_sequence:
        raise SchemaValidationError("TransactionVerification", ["sequence does not match the active transaction"])

    previous_raw = {} if ctx.fresh_reverification else (repo.get_transaction_result(ctx.case_id, tx_id) or {})
    previous = _legacy_result(previous_raw, tx_id=tx_id, sequence=expected_sequence)
    payload = dict(args)
    if force_pending:
        payload["status"] = "PENDING_NOT_VERIFIED"
    payload["transaction_metadata"] = {
        **(previous.get("transaction_metadata") or {}),
        **_current_transaction_metadata(ctx, tx_id),
    }
    payload["transaction_metadata"].pop("_verification_checkpoint", None)
    payload["transaction_metadata"]["_document_manifest"] = {
        str(document["doc_id"]): str(document.get("status") or "unknown")
        for document in ctx.docs
    }
    if expected_sequence > 1:
        # Dependency-aware chain record: every non-root result stores, at save
        # time, which upstream links were unverified when it was produced.
        payload["transaction_metadata"]["chain_context"] = _upstream_chain_context(
            ctx.case_id, ctx.phase_a_chain, expected_sequence
        )
        chain_context = payload["transaction_metadata"].get("chain_context") or {}
        if chain_context.get("upstream_unverified") and not _has_dependency_section(str(payload.get("report") or "")):
            raise SchemaValidationError(
                "TransactionVerification",
                ["report must contain an '## Earlier transactions' section while an earlier chain link is unverified"],
            )
    payload["reviewed_document_ids"] = sorted(
        doc_id for doc_id in (
            set(previous.get("reviewed_document_ids") or []) | ctx.selected_document_ids
        ) if not _is_phase_a_only_document(ctx.by_id.get(doc_id) or {})
    )
    status = str(payload.get("status") or "")
    payload["verified_at"] = _now() if status in {
        "VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE",
    } else None
    payload["schema_version"] = SCHEMA_VERSION
    # Missing fields on a partial tool call inherit prior verified state; explicit
    # empty arrays are respected as deliberate updates. Completed updates also
    # inherit the prior dossier's observations and result content when omitted;
    # pending checkpoints (request_missing_documents) never carry findings.
    for key in ("cited_documents", "required_documents"):
        if key not in args and key in previous:
            payload[key] = previous[key]
    if not force_pending and normalize_status(status) not in {
        VerificationStatus.PENDING_NOT_VERIFIED.value,
        VerificationStatus.PENDING.value,
        VerificationStatus.IN_PROGRESS.value,
    }:
        for content_key in (
            "findings", "executive_summary", "verified_facts", "unverified_facts",
            "limitations", "contradictory_evidence", "handoff",
        ):
            if content_key not in args and previous.get(content_key):
                payload[content_key] = previous[content_key]
    # Case-membership gate for contradictory evidence (review defect 2): every
    # reference — model-supplied or inherited above — must cite a document in
    # this case. Rejected hard instead of silently persisting a foreign id;
    # structural validity of each ref is enforced by the canonical contract
    # validation below.
    contradictory_refs = payload.get("contradictory_evidence")
    if contradictory_refs:
        case_doc_ids = set(ctx.by_id)
        foreign_ids = sorted({
            str(ref.get("doc_id"))
            for ref in contradictory_refs
            if isinstance(ref, dict) and ref.get("doc_id") and str(ref.get("doc_id")) not in case_doc_ids
        })
        if foreign_ids:
            raise SchemaValidationError("TransactionVerification", [
                f"contradictory_evidence cites documents outside this case: {foreign_ids}; "
                "nothing was saved",
                "set contradictory_evidence to [] to clear inherited references that no longer apply",
            ])
    for requirement in payload.get("required_documents") or []:
        owner_tx_id = requirement.get("for_transaction")
        if owner_tx_id and owner_tx_id != tx_id:
            raise SchemaValidationError(
                "TransactionVerification",
                [f"required_documents entry belongs to {owner_tx_id}, not active transaction {tx_id}"],
            )
    if isinstance(payload.get("required_documents"), list):
        earlier_requests = _earlier_requests(ctx.case_id, expected_sequence)
        duplicate_request_errors = []
        for requirement in payload["required_documents"]:
            label = str(requirement.get("document_type") or "")
            owners = sorted({tx for _, earlier_label, tx in earlier_requests if _requests_match(label, earlier_label)})
            if owners:
                duplicate_request_errors.append(
                    "%s is already requested by earlier transaction(s) %s; remove it from "
                    "required_documents and state in the report that this transaction relies "
                    "on that earlier request" % (label, ", ".join(owners))
                )
        if duplicate_request_errors:
            raise SchemaValidationError("TransactionVerification", duplicate_request_errors)
        available_errors = _available_document_request_errors(ctx, payload["required_documents"])
        if available_errors:
            raise SchemaValidationError("TransactionVerification", available_errors)
    if isinstance(payload.get("cited_documents"), list):
        prior_citations = {
            (ref.get("doc_id"), ref.get("pages"))
            for ref in previous.get("cited_documents") or [] if isinstance(ref, dict)
        }
        citation_errors = []
        for index, reference in enumerate(payload["cited_documents"]):
            doc_id = reference.get("doc_id")
            if doc_id not in ctx.by_id:
                citation_errors.append(f"cited_documents[{index}] cites a document outside this case: {doc_id}")
            elif _is_phase_a_only_document(ctx.by_id[doc_id]):
                citation_errors.append(
                    f"cited_documents[{index}] cites an encumbrance certificate, which is title-chain-only and not transaction evidence: {doc_id}"
                )
            elif (doc_id, reference.get("pages")) in prior_citations:
                continue
            elif doc_id not in ctx.selected_document_ids or not _has_read_full_text(ctx, doc_id):
                citation_errors.append(f"cited_documents[{index}] cites a document whose complete OCR was not reviewed: {doc_id}")
        if citation_errors:
            raise SchemaValidationError("TransactionVerification", citation_errors)
        payload["cited_documents"] = _dedupe(payload["cited_documents"])

    if isinstance(payload.get("reviewed_document_ids"), list):
        unknown_reviewed = sorted(
            set(payload["reviewed_document_ids"]) - set(ctx.by_id) - set(previous.get("reviewed_document_ids") or [])
        )
        if unknown_reviewed:
            raise SchemaValidationError(
                "TransactionVerification", [f"reviewed_document_ids contains unknown document IDs: {unknown_reviewed}"]
            )
    if isinstance(payload.get("required_documents"), list):
        payload["required_documents"] = _dedupe(payload["required_documents"], requirement=True)
    # Dossier evidence relationships to the chain it verified: every earlier
    # chain link's stable id (application-supplied context, not model data).
    payload["upstream_dependencies"] = []
    for entry in ctx.phase_a_chain:
        position = int(entry.get("chain_position") or 0)
        if position and position < expected_sequence:
            payload["upstream_dependencies"].append(
                str(entry.get("tx_id") or f"PA-TC-{position:04d}")
            )
    # -- typed findings: per-finding validation before persistence. Invalid ones
    # -- are excluded from the saved result (logged here, reported back in the
    # -- save response) so one bad observation can never destroy good ones.
    _validated_findings(ctx, tx_id, payload)
    _validate_handoff(ctx, payload, previous, expected_sequence, force_pending=force_pending)
    # Scope is application data (what this dossier was verified against); any
    # model-supplied value is overwritten here (master rule: app owns all IDs
    # and state).
    chain_context = (payload.get("transaction_metadata") or {}).get("chain_context")
    payload["scope"] = {
        "phase_a_hash": ctx.phase_a_hash or None,
        "chain_context_hash": content_hash(chain_context) if chain_context else None,
    }
    validated = validate_transaction_verification(payload)
    return validated.model_dump()


def _current_transaction_metadata(ctx: ToolContext, tx_id: str) -> dict:
    transaction = _find_tx(ctx, tx_id) or {}
    if not transaction:
        entry = _phase_a_entry_for_id(ctx, tx_id) or {}
        transaction = dict(entry.get("documented_transaction") or {})
        transaction["chain_position"] = entry.get("chain_position")
        transaction["is_current_owner_transaction"] = bool(
            entry and entry is ctx.phase_a_chain[-1]
        )
        transaction["related_events"] = entry.get("related_events") or []
    metadata = {
        key: transaction.get(key) for key in (
            "transaction_type", "executed_date", "registration_number", "registration_date",
            "registration_office", "consideration", "transaction_number", "vendors", "purchasers",
            "property_type", "property_schedule", "cts_number",
            "survey_number", "plot_number", "site_flat_number", "property_location", "schedule_property",
            "conveyed_portion", "chain_position", "is_current_owner_transaction",
        ) if transaction.get(key) is not None
    }
    if isinstance(metadata.get("transaction_type"), str):
        metadata["transaction_type"] = re.sub(
            r"\s*\(EC entry;\s*instrument not supplied\)",
            "",
            metadata["transaction_type"],
            flags=re.IGNORECASE,
        ).strip()
    if not metadata.get("vendors") or not metadata.get("purchasers"):
        # Canonical structured parties (task §4) fill the API-facing legacy keys
        # before any prose parsing is attempted.
        for canonical, legacy in (("transferors", "vendors"), ("transferees", "purchasers")):
            names = transaction.get(canonical)
            if not metadata.get(legacy) and isinstance(names, list):
                cleaned = [str(name).strip() for name in names if str(name or "").strip()]
                if cleaned:
                    metadata[legacy] = cleaned
    if not metadata.get("vendors") or not metadata.get("purchasers"):
        for point in transaction.get("summary_points") or []:
            match = re.match(
                r"\s*(?P<vendor>.+?)\s+(?:conveyed|sold|transferred|gifted|released)\b"
                r".*\bto\s+(?P<purchaser>[^.;]+)[.;]?\s*$",
                str(point),
                flags=re.IGNORECASE,
            )
            if match:
                metadata.setdefault("vendors", [match.group("vendor").strip()])
                metadata.setdefault("purchasers", [match.group("purchaser").strip()])
                break
    # A death date is the reported succession event date, not an instrument
    # execution date. Preserve it in the report/evidence, never in executed_date.
    tx_type = str(transaction.get("transaction_type") or "").casefold()
    if any(term in tx_type for term in ("succession", "inheritance", "death")):
        metadata.pop("executed_date", None)
    if transaction.get("related_events"):
        metadata["related_events"] = _without_source_refs(transaction["related_events"])
    return metadata


def _h_save_transaction_result(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id or ""
    try:
        if args.get("status") in {
            "VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE",
        }:
            unread = sorted(doc_id for doc_id in ctx.selected_document_ids if not _has_read_full_text(ctx, doc_id))
            if not ctx.selected_document_ids or unread:
                ctx.result_error = "full OCR must be read for every selected supporting document before a completed result can be saved"
                return {"error": ctx.result_error, "unread_document_ids": unread}
        payload = _canonical_verification(ctx, args)
        if payload["status"] == "PENDING_NOT_VERIFIED" and not payload.get("required_documents"):
            # Reliance on an earlier link's outstanding requests is a valid
            # pending state; only demand an own request when none is outstanding.
            if not _earlier_requests(ctx.case_id, int(payload.get("sequence") or 0)):
                return {
                    "error": "PENDING_NOT_VERIFIED requires at least one specific required_documents entry; "
                    "use INCONCLUSIVE if no user-uploadable evidence request is known",
                }
        compactness_errors = _result_compactness_errors(payload)
        if compactness_errors:
            raise SchemaValidationError("TransactionVerification", compactness_errors)
        if payload.get("required_documents"):
            issue = _validate_missing_requirements(ctx, payload["required_documents"])
            if issue:
                return issue
    except SchemaValidationError as e:
        ctx.result_error = str(e)
        return {"error": f"invalid transaction result: {e}", "issues": e.errors}
    except RegistryReadUnavailable as e:
        ctx.result_error = str(e)
        return {"error": str(e), "retryable": True}
    try:
        logger.info("agent_result_persist_attempt run_id=%s tx_id=%s", ctx.run_id, tx_id)
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=payload)
    except Exception as e:
        logger.exception("save_transaction_result failed for %s/%s", ctx.case_id, tx_id)
        ctx.result_error = f"failed to persist result: {e}"
        return {"error": f"failed to persist result: {e}"}
    ctx.result_error = None
    ctx.saved_results.append(payload)
    logger.info(
        "agent_result_persisted run_id=%s tx_id=%s status=%s reviewed_doc_ids=%s",
        ctx.run_id, tx_id, payload.get("status"), payload.get("reviewed_document_ids"),
    )
    # Persistence is the transaction's terminal action. Do not spend another
    # model turn asking it to finish or allowing it to reopen the investigation.
    ctx.finished = True
    missing_documents = payload.get("required_documents") or []
    response = {"saved": True, "tx_id": tx_id, "status": payload["status"]}
    if payload["status"] == "PENDING_NOT_VERIFIED" and missing_documents:
        # Models may save a pending result directly instead of calling the
        # explicit missing-document tool. Either representation must pause this
        # transaction so the UI never advances past an unserved evidence request.
        ctx.missing_requests.append({"tx_id": tx_id, "documents": missing_documents})
        response = {"saved": True, "paused": True, "tx_id": tx_id, "required_documents": missing_documents}
    if ctx.rejected_findings:
        response["rejected_findings"] = ctx.rejected_findings
    return response


def _h_request_missing(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id
    if not tx_id:
        return {"error": "no transaction under investigation"}
    if not isinstance(args.get("required_documents"), list) or not args["required_documents"]:
        return {
            "error": "provide at least one specific required_documents entry to pause and ask the user; "
            "if this transaction only relies on documents already requested by earlier "
            "transactions, use save_transaction_result with status PENDING_NOT_VERIFIED "
            "and no required_documents instead",
        }
    canonical_args = dict(args)
    canonical_args["status"] = "PENDING_NOT_VERIFIED"
    try:
        if not ctx.evidence_requirements or not ctx.documents_listed:
            return {"error": "record transaction requirements and search document summaries before requesting missing evidence"}
        verification = _canonical_verification(ctx, canonical_args, force_pending=True)
        compactness_errors = _result_compactness_errors(verification)
        if compactness_errors:
            raise SchemaValidationError("TransactionVerification", compactness_errors)
        issue = _validate_missing_requirements(ctx, verification["required_documents"])
        if issue:
            return issue
    except SchemaValidationError as e:
        ctx.result_error = str(e)
        return {"error": f"invalid transaction result: {e}", "issues": e.errors}
    try:
        logger.info("agent_missing_request_persist_attempt run_id=%s tx_id=%s", ctx.run_id, tx_id)
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=verification)
    except Exception as e:
        logger.exception("request_missing_documents failed for %s/%s", ctx.case_id, tx_id)
        ctx.result_error = f"failed to persist request: {e}"
        return {"error": f"failed to persist request: {e}"}
    ctx.result_error = None
    ctx.missing_requests.append({"tx_id": tx_id, "documents": verification["required_documents"]})
    ctx.finished = True
    logger.info("agent_missing_request_persisted run_id=%s tx_id=%s", ctx.run_id, tx_id)
    return {"paused": True, "tx_id": tx_id, "required_documents": verification["required_documents"]}


def _h_finish(ctx: ToolContext, args: dict) -> dict:
    if ctx.current_tx_id and not ctx.saved_results and not ctx.missing_requests:
        return {
            "error": "the active transaction has no saved result; call save_transaction_result "
            "or request_missing_documents before finish"
        }
    ctx.finished = True
    return {"ok": True}


def _h_request_more_calls(ctx: ToolContext, args: dict) -> dict:
    next_step = str(args.get("next_step") or "").strip()
    if len(next_step) < 12 or len(next_step) > 400:
        return {"error": "next_step must describe a concrete evidence check (12–400 characters)"}
    if ctx.additional_model_calls_used:
        return {"error": "the one permitted verification-budget extension was already used"}
    ctx.additional_model_calls_used = True
    ctx.additional_model_calls = 8
    logger.info("agent_verification_budget_extended run_id=%s tx_id=%s extra_calls=%s reason=%s", ctx.run_id, ctx.current_tx_id, ctx.additional_model_calls, next_step)
    return {"granted_additional_calls": ctx.additional_model_calls, "hard_cap": 24}


_HANDLERS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "list_documents": _h_list_documents,
    "get_document_metadata": _h_doc_metadata,
    "get_document_text": _h_doc_text,
    "record_evidence_requirements": _h_record_requirements,
    "select_documents": _h_select_documents,
    "record_observation": _h_record_observation,
    "save_phase_a_result": _h_save_phase_a_result,
    "list_transactions": _h_list_transactions,
    "get_transaction": _h_get_transaction,
    "save_transaction_result": _h_save_transaction_result,
    "request_missing_documents": _h_request_missing,
    "request_additional_verification_calls": _h_request_more_calls,
    "finish": _h_finish,
}


def dispatch(ctx: ToolContext, name: str, args: dict) -> dict:
    """Execute one tool call. Never raises; returns a JSON-serializable dict."""
    if ctx.finished:
        return {"error": "active transaction is already terminal; no further tools may run"}
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name!r}"}
    call_key = json.dumps([name, args or {}], sort_keys=True, ensure_ascii=False, default=str)
    prior_count = ctx.tool_call_fingerprints.get(call_key, 0)
    if prior_count:
        ctx.repeated_tool_calls += 1
    ctx.tool_call_fingerprints[call_key] = prior_count + 1
    if call_key in ctx.tool_result_cache:
        logger.warning(
            "agent_duplicate_tool_call run_id=%s tx_id=%s tool=%s repeat=%s",
            ctx.run_id, ctx.current_tx_id, name, ctx.repeated_tool_calls,
        )
        return ctx.tool_result_cache[call_key]
    ctx.tool_call_counts[name] = ctx.tool_call_counts.get(name, 0) + 1
    try:
        result = handler(ctx, args or {})
        if not (isinstance(result, dict) and result.get("error")):
            ctx.tool_result_cache[call_key] = result
        return result
    except SchemaValidationError as e:
        return {"error": f"invalid arguments: {e}", "issues": e.errors}
    except Exception as e:
        logger.exception("tool %s failed for case %s", name, getattr(ctx, "case_id", "?"))
        return {"error": str(e)}
