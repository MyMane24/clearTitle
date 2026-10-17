"""The ClearTitle verification agent — one primary tool-calling LLM agent.

The agent owns the post-OCR investigation: it builds the authoritative property
identity + chronological title chain, maintains a durable per-transaction TODO
checklist, verifies each transaction through tools, and produces the final report.

The LLM interprets documents and decides outcomes; this module only orchestrates
(phases, locking, resume) and persists through the repositories. It never decides
a transaction's legal status itself.

Pause/resume: when a transaction needs a missing document the run pauses, the
TODO stays PENDING, and the request is saved. Re-running (`--analyze`) after the
document pipeline has processed new uploads resumes without rebuilding the chain.
"""

from __future__ import annotations

import json

from backend.config import PIPELINE_LOCK_ENABLED
from backend.database.repositories import agent_repo as repo
from backend.database.repositories.case_repo import set_case_verification_status
from backend.integrations.llm.agent_llm import AgentLLMError, complete_json
from backend.integrations.redis.lock import RedisLock
from backend.logger import get_logger
from backend.prompts.loader import load_prompt
from backend.services import agent_rules
from backend.services.agent_runtime import run_tool_loop
from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    TodoState,
    normalize_status,
)
from backend.services.agent_tools import ToolContext, _now

logger = get_logger(__name__)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_ERROR = "error"

_CHAIN_MAX_STEPS = 10
_VERIFY_MAX_STEPS = 12
_FINAL_MAX_STEPS = 6
_PHASE_A_MAX_STEPS = 80


# ── document summaries (cheap navigation aid, generated only when missing) ────


def ensure_summaries(case_id: str, docs: list[dict]) -> None:
    for doc in docs:
        if doc.get("summary"):
            continue
        text = repo.get_document_raw_text(case_id, doc["doc_id"])
        label = doc.get("document_type") or "UNKNOWN"
        if not text:
            summary = f"{label}: (no OCR text available)"
        else:
            prompt = (
                load_prompt("agent_summary")
                + f"\n\nDOCUMENT TYPE: {label}"
                + f"\nFILENAME: {doc.get('filename') or ''}"
                + f"\n\n--- DOCUMENT CONTENT ---\n{text[:6000]}"
            )
            try:
                out = complete_json(prompt, task="agent_summary")
                summary = str(out.get("summary") or "").strip()
            except Exception as e:  # a summary failure must not kill the run
                logger.warning("summary failed for %s/%s: %s", case_id, doc["doc_id"], e)
                summary = f"{label}: (summary unavailable)"
        if not summary:
            summary = f"{label}: (summary unavailable)"
        repo.set_document_summary(case_id=case_id, doc_id=doc["doc_id"], summary=summary)
        doc["summary"] = summary


# ── phase instructions ────────────────────────────────────────────────────────


def _doc_list(docs: list[dict]) -> str:
    return "\n".join(
        f"- {d['doc_id']} | {d.get('document_type') or 'UNKNOWN'} | {d.get('filename') or ''} | {d.get('summary') or '(no summary)'}"
        for d in docs
    )


def _chain_instruction(docs: list[dict]) -> str:
    return load_prompt("agent_chain_task") + "\n\n--- CASE DOCUMENTS ---\n" + _doc_list(docs)


def _phase_a_instruction(docs: list[dict]) -> str:
    manifest = "\n".join(
        f"- {doc['doc_id']} | citation filename: {doc.get('filename') or '(filename unavailable)'} | summary: {doc.get('summary') or '(no saved summary)'}"
        for doc in docs
    )
    skill = (repo_skill_path()).read_text(encoding="utf-8")
    return (
        "MANDATORY SKILL — FOLLOW THIS FOR EVERY TITLE-CHAIN BUILD\n\n"
        + skill
        + "\n\n"
        + load_prompt("title_chain_task")
        + "\n\n--- ALL UPLOADED DOCUMENT SUMMARIES ---\n"
        + manifest
    )


