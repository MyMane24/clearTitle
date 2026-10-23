"""Tools exposed to the ClearTitle verification agent.

The LLM investigates ONLY through these tools. Handlers are thin wrappers over
existing repositories/services; they validate arguments, persist through the
authoritative stores, and return compact JSON results.

The application (not the model) assigns stable transaction ids and persists each
transaction result before advancing workflow state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from backend.database.repositories import agent_repo as repo
from backend.logger import get_logger
from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    SchemaValidationError,
    TransactionVerification,
    validate_transaction_verification,
    normalize_transaction_verification,
)

logger = get_logger(__name__)

_DEFAULT_TEXT_CHARS = 40000
_TEXT_CAP = 200000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolContext:
    """Mutable state shared across one agent run."""

    def __init__(self, case_id: str, docs: list[dict], chain: dict | None = None,
                 current_tx_id: str | None = None, phase_a_chain: list[dict] | None = None):
        self.case_id = case_id
        self.docs = docs
        self.by_id = {d["doc_id"]: d for d in docs}
        self.chain = chain or {}
        self.phase_a_chain = phase_a_chain or []
        self.current_tx_id = current_tx_id
        self.evidence_requirements: list[dict] = []
        self.listed_document_ids: set[str] = set()
        self.documents_listed = False
        self.selected_document_ids: set[str] = set()
        self.saved_phase_a_result: dict | None = None
        self.saved_results: list[dict] = []
        self.missing_requests: list[dict] = []
        self.result_error: str | None = None
        self.finished = False


# ── JSON schema for tools: generated from the canonical Pydantic contract ──────


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
    return {key: value for key, value in inlined.items() if key not in {"$schema", "title"}}


_LIST_DOCS = {
    "name": "list_documents",
    "description": "List all uploaded document IDs and their saved summaries. No other document fields are available to this phase.",
    "parameters": {"type": "object", "properties": {}},
}
_DOC_META = {
    "name": "get_document_metadata",
    "description": "Get metadata and structured extraction for one document.",
    "parameters": {"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]},
}
_DOC_TEXT = {
    "name": "get_document_text",
    "description": "Read a chunk of one document's merged OCR text directly from the database.",
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
    "description": "After reading saved summaries, select candidate document IDs to inspect. Only selected IDs can be fetched as OCR text.",
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
            "summary": _canonical_result_schema["properties"]["summary"],
            "findings": _canonical_result_schema["properties"]["findings"],
            "required_documents": _canonical_result_schema["properties"]["required_documents"],
        },
        "required": ["tx_id", "sequence", "summary", "required_documents"],
    },
}
PHASE_A_TOOLS = [_LIST_DOCS, _DOC_TEXT, _SAVE_PHASE_A, _FINISH]
VERIFY_TOOLS = [_LIST_TX, _GET_TX, _RECORD_REQUIREMENTS,
                _LIST_DOCS, _SELECT_DOCUMENTS, _DOC_TEXT,
                _SAVE_RESULT, _REQ_MISSING, _FINISH]


def tools_for(phase: str) -> list[dict]:
    return {"phase_a": PHASE_A_TOOLS,
            "verify": VERIFY_TOOLS}.get(phase, [])


# ── helpers ───────────────────────────────────────────────────────────────────


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


# ── handlers ──────────────────────────────────────────────────────────────────


def _h_list_documents(ctx: ToolContext, args: dict) -> dict:
    if ctx.current_tx_id and not ctx.evidence_requirements:
        return {"error": "record evidence requirements from the transaction and verification skill before searching summaries"}
    documents = [
        {
            "doc_id": d["doc_id"], "filename": d.get("filename") or "",
            "document_type": d.get("document_type") or "",
            "status": d.get("status") or "unknown",
            "summary": d.get("summary") or "(summary unavailable)",
        }
        for d in ctx.docs
    ]
    ctx.listed_document_ids = {d["doc_id"] for d in documents}
    ctx.documents_listed = True
    return {"documents": documents}


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
    ctx.evidence_requirements = normalized
    return {"recorded": True, "requirements": normalized}


def _h_select_documents(ctx: ToolContext, args: dict) -> dict:
    if ctx.current_tx_id and (not ctx.evidence_requirements or not ctx.documents_listed):
        return {"error": "record evidence requirements and search summaries before selecting documents"}
    doc_ids = args.get("doc_ids")
    if not isinstance(doc_ids, list) or any(doc_id not in ctx.listed_document_ids for doc_id in doc_ids):
        return {"error": "select only document IDs returned by list_documents"}
    ctx.selected_document_ids = set(doc_ids)
    return {"selected": sorted(ctx.selected_document_ids)}


def _h_doc_metadata(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    meta = repo.get_document_metadata(ctx.case_id, doc_id)
    return meta if meta else {"error": f"no document {doc_id!r} in case"}


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
    text = repo.get_document_raw_text(ctx.case_id, doc_id)
    end_char = min(start_char + max_chars, len(text))
    return {
        "doc_id": doc_id,
        "total_chars": len(text),
        "start_char": start_char,
        "next_start_char": end_char if end_char < len(text) else None,
        "has_more": end_char < len(text),
        "text": text[start_char:end_char],
    }


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
        if entry.get("chain_position") != index + 1:
            return {"error": "title_chain must be numbered from earliest supported root to current/latest owner"}
        if "unresolved" in entry:
            return {"error": f"do not add an unresolved field to title_chain[{index}]"}
        transaction = entry.get("documented_transaction")
        if not isinstance(transaction, dict) or not transaction:
            return {"error": f"title_chain[{index}].documented_transaction must contain the open-ended transaction details"}
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
    repo.save_phase_a_result(case_id=ctx.case_id, result=result)
    ctx.saved_phase_a_result = result
    return {"saved": True}


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
                "tx_id": f"PA-TC-{index:04d}",
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
         "vendors": t.get("vendors"), "purchasers": t.get("purchasers")}
        for t in (ctx.chain or {}).get("transactions") or []
    ]}


def _h_get_transaction(ctx: ToolContext, args: dict) -> dict:
    tx_id = str(args.get("tx_id") or ctx.current_tx_id or "")
    tx = _find_tx(ctx, tx_id)
    if tx is not None:
        return {"transaction": tx, "verification_result": _prior_result_for_agent(ctx, tx_id, int(tx.get("sequence") or 0))}
    entry = _phase_a_entry_for_id(ctx, tx_id)
    if entry is None:
        return {"error": f"no transaction {tx_id!r} in chain"}
    transaction = dict(entry.get("documented_transaction") or {})
    transaction.update({"tx_id": tx_id, "sequence": entry.get("chain_position")})
    transaction["related_events"] = entry.get("related_events") or []
    return {
        "transaction": transaction,
        "verification_result": _prior_result_for_agent(ctx, tx_id, int(entry.get("chain_position") or 0)),
    }


def _prior_result_for_agent(ctx: ToolContext, tx_id: str, sequence: int) -> dict | None:
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


def _legacy_result(previous: dict, *, tx_id: str, sequence: int) -> dict:
    """Adapt an existing result for resume without changing its persisted row."""
    result = dict(previous or {})
    result.setdefault("tx_id", tx_id)
    result.setdefault("sequence", sequence)
    result.setdefault("status", "PENDING")
    result.setdefault("summary", "No prior verification summary was recorded.")
    return normalize_transaction_verification(result)


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

    previous_raw = repo.get_transaction_result(ctx.case_id, tx_id) or {}
    previous = _legacy_result(previous_raw, tx_id=tx_id, sequence=expected_sequence)
    payload = dict(args)
    if force_pending:
        payload["status"] = "PENDING_NOT_VERIFIED"
    payload["transaction_metadata"] = {
        **(previous.get("transaction_metadata") or {}),
        **_current_transaction_metadata(ctx, tx_id),
    }
    payload["reviewed_document_ids"] = sorted(
        set(previous.get("reviewed_document_ids") or []) | ctx.selected_document_ids
    )
    status = str(payload.get("status") or "")
    payload["verified_at"] = _now() if status in {
        "VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE",
    } else None
    payload["schema_version"] = SCHEMA_VERSION
    # Missing fields on a partial tool call inherit prior verified state; explicit
    # empty arrays are respected as deliberate updates.
    for key in ("findings", "required_documents"):
        if key not in args and key in previous:
            payload[key] = previous[key]
    if isinstance(payload.get("findings"), list):
        payload["findings"] = _dedupe(payload["findings"])
    if isinstance(payload.get("required_documents"), list):
        payload["required_documents"] = _dedupe(payload["required_documents"], requirement=True)
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
            "transaction_number", "vendors", "purchasers", "survey_number", "plot_number",
            "site_flat_number", "property_location", "schedule_property", "conveyed_portion",
            "chain_position", "is_current_owner_transaction",
        ) if transaction.get(key) is not None
    }
    # A death date is the reported succession event date, not an instrument
    # execution date. Preserve it in evidence/findings, never in executed_date.
    tx_type = str(transaction.get("transaction_type") or "").casefold()
    if any(term in tx_type for term in ("succession", "inheritance", "death")):
        metadata.pop("executed_date", None)
    if transaction.get("related_events"):
        metadata["related_events"] = transaction["related_events"]
    return metadata


def _h_save_transaction_result(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id or ""
    try:
        payload = _canonical_verification(ctx, args)
    except SchemaValidationError as e:
        ctx.result_error = str(e)
        return {"error": f"invalid transaction result: {e}", "issues": e.errors}
    try:
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=payload)
    except Exception as e:  # noqa: BLE001 - surface persistence failure, do NOT mark done
        logger.exception("save_transaction_result failed for %s/%s", ctx.case_id, tx_id)
        ctx.result_error = f"failed to persist result: {e}"
        return {"error": f"failed to persist result: {e}"}
    ctx.result_error = None
    ctx.saved_results.append(payload)
    missing_documents = payload.get("required_documents") or []
    if payload["status"] == "PENDING_NOT_VERIFIED" and missing_documents:
        # Models may save a pending result directly instead of calling the
        # explicit missing-document tool. Either representation must pause this
        # transaction so the UI never advances past an unserved evidence request.
        ctx.missing_requests.append({"tx_id": tx_id, "documents": missing_documents})
        return {
            "saved": True,
            "paused": True,
            "tx_id": tx_id,
            "required_documents": missing_documents,
        }
    return {"saved": True, "tx_id": tx_id, "status": payload["status"]}


def _h_request_missing(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id
    if not tx_id:
        return {"error": "no transaction under investigation"}
    canonical_args = dict(args)
    canonical_args["status"] = "PENDING_NOT_VERIFIED"
    try:
        verification = _canonical_verification(ctx, canonical_args, force_pending=True)
    except SchemaValidationError as e:
        ctx.result_error = str(e)
        return {"error": f"invalid transaction result: {e}", "issues": e.errors}
    try:
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=verification)
    except Exception as e:  # noqa: BLE001
        logger.exception("request_missing_documents failed for %s/%s", ctx.case_id, tx_id)
        ctx.result_error = f"failed to persist request: {e}"
        return {"error": f"failed to persist request: {e}"}
    ctx.result_error = None
    ctx.missing_requests.append({"tx_id": tx_id, "documents": verification["required_documents"]})
    return {"paused": True, "tx_id": tx_id, "required_documents": verification["required_documents"]}


def _h_finish(ctx: ToolContext, args: dict) -> dict:
    ctx.finished = True
    return {"ok": True}


_HANDLERS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "list_documents": _h_list_documents,
    "get_document_metadata": _h_doc_metadata,
    "get_document_text": _h_doc_text,
    "record_evidence_requirements": _h_record_requirements,
    "select_documents": _h_select_documents,
    "save_phase_a_result": _h_save_phase_a_result,
    "list_transactions": _h_list_transactions,
    "get_transaction": _h_get_transaction,
    "save_transaction_result": _h_save_transaction_result,
    "request_missing_documents": _h_request_missing,
    "finish": _h_finish,
}


def dispatch(ctx: ToolContext, name: str, args: dict) -> dict:
    """Execute one tool call. Never raises; returns a JSON-serializable dict."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return handler(ctx, args or {})
    except SchemaValidationError as e:
        return {"error": f"invalid arguments: {e}", "issues": e.errors}
    except Exception as e:  # noqa: BLE001 - tool failure is reported, never fatal
        logger.exception("tool %s failed for case %s", name, getattr(ctx, "case_id", "?"))
        return {"error": str(e)}
