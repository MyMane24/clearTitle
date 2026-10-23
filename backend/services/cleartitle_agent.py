"""The ClearTitle verification agent — one primary tool-calling LLM agent.

The agent builds or reuses the saved Phase A title chain, then verifies each
transaction directly using the verification prompt, skill, and uploaded
documents. Findings and case memory are the durable verification/resume state.

The LLM interprets documents and decides outcomes; this module only orchestrates
(phases, locking, resume) and persists through the repositories. It never decides
a transaction's legal status itself.

Completed transactions are skipped on resume; a transaction paused for missing
evidence is retried when the case is resumed after an upload.
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
from backend.services.agent_runtime import run_tool_loop
from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    normalize_status,
)
from backend.services.agent_tools import ToolContext, _now

logger = get_logger(__name__)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_ERROR = "error"

_VERIFY_MAX_STEPS = 12
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


def verification_skill_path():
    """Resolve the transaction-verification strategy skill."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "skills" / "transaction_verification" / "skill.md"


def repo_skill_path():
    """Resolve the mandatory skill file from the backend package tree."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "skills" / "title_chain" / "skill.md"


def _verify_instruction(tx: dict) -> str:
    return (
        load_prompt("agent_verify_task")
        + "\n\nMANDATORY TRANSACTION-VERIFICATION SKILL\n\n"
        + verification_skill_path().read_text(encoding="utf-8")
        + "\n\n--- TRANSACTION UNDER INVESTIGATION ---\n"
        + json.dumps(tx, ensure_ascii=False, default=str, indent=2)
    )


# ── phases ────────────────────────────────────────────────────────────────────


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


def _phase_a_transactions(phase_a: dict) -> list[dict]:
    transactions = []
    for position, entry in enumerate(phase_a.get("title_chain") or [], start=1):
        transaction = dict(entry.get("documented_transaction") or {})
        transaction_type = str(transaction.get("transaction_type") or "").casefold()
        if any(term in transaction_type for term in ("succession", "inheritance", "death")):
            transaction["executed_date"] = None
        transaction.update({
            # Preserve identifiers already assigned by a saved legacy title chain.
            # Newly reconstructed chains receive the current stable ID format.
            "tx_id": entry.get("tx_id") or transaction.get("tx_id") or f"PA-TC-{position:04d}",
            "sequence": position,
            "is_current_owner_transaction": position == len(phase_a.get("title_chain") or []),
            "related_events": entry.get("related_events") or [],
            "chain_position": entry.get("chain_position") or position,
        })
        transactions.append(transaction)
    return transactions


def _verify_transaction(
    case_id: str, docs: list[dict], phase_a: dict, transaction: dict,
) -> ToolContext:
    tx_id = transaction["tx_id"]
    ctx = ToolContext(
        case_id, docs, current_tx_id=tx_id,
        phase_a_chain=phase_a.get("title_chain") or [],
    )
    try:
        run_tool_loop(
            ctx=ctx, phase="verify", system=load_prompt("agent_system"),
            instruction=_verify_instruction(transaction), max_steps=_VERIFY_MAX_STEPS,
        )
    except AgentLLMError as e:
        logger.warning("verification pass failed for %s tx %s: %s", case_id, tx_id, e)
    return ctx


# ── run loop ──────────────────────────────────────────────────────────────────


def run_agent(case_id: str) -> dict:
    """Build Phase A when absent, then verify its transactions directly."""
    return _run_with_lock(case_id)


def _run_with_lock(
    case_id: str,
    skip_tx_ids: set[str] | None = None,
    skip_ref=None,
) -> dict:
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
        if skip_ref is not None:
            return _skip_transaction_locked(case_id, skip_ref)
        memory = repo.get_agent_memory(case_id) or {}
        if memory.get("skipped_tx_ids"):
            memory["skipped_tx_ids"] = []
            repo.save_agent_memory(case_id=case_id, memory=memory)
        return _run(case_id, skip_tx_ids=skip_tx_ids or set())
    finally:
        if lock is not None:
            lock.release()


def _run(case_id: str, skip_tx_ids: set[str] | None = None) -> dict:
    docs = repo.get_agent_documents(case_id)
    if not docs:
        repo.set_agent_status(case_id=case_id, status=STATUS_ERROR)
        _sync_case_verdict(case_id, "error", "N/A")
        return {"case_id": case_id, "status": "error", "reason": "no documents"}

    memory = repo.get_agent_memory(case_id) or {}
    try:
        repo.set_agent_status(case_id=case_id, status=STATUS_RUNNING)
        phase_a = repo.get_agent_result(case_id)
        if not phase_a or not phase_a.get("title_chain"):
            # Phase A uses summaries for navigation. This is deliberately not
            # run on every verification resume, where each transaction chooses
            # evidence requirements before inspecting summaries.
            ensure_summaries(case_id, docs)
            memory["stage"] = "phase_a"
            _save_state(case_id, memory, STATUS_RUNNING)
            phase_a = _build_phase_a(case_id, docs)
        transactions = _phase_a_transactions(phase_a)
        if not transactions:
            raise AgentLLMError("saved Phase A result contains no transactions")
        skipped_this_run = skip_tx_ids or set()

        memory["stage"] = "verifying"
        memory["status"] = "IN_PROGRESS"
        _save_state(case_id, memory, STATUS_RUNNING)

        terminal = {"VERIFIED_WITH_AVAILABLE_EVIDENCE", "ISSUES_IDENTIFIED", "INCONCLUSIVE"}
        for transaction in transactions:
            tx_id = transaction["tx_id"]
            if tx_id in skipped_this_run:
                continue
            previous = repo.get_transaction_result(case_id, tx_id) or {}
            if normalize_status(previous.get("status")) in terminal:
                continue

            memory["current_tx_id"] = tx_id
            memory["stage"] = "verifying_transaction"
            memory["status"] = "IN_PROGRESS"
            _save_state(case_id, memory, STATUS_RUNNING)
            ctx = _verify_transaction(case_id, docs, phase_a, transaction)
            result_error = getattr(ctx, "result_error", None)
            if result_error:
                raise AgentLLMError(f"transaction result was rejected or not persisted: {result_error}")
            if not getattr(ctx, "saved_results", []) and not ctx.missing_requests:
                raise AgentLLMError(f"verification ended without a persisted result for {tx_id}")

            saved = repo.get_transaction_result(case_id, tx_id) or {}
            if ctx.missing_requests or normalize_status(saved.get("status")) == "PENDING_NOT_VERIFIED":
                missing = _collect_missing([{
                    "tx_id": tx_id,
                    "required_documents": saved.get("required_documents")
                    or (ctx.missing_requests[-1].get("documents") if ctx.missing_requests else [])
                    or [],
                }])
                memory["stage"] = "paused"
                memory["paused_transaction"] = tx_id
                memory["current_tx_id"] = tx_id
                memory["result_ref"] = tx_id
                memory["status"] = "PENDING_NOT_VERIFIED"
                memory["missing_documents"] = missing
                memory["last_transaction_id"] = tx_id
                memory["last_transaction_status"] = "PENDING_NOT_VERIFIED"
                memory["last_transaction_summary"] = "Pending — required evidence was not provided; verification is not complete."
                memory["pending_tx_ids"] = sorted(set(memory.get("pending_tx_ids") or []) | {tx_id})
                memory["next_action"] = (
                    f"Upload the requested document(s) for {tx_id} to retry, or skip this transaction."
                )
                _save_state(case_id, memory, STATUS_PAUSED)
                _sync_case_verdict(case_id, "paused", "PENDING_NOT_VERIFIED")
                logger.info("agent paused for %s at %s", case_id, tx_id)
                return {"case_id": case_id, "status": STATUS_PAUSED, "paused_transaction": tx_id,
                        "missing_documents": missing}

            memory["result_ref"] = tx_id
            memory["status"] = saved.get("status") or "PENDING_NOT_VERIFIED"
            memory["last_transaction_id"] = tx_id
            memory["last_transaction_status"] = saved.get("status") or "PENDING_NOT_VERIFIED"
            points = [item.get("description") for item in (saved.get("findings") or []) if isinstance(item, dict) and item.get("description")]
            memory["last_transaction_summary"] = "; ".join(points[:3]) or saved.get("conclusion") or "No verification points were recorded."
            memory["last_evidence_requirements"] = saved.get("evidence_requirements") or getattr(ctx, "evidence_requirements", [])
            memory["last_reviewed_document_ids"] = saved.get("reviewed_document_ids") or sorted(getattr(ctx, "selected_document_ids", set()))
            memory["completed_tx_ids"] = [
                item["tx_id"] for item in repo.list_transaction_results(case_id)
                if normalize_status(item.get("status")) in terminal
            ]
            memory["pending_tx_ids"] = [
                item["tx_id"] for item in repo.list_transaction_results(case_id)
                if normalize_status(item.get("status")) == "PENDING_NOT_VERIFIED"
            ]
            memory["current_tx_id"] = None
            _save_state(case_id, memory, STATUS_RUNNING)

        memory["stage"] = "done"
        memory["paused_transaction"] = None
        memory["current_tx_id"] = None
        all_findings = repo.list_transaction_results(case_id)
        memory["completed_tx_ids"] = [
            item["tx_id"] for item in all_findings
            if normalize_status(item.get("status")) in terminal
        ]
        memory["pending_tx_ids"] = [
            item["tx_id"] for item in all_findings
            if normalize_status(item.get("status")) == "PENDING_NOT_VERIFIED"
        ]
        overall_status = _overall_transaction_status(all_findings)
        memory["missing_documents"] = _collect_missing(all_findings)
        _save_state(case_id, memory, STATUS_DONE)
        _sync_case_verdict(case_id, "complete", overall_status)
        logger.info("agent completed for %s: %s", case_id, overall_status)
        return {"case_id": case_id, "status": STATUS_DONE, "overall_status": overall_status}

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


def _collect_missing(transactions: list[dict]) -> list[dict]:
    out = []
    for t in transactions:
        for m in (t.get("required_documents") or t.get("missing_documents") or []):
            if not isinstance(m, dict):
                continue
            out.append({
                "document_type": m.get("document_type") or m.get("type") or "Document",
                "reason": m.get("reason") or "",
                "for_transaction": t.get("tx_id") or m.get("for_transaction") or "",
            })
    return out


def _overall_transaction_status(transactions: list[dict]) -> str:
    statuses = {normalize_status(item.get("status")) for item in transactions}
    if "ISSUES_IDENTIFIED" in statuses:
        return "ISSUES_IDENTIFIED"
    if not statuses or statuses - {"VERIFIED_WITH_AVAILABLE_EVIDENCE"}:
        return "INCONCLUSIVE"
    return "VERIFIED_WITH_AVAILABLE_EVIDENCE"


def _save_state(case_id: str, memory: dict, status: str) -> None:
    memory["updated_at"] = _now()
    memory["current_stage"] = memory.get("stage") or status
    repo.save_agent_memory(case_id=case_id, memory=memory)
    repo.set_agent_status(case_id=case_id, status=status)


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
    if isinstance(ref, str):
        matched = next((t.get("tx_id") for t in txs if t.get("tx_id") == ref), None)
        if matched:
            return matched
    try:
        seq = int(ref)
    except (TypeError, ValueError):
        return None
    for t in txs:
        if t.get("sequence") == seq or t.get("index") == seq:
            return t.get("tx_id")
    return None


def skip_transaction(case_id: str, tx_ref) -> dict:
    """Record a paused transaction as skipped and continue under the case lock."""
    return _run_with_lock(case_id, skip_ref=tx_ref)


def _skip_transaction_locked(case_id: str, tx_ref) -> dict:
    phase_a = repo.get_agent_result(case_id) or {}
    chain = {"transactions": _phase_a_transactions(phase_a)}
    tx_id = _resolve_tx_ref(chain, tx_ref)
    if not tx_id:
        return {"case_id": case_id, "status": "error", "reason": f"transaction {tx_ref} not found"}
    memory = repo.get_agent_memory(case_id) or {}
    paused_tx_id = memory.get("paused_transaction") or (
        memory.get("current_tx_id")
        if memory.get("current_stage") == "paused" and memory.get("status") == "PENDING_NOT_VERIFIED"
        else None
    )
    if paused_tx_id != tx_id:
        return {"case_id": case_id, "status": "error", "reason": "only the currently paused transaction can be skipped"}

    previous = repo.get_transaction_result(case_id, tx_id) or {}
    skipped_ids = set(memory.get("skipped_tx_ids") or [])
    skipped_ids.add(tx_id)
    tx = next(item for item in chain["transactions"] if item["tx_id"] == tx_id)
    # Skipping is workflow state only. Never rewrite the verification result (or
    # its evidence/requirements) to record the user's navigation choice.
    if previous and normalize_status(previous.get("status")) != "PENDING_NOT_VERIFIED":
        return {"case_id": case_id, "status": "error", "reason": "only a pending transaction can be skipped"}
    memory["skipped_tx_ids"] = sorted(skipped_ids)
    memory["pending_tx_ids"] = sorted(set(memory.get("pending_tx_ids") or []) | {tx_id})
    memory["last_transaction_id"] = tx_id
    memory["last_transaction_status"] = "PENDING_NOT_VERIFIED"
    memory["last_transaction_summary"] = "Not verified — the user skipped evidence upload; requested documents remain required."
    memory["current_tx_id"] = tx_id
    memory["result_ref"] = tx_id
    memory["current_stage"] = "SKIPPED"
    memory["status"] = "PENDING_NOT_VERIFIED"
    memory["stage"] = "skipped"
    memory["next_action"] = None
    repo.save_agent_memory(case_id=case_id, memory=memory)
    return _run(case_id, skip_tx_ids=skipped_ids)