def repo_skill_path():
    """Resolve the mandatory skill file from the backend package tree."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "skills" / "title_chain" / "skill.md"


def _verify_instruction(tx: dict) -> str:
    rules = agent_rules.transaction_rules_for({"type": tx.get("transaction_type")})
    return (
        load_prompt("agent_verify_task")
        + "\n\n--- TRANSACTION UNDER INVESTIGATION ---\n"
        + json.dumps(tx, ensure_ascii=False, default=str, indent=2)
        + "\n\n--- APPLICABLE RULES ---\n"
        + agent_rules.format_rules(rules)
    )


def _final_instruction(merged: list[dict]) -> str:
    compact = [
        {
            "tx_id": t.get("tx_id"),
            "sequence": t.get("sequence"),
            "type": t.get("transaction_type"),
            "executed_date": t.get("executed_date"),
            "status": t.get("status"),
            "conclusion": t.get("conclusion"),
            "missing_documents": t.get("missing_documents"),
        }
        for t in merged
    ]
    return load_prompt("agent_final") + "\n\n--- TRANSACTION RESULTS ---\n" + json.dumps(
        compact, ensure_ascii=False, default=str, indent=2
    )


# ── phases ────────────────────────────────────────────────────────────────────


def _build_chain(case_id: str, docs: list[dict]) -> dict | None:
    ctx = ToolContext(case_id, docs)
    run_tool_loop(
        ctx=ctx, phase="chain", system=load_prompt("agent_system"),
        instruction=_chain_instruction(docs), max_steps=_CHAIN_MAX_STEPS,
    )
    return ctx.saved_chain or repo.get_title_chain(case_id)


def _build_phase_a(case_id: str, docs: list[dict]) -> dict:
    ctx = ToolContext(case_id, docs)
    try:
        run_tool_loop(
            ctx=ctx,
            phase="phase_a",
            system=load_prompt("title_chain_system"),
            instruction=_phase_a_instruction(docs),
            max_steps=_PHASE_A_MAX_STEPS,
        )
    except AgentLLMError:
        # A provider failure after the result was durably saved must not turn a
        # completed Phase A into an apparent failure.
        if not ctx.saved_phase_a_result:
            raise
        logger.warning("Phase A saved for %s but final model turn failed", case_id)
    if not ctx.saved_phase_a_result:
        raise AgentLLMError("Phase A ended without saving the property identity and title-chain result")
    return ctx.saved_phase_a_result


def _verify_transaction(case_id: str, docs: list[dict], chain: dict, tx_id: str) -> ToolContext:
    ctx = ToolContext(case_id, docs, chain=chain, current_tx_id=tx_id)
    tx = _find_tx(chain, tx_id) or {"tx_id": tx_id}
    try:
        run_tool_loop(
            ctx=ctx, phase="verify", system=load_prompt("agent_system"),
            instruction=_verify_instruction(tx), max_steps=_VERIFY_MAX_STEPS,
        )
    except AgentLLMError as e:
        logger.warning("verification pass failed for %s tx %s: %s", case_id, tx_id, e)
    return ctx


def _build_final(case_id: str, docs: list[dict], chain: dict) -> dict:
    merged = _merged_transactions(chain, repo.list_transaction_results(case_id))
    ctx = ToolContext(case_id, docs, chain=chain)
    try:
        run_tool_loop(
            ctx=ctx, phase="final", system=load_prompt("agent_system"),
            instruction=_final_instruction(merged), max_steps=_FINAL_MAX_STEPS,
        )
    except AgentLLMError as e:
        logger.warning("final report pass failed for %s: %s", case_id, e)
    report = ctx.saved_report or {}
    return {
        "case_id": case_id,
        "schema_version": SCHEMA_VERSION,
        "property_identity": chain.get("property_identity") or {},
        "title_chain": {
            "transactions": chain.get("transactions") or [],
            "title_story": chain.get("title_story") or "",
            "unresolved": chain.get("unresolved") or [],
        },
        "transactions": merged,
        "overall_status": normalize_status(report.get("overall_status")),
        "headline": report.get("headline") or "",
        "report": report.get("report") or "",
        "findings": report.get("findings") or [],
        "recommendation": report.get("recommendation") or "",
        "missing_documents": _collect_missing(merged),
        "updated_at": _now(),
    }


# ── run loop ──────────────────────────────────────────────────────────────────


def run_agent(case_id: str) -> dict:
    """Build and persist Phase A: property identity and title-chain graph."""
    lock = None
    if PIPELINE_LOCK_ENABLED:
        try:
            lock = RedisLock(f"case:{case_id}:agent_lock")
            if not lock.acquire():
                logger.info("agent already running for case %s", case_id)
                return {"case_id": case_id, "status": "busy"}
        except Exception as e:  # degrade to no-lock rather than fail
            logger.warning("agent lock unavailable for %s: %s", case_id, e)
            lock = None
    try:
        return _run_phase_a(case_id)
    finally:
        if lock is not None:
            lock.release()


def _run_phase_a(case_id: str) -> dict:
    """Run Phase A only; later verification phases are intentionally not invoked."""
    docs = repo.get_agent_documents(case_id)
    if not docs:
        repo.set_agent_status(case_id=case_id, status=STATUS_ERROR)
        return {"case_id": case_id, "status": STATUS_ERROR, "reason": "no documents"}

    memory = repo.get_agent_memory(case_id) or {}
    try:
        repo.set_agent_status(case_id=case_id, status=STATUS_RUNNING)
        memory.update({"stage": "phase_a", "error": None})
        _save_state(case_id, memory, STATUS_RUNNING)
        result = _build_phase_a(case_id, docs)
        memory.update({"stage": "phase_a_complete", "updated_at": _now()})
        _save_state(case_id, memory, STATUS_DONE)
        logger.info("Phase A title chain saved for case %s", case_id)
        return {"case_id": case_id, "status": STATUS_DONE, "result": result}
    except Exception as e:
        logger.exception("Phase A failed for %s: %s", case_id, e)
        memory.update({"stage": "phase_a_error", "error": str(e)})
        _save_state(case_id, memory, STATUS_ERROR)
        return {"case_id": case_id, "status": STATUS_ERROR, "error": str(e)}


def _run(case_id: str) -> dict:
    docs = repo.get_agent_documents(case_id)
    if not docs:
        repo.set_agent_status(case_id=case_id, status=STATUS_ERROR)
        _sync_case_verdict(case_id, "error", "N/A")
        return {"case_id": case_id, "status": "error", "reason": "no documents"}

    memory = repo.get_agent_memory(case_id) or {}
    try:
        repo.set_agent_status(case_id=case_id, status=STATUS_RUNNING)
        ensure_summaries(case_id, docs)

        chain = repo.get_title_chain(case_id)
        if not chain or not chain.get("transactions"):
            memory["stage"] = "title_chain"
            _save_state(case_id, memory, STATUS_RUNNING)
            chain = _build_chain(case_id, docs)
            if not chain or not chain.get("transactions"):
                raise AgentLLMError("title chain construction produced no transactions")

        _sync_todos(case_id, chain)
        skipped = set(memory.get("skipped_tx_ids") or [])

        memory["stage"] = "verifying"
        _save_state(case_id, memory, STATUS_RUNNING)

        for todo in repo.list_todos(case_id):
            if todo["state"] == TodoState.COMPLETED.value or todo["tx_id"] in skipped:
                continue
            ctx = _verify_transaction(case_id, docs, chain, todo["tx_id"])

            if ctx.missing_requests:
                missing = _collect_missing(_merged_transactions(chain, repo.list_transaction_results(case_id)))
                memory["stage"] = "paused"
                memory["paused_transaction"] = todo["tx_id"]
                memory["missing_documents"] = missing
                memory["next_action"] = (
                    f"Provide the missing document(s) for {todo['tx_id']}, then resume; or skip."
                )
                _save_state(case_id, memory, STATUS_PAUSED)
                _sync_case_verdict(case_id, "paused", "PENDING_NOT_VERIFIED")
                logger.info("agent paused for %s at %s", case_id, todo["tx_id"])
                return {"case_id": case_id, "status": STATUS_PAUSED, "paused_transaction": todo["tx_id"],
                        "missing_documents": missing}

            memory["current_tx_id"] = todo["tx_id"]
            _save_state(case_id, memory, STATUS_RUNNING)

        memory["stage"] = "done"
        memory["paused_transaction"] = None
        result = _build_final(case_id, docs, chain)
        repo.save_agent_result(case_id=case_id, result=result)
        memory["missing_documents"] = result["missing_documents"]
        _save_state(case_id, memory, STATUS_DONE)
        _sync_case_verdict(case_id, "complete", result["overall_status"])
        logger.info("agent completed for %s: %s", case_id, result["overall_status"])
        return {"case_id": case_id, "status": STATUS_DONE, "overall_status": result["overall_status"]}

    except Exception as e:  # record failure, don't crash the worker
        logger.exception("agent failed for %s: %s", case_id, e)
        memory["stage"] = "error"
        memory["error"] = str(e)
        _save_state(case_id, memory, STATUS_ERROR)
        _sync_case_verdict(case_id, "error", "N/A")
        return {"case_id": case_id, "status": STATUS_ERROR, "error": str(e)}


# ── helpers ───────────────────────────────────────────────────────────────────


def _find_tx(chain: dict, tx_id: str) -> dict | None:
    return next((t for t in (chain or {}).get("transactions") or [] if t.get("tx_id") == tx_id), None)


def _sync_todos(case_id: str, chain: dict) -> None:
    existing = {t["tx_id"] for t in repo.list_todos(case_id)}
    for tx in chain.get("transactions") or []:
        tx_id = tx.get("tx_id")
        if tx_id and tx_id not in existing:
            repo.upsert_todo(
                case_id=case_id, tx_id=tx_id, tx_index=tx.get("sequence") or 0,
                description=f"Verify transaction {tx_id} ({tx.get('transaction_type') or 'OTHER'})",
            )


def _merged_transactions(chain: dict, findings: list[dict]) -> list[dict]:
    by_id = {f.get("tx_id"): f for f in findings or []}
    merged = []
    for tx in chain.get("transactions") or []:
        v = by_id.get(tx.get("tx_id")) or {}
        item = dict(tx)
        item["status"] = normalize_status(v.get("status") or "PENDING")
        item["conclusion"] = v.get("conclusion") or ""
        item["reasoning"] = v.get("reasoning") or ""
        item["findings"] = v.get("findings") or []
        item["supporting_evidence"] = v.get("supporting_evidence") or []
        item["contradictory_evidence"] = v.get("contradictory_evidence") or []
        item["missing_documents"] = v.get("missing_documents") or []
        item["unresolved"] = v.get("unresolved") or []
        item["limitations"] = v.get("limitations") or []
        item["rule_versions"] = v.get("rule_versions") or []
        item["verified_at"] = v.get("verified_at") or ""
        merged.append(item)
    return merged


def _collect_missing(transactions: list[dict]) -> list[dict]:
    out = []
    for t in transactions:
        for m in t.get("missing_documents") or []:
            if not isinstance(m, dict):
                continue
            out.append({
                "document_type": m.get("document_type") or m.get("type") or "Document",
                "reason": m.get("reason") or "",
                "for_transaction": t.get("tx_id") or m.get("for_transaction") or "",
            })
    return out


def _save_state(case_id: str, memory: dict, status: str) -> None:
    try:
        repo.save_agent_memory(case_id=case_id, memory=memory)
        repo.set_agent_status(case_id=case_id, status=status)
    except Exception as e:  # state save failure must not kill the run
        logger.warning("failed to save agent state for %s: %s", case_id, e)


def _verdict_for(overall: str) -> str:
    o = (overall or "").upper()
    if o == "VERIFIED_WITH_AVAILABLE_EVIDENCE":
        return "CLEAR_TITLE"
    if o in ("PENDING", "", "N/A", "IN_PROGRESS"):
        return "N/A"
    return "ATTENTION_REQUIRED"


def _sync_case_verdict(case_id: str, verification_status: str, overall: str) -> None:
    try:
        set_case_verification_status(
            case_id=case_id, verification_status=verification_status, verdict=_verdict_for(overall)
        )
    except Exception as e:  # status mirror must not kill the run
        logger.warning("failed to sync case verdict for %s: %s", case_id, e)


# ── user actions ──────────────────────────────────────────────────────────────


def _resolve_tx_ref(chain: dict, ref) -> str | None:
    txs = (chain or {}).get("transactions") or []
    if isinstance(ref, str) and ref.upper().startswith("T"):
        return ref if any(t.get("tx_id") == ref for t in txs) else None
    try:
        seq = int(ref)
    except (TypeError, ValueError):
        return None
    for t in txs:
        if t.get("sequence") == seq or t.get("index") == seq:
            return t.get("tx_id")
    return None


def skip_transaction(case_id: str, tx_ref) -> dict:
    """Record a transaction as skipped (verification incomplete) and continue."""
    chain = repo.get_title_chain(case_id) or {}
    tx_id = _resolve_tx_ref(chain, tx_ref)
    if not tx_id:
        return {"case_id": case_id, "status": "error", "reason": f"transaction {tx_ref} not found"}

    repo.save_transaction_result(case_id=case_id, tx_id=tx_id, verification={
        "tx_id": tx_id,
        "status": normalize_status("PENDING_NOT_VERIFIED"),
        "conclusion": "Skipped by user — verification incomplete.",
        "reasoning": "",
        "findings": [],
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "missing_documents": [],
        "unresolved": [],
        "limitations": ["Not investigated — skipped by the user."],
        "rule_versions": [],
        "verified_at": "",
        "schema_version": SCHEMA_VERSION,
    })
    # TODO stays PENDING (skipped != completed) but is excluded from this and
    # subsequent runs unless new evidence arrives.
    memory = repo.get_agent_memory(case_id) or {}
    skipped = list(memory.get("skipped_tx_ids") or [])
    if tx_id not in skipped:
        skipped.append(tx_id)
    memory["skipped_tx_ids"] = skipped
    if memory.get("paused_transaction") == tx_id:
        memory["paused_transaction"] = None
    repo.save_agent_memory(case_id=case_id, memory=memory)
    return _run(case_id)
