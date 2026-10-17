"""Tools exposed to the ClearTitle verification agent.

The LLM investigates ONLY through these tools. Handlers are thin wrappers over
existing repositories/services; they validate arguments, persist through the
authoritative stores, and return compact JSON results.

The application (not the model) assigns stable transaction ids and enforces the
rule that a TODO is marked COMPLETED only after its result has been persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from backend.database.repositories import agent_repo as repo
from backend.logger import get_logger
from backend.services import agent_rules
from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    SchemaValidationError,
    TitleChain,
    TodoState,
    TransactionVerification,
    normalize_status,
    validate_title_chain,
)

logger = get_logger(__name__)

_DEFAULT_TEXT_CHARS = 40000
_TEXT_CAP = 200000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolContext:
    """Mutable state shared across one agent run."""

    def __init__(self, case_id: str, docs: list[dict], chain: dict | None = None,
                 current_tx_id: str | None = None):
        self.case_id = case_id
        self.docs = docs
        self.by_id = {d["doc_id"]: d for d in docs}
        self.chain = chain or {}
        self.current_tx_id = current_tx_id
        self.saved_chain: dict | None = None
        self.saved_phase_a_result: dict | None = None
        self.saved_results: list[dict] = []
        self.missing_requests: list[dict] = []
        self.saved_report: dict | None = None
        self.finished = False


# ── json-schema fragments ─────────────────────────────────────────────────────


def _ref_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "page": {"type": "string"},
            "passage": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["doc_id"],
    }


def _finding_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "significance": {"type": "string"},
            "explanation": {"type": "string"},
            "source_refs": {"type": "array", "items": _ref_schema()},
        },
        "required": ["description"],
    }


def _missing_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "document_type": {"type": "string"},
            "reason": {"type": "string"},
            "for_transaction": {"type": "string"},
        },
        "required": ["document_type"],
    }


def _verification_props() -> dict:
    return {
        "status": {"type": "string"},
        "conclusion": {"type": "string"},
        "reasoning": {"type": "string"},
        "findings": {"type": "array", "items": _finding_schema()},
        "supporting_evidence": {"type": "array", "items": _ref_schema()},
        "contradictory_evidence": {"type": "array", "items": _ref_schema()},
        "missing_documents": {"type": "array", "items": _missing_schema()},
        "impact": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "rule_versions": {"type": "array", "items": {"type": "string"}},
    }


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
_SAVE_CHAIN = {
    "name": "save_title_chain",
    "description": "Persist the authoritative property identity + chronological title chain. Call once.",
    "parameters": {"type": "object", "properties": {"chain": {"type": "object"}}, "required": ["chain"]},
}
_LIST_TX = {"name": "list_transactions", "description": "List the title-chain transactions.", "parameters": {"type": "object", "properties": {}}}
_GET_TX = {
    "name": "get_transaction",
    "description": "Get one transaction by tx_id, with its saved verification result if any.",
    "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}}, "required": ["tx_id"]},
}
_LOAD_RULES = {
    "name": "load_rules",
    "description": "Load the verification rules applicable to a transaction.",
    "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}}, "required": ["tx_id"]},
}
_SAVE_RESULT = {
    "name": "save_transaction_result",
    "description": "Persist the verification result for the transaction under investigation.",
    "parameters": {"type": "object", "properties": _verification_props(), "required": ["status"]},
}
_REQ_MISSING = {
    "name": "request_missing_documents",
    "description": "Pause this transaction: name the required document(s) that are missing.",
    "parameters": {
        "type": "object",
        "properties": {
            "documents": {"type": "array", "items": _missing_schema()},
            "conclusion": {"type": "string"},
            "reasoning": {"type": "string"},
            "findings": {"type": "array", "items": _finding_schema()},
        },
        "required": ["documents"],
    },
}
_SAVE_REPORT = {
    "name": "save_report",
    "description": "Persist the consolidated final report. Call once.",
    "parameters": {"type": "object", "properties": {"report": {"type": "object"}}, "required": ["report"]},
}

PHASE_A_TOOLS = [_LIST_DOCS, _DOC_TEXT, _SAVE_PHASE_A, _FINISH]
CHAIN_TOOLS = [_LIST_DOCS, _DOC_META, _DOC_TEXT, _SAVE_CHAIN, _FINISH]
VERIFY_TOOLS = [_LIST_TX, _GET_TX, _LOAD_RULES, _DOC_META, _DOC_TEXT, _SAVE_RESULT, _REQ_MISSING, _FINISH]
FINAL_TOOLS = [_LIST_TX, _GET_TX, _DOC_TEXT, _SAVE_REPORT, _FINISH]


def tools_for(phase: str) -> list[dict]:
    return {"phase_a": PHASE_A_TOOLS, "chain": CHAIN_TOOLS, "verify": VERIFY_TOOLS, "final": FINAL_TOOLS}.get(phase, [])


# ── helpers ───────────────────────────────────────────────────────────────────


def _assign_ids(chain: TitleChain) -> TitleChain:
    """Assign a stable tx_id / sequence to every transaction (once)."""
    for i, tx in enumerate(chain.transactions, start=1):
        if not tx.sequence:
            tx.sequence = i
        if not tx.tx_id:
            tx.tx_id = f"TX{tx.sequence:03d}"
    return chain


def _find_tx(ctx: ToolContext, tx_id: str) -> dict | None:
    return next((t for t in (ctx.chain or {}).get("transactions") or [] if t.get("tx_id") == tx_id), None)


# ── handlers ──────────────────────────────────────────────────────────────────


def _h_list_documents(ctx: ToolContext, args: dict) -> dict:
    return {"documents": [
        {"doc_id": d["doc_id"], "filename": d.get("filename") or "", "summary": d.get("summary") or ""}
        for d in ctx.docs
    ]}


def _h_doc_metadata(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    meta = repo.get_document_metadata(ctx.case_id, doc_id)
    return meta if meta else {"error": f"no document {doc_id!r} in case"}


def _h_doc_text(ctx: ToolContext, args: dict) -> dict:
    doc_id = str(args.get("doc_id") or "")
    if doc_id not in ctx.by_id:
        return {"error": f"no document {doc_id!r} in case"}
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


def _h_save_title_chain(ctx: ToolContext, args: dict) -> dict:
    raw = args.get("chain") if isinstance(args.get("chain"), dict) else args
    try:
        chain = _assign_ids(validate_title_chain(raw))
    except SchemaValidationError as e:
        return {"error": "invalid title chain", "issues": e.errors}
    repo.save_title_chain(case_id=ctx.case_id, chain=chain.model_dump())
    for tx in chain.transactions:
        repo.upsert_todo(
            case_id=ctx.case_id, tx_id=tx.tx_id, tx_index=tx.sequence,
            description=f"Verify transaction {tx.tx_id} ({tx.transaction_type or 'OTHER'})",
        )
    ctx.chain = chain.model_dump()
    ctx.saved_chain = chain.model_dump()
    return {"saved": True, "transactions": len(chain.transactions)}


def _h_list_transactions(ctx: ToolContext, args: dict) -> dict:
    return {"transactions": [
        {"tx_id": t.get("tx_id"), "sequence": t.get("sequence"),
         "type": t.get("transaction_type"), "executed_date": t.get("executed_date"),
         "vendors": t.get("vendors"), "purchasers": t.get("purchasers")}
        for t in (ctx.chain or {}).get("transactions") or []
    ]}


def _h_get_transaction(ctx: ToolContext, args: dict) -> dict:
    tx_id = str(args.get("tx_id") or ctx.current_tx_id or "")
    tx = _find_tx(ctx, tx_id)
    if tx is None:
        return {"error": f"no transaction {tx_id!r} in chain"}
    return {"transaction": tx, "verification_result": repo.get_transaction_result(ctx.case_id, tx_id)}


def _h_load_rules(ctx: ToolContext, args: dict) -> dict:
    tx_id = str(args.get("tx_id") or ctx.current_tx_id or "")
    tx = _find_tx(ctx, tx_id)
    if tx is None:
        return {"error": f"no transaction {tx_id!r} in chain"}
    rules = agent_rules.transaction_rules_for({"type": tx.get("transaction_type")})
    return {
        "rules": agent_rules.format_rules(rules),
        "rule_versions": [f"{r['id']}@{r['version']}" for r in rules],
    }


def _verification_from_args(args: dict, tx_id: str) -> dict:
    return {
        "tx_id": tx_id,
        "status": normalize_status(args.get("status")),
        "conclusion": args.get("conclusion") or "",
        "reasoning": args.get("reasoning") or "",
        "findings": args.get("findings") or [],
        "supporting_evidence": args.get("supporting_evidence") or [],
        "contradictory_evidence": args.get("contradictory_evidence") or [],
        "missing_documents": args.get("missing_documents") or [],
        "impact": args.get("impact"),
        "unresolved": args.get("unresolved") or [],
        "limitations": args.get("limitations") or [],
        "rule_versions": args.get("rule_versions") or [],
        "verified_at": _now(),
        "schema_version": SCHEMA_VERSION,
    }


def _h_save_transaction_result(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id
    if not tx_id:
        return {"error": "no transaction under investigation"}
    verification = TransactionVerification.model_validate(_verification_from_args(args, tx_id))
    try:
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=verification.model_dump())
    except Exception as e:  # noqa: BLE001 - surface persistence failure, do NOT mark done
        logger.exception("save_transaction_result failed for %s/%s", ctx.case_id, tx_id)
        return {"error": f"failed to persist result: {e}"}
    # TODO completed ONLY after the result has been persisted.
    repo.set_todo_state(case_id=ctx.case_id, tx_id=tx_id, state=TodoState.COMPLETED.value)
    ctx.saved_results.append(verification.model_dump())
    return {"saved": True, "tx_id": tx_id, "status": verification.status.value}


def _h_request_missing(ctx: ToolContext, args: dict) -> dict:
    tx_id = ctx.current_tx_id
    if not tx_id:
        return {"error": "no transaction under investigation"}
    verification = {
        "tx_id": tx_id,
        "status": normalize_status("PENDING_NOT_VERIFIED"),
        "conclusion": args.get("conclusion") or "Verification paused — a required document is missing.",
        "reasoning": args.get("reasoning") or "",
        "findings": args.get("findings") or [],
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "missing_documents": args.get("documents") or [],
        "impact": None,
        "unresolved": [],
        "limitations": [],
        "rule_versions": [],
        "verified_at": _now(),
        "schema_version": SCHEMA_VERSION,
    }
    try:
        repo.save_transaction_result(case_id=ctx.case_id, tx_id=tx_id, verification=verification)
    except Exception as e:  # noqa: BLE001
        logger.exception("request_missing_documents failed for %s/%s", ctx.case_id, tx_id)
        return {"error": f"failed to persist request: {e}"}
    repo.set_todo_state(case_id=ctx.case_id, tx_id=tx_id, state=TodoState.PENDING.value)
    ctx.missing_requests.append({"tx_id": tx_id, "documents": verification["missing_documents"]})
    return {"paused": True, "tx_id": tx_id, "missing_documents": verification["missing_documents"]}


def _h_save_report(ctx: ToolContext, args: dict) -> dict:
    ctx.saved_report = args.get("report") if isinstance(args.get("report"), dict) else args
    return {"saved": True}


def _h_finish(ctx: ToolContext, args: dict) -> dict:
    ctx.finished = True
    return {"ok": True}


_HANDLERS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "list_documents": _h_list_documents,
    "get_document_metadata": _h_doc_metadata,
    "get_document_text": _h_doc_text,
    "save_phase_a_result": _h_save_phase_a_result,
    "save_title_chain": _h_save_title_chain,
    "list_transactions": _h_list_transactions,
    "get_transaction": _h_get_transaction,
    "load_rules": _h_load_rules,
    "save_transaction_result": _h_save_transaction_result,
    "request_missing_documents": _h_request_missing,
    "save_report": _h_save_report,
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
