"""Generic tool-calling loop for the ClearTitle agent.

One turn = ask the model, execute any tool calls it makes, feed the results back,
repeat until the model stops calling tools (or ``finish`` is called, or the step
budget is exhausted). The model decides *what* to investigate; the tool handlers
own *how* state is persisted.
"""

from __future__ import annotations

import json
from time import perf_counter

from backend.config import (
    CLEARTITLE_AGENT_MODEL,
    CLEARTITLE_AGENT_PROVIDER,
    CLEARTITLE_KEEP_OCR_RESULTS,
    CLEARTITLE_MAX_NUDGES,
)
from backend.integrations.llm.agent_llm import complete_with_tools
from backend.logger import get_logger
from backend.services.agent_tools import ToolContext, dispatch, tools_for

logger = get_logger(__name__)


_RECOVERABLE_EVIDENCE_ERRORS = (
    "whose complete ocr was not reviewed",
    "must be read for every selected supporting document",
)


def _grant_recovery_budget(ctx: ToolContext, phase: str, tool_name: str, result: object) -> None:
    """Reserve one bounded continuation for evidence-validation recovery."""
    if phase != "verify" or tool_name not in {"save_transaction_result", "request_missing_documents"}:
        return
    if ctx.additional_model_calls_used or not isinstance(result, dict) or not result.get("error"):
        return
    error_text = str(result["error"]).casefold()
    if not any(marker in error_text for marker in _RECOVERABLE_EVIDENCE_ERRORS):
        return
    ctx.additional_model_calls_used = True
    ctx.additional_model_calls = 8
    logger.warning(
        "agent_validation_recovery_budget_granted run_id=%s tx_id=%s extra_calls=8 reason=%s",
        ctx.run_id, ctx.current_tx_id, error_text[:240],
    )


_FINAL_CALL_TOOLS = {"save_transaction_result", "request_missing_documents"}

_NUDGE = (
    "You ended your turn without calling a tool, so nothing was saved. Continue the "
    "verification with a tool call: finish any remaining evidence check, then call "
    "save_transaction_result (or request_missing_documents when essential evidence is "
    "outstanding). Do not reply with prose only."
)


def _context_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def _prune_stale_ocr(ctx: ToolContext, messages: list[dict]) -> int:
    """Replace old OCR tool results with a stub, keeping the newest few verbatim.

    A coding agent does not re-send every file it ever opened; likewise a chunk
    of OCR is dropped from the history once the model has recorded observations
    for that document (``record_observation``). Chunks of documents without any
    recorded observation are never pruned, so nothing unnoted is lost. The range
    stays readable: pruned ranges are exempt from the overlap rule.
    """
    ocr_positions = [
        index for index, message in enumerate(messages)
        if message.get("role") == "tool" and message.get("name") == "get_document_text"
        and '"text"' in str(message.get("content") or "")
    ]
    pruned = 0
    for index in ocr_positions[:-CLEARTITLE_KEEP_OCR_RESULTS]:
        message = messages[index]
        try:
            payload = json.loads(message["content"])
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        doc_id = str(payload.get("doc_id") or "")
        if not any(o.get("doc_id") == doc_id for o in ctx.observations):
            continue
        start = int(payload.get("start_char") or 0)
        end = start + len(str(payload.get("text") or ""))
        ctx.pruned_ranges.setdefault(doc_id, set()).add((start, end))
        message["content"] = json.dumps({
            "doc_id": doc_id, "start_char": start, "end_char": end,
            "total_chars": payload.get("total_chars"), "has_more": payload.get("has_more"),
            "next_start_char": payload.get("next_start_char"),
            "pruned": True,
            "note": "OCR text cleared from the session after review; your record_observation "
                    "notes hold what mattered. Re-read this range with get_document_text if exact wording is needed.",
        })
        pruned += 1
    return pruned


def run_tool_loop(
    *,
    ctx: ToolContext,
    phase: str,
    system: str,
    instruction: str,
    max_steps: int = 12,
) -> ToolContext:
    tools = tools_for(phase)
    messages: list[dict] = [{"role": "user", "content": instruction}]
    model_calls = 0
    ctx.model_call_count = 0
    ctx.stop_reason = "model_stopped_without_result"

    step = 0
    nudges = 0
    final_call_announced = False
    while step < max_steps:
        if ctx.finished:
            break
        step += 1
        model_calls += 1
        ctx.model_call_count = model_calls
        started = perf_counter()
        task_trace = f"{phase}:run={ctx.run_id}:tx={ctx.current_tx_id or '-'}"
        call_tools = tools
        if phase == "verify" and step == max_steps and max_steps >= 4:
            # Last call of the budget: only a decision can still be recorded.
            call_tools = [t for t in tools if t["name"] in _FINAL_CALL_TOOLS] or tools
            if not final_call_announced:
                final_call_announced = True
                messages.append({"role": "user", "content": (
                    "FINAL CALL OF THE VERIFICATION BUDGET. Record your decision now: "
                    "save_transaction_result with the evidence reviewed so far, or "
                    "request_missing_documents if essential evidence is outstanding."
                )})
        resp = complete_with_tools(messages, tools=call_tools, system=system, task=task_trace)
        logger.info(
            "agent_model_call run_id=%s tx_id=%s phase=%s provider=%s model=%s call=%s budget=%s attempts=%s latency_ms=%s context_chars=%s usage=%s",
            ctx.run_id, ctx.current_tx_id, phase, CLEARTITLE_AGENT_PROVIDER,
            CLEARTITLE_AGENT_MODEL, model_calls, max_steps, resp.get("attempts", 1),
            round((perf_counter() - started) * 1000), _context_chars(messages), resp.get("usage"),
        )
        calls = resp.get("tool_calls") or []
        if not calls:
            if phase == "verify" and not ctx.finished and nudges < CLEARTITLE_MAX_NUDGES and step < max_steps:
                nudges += 1
                logger.warning(
                    "agent_turn_without_tool run_id=%s tx_id=%s nudge=%s/%s",
                    ctx.run_id, ctx.current_tx_id, nudges, CLEARTITLE_MAX_NUDGES,
                )
                messages.append({"role": "assistant", "content": resp.get("content") or "(no action)"})
                messages.append({"role": "user", "content": _NUDGE})
                continue
            break

        messages.append({"role": "assistant", "content": resp.get("content"), "tool_calls": calls})
        for call in calls:
            if ctx.finished:
                break
            repeated_before = ctx.repeated_tool_calls
            result = dispatch(ctx, call["name"], call.get("args") or {})
            _grant_recovery_budget(ctx, phase, call["name"], result)
            if ctx.repeated_tool_calls > repeated_before and isinstance(result, dict):
                # Cached tool output is safe to reuse, but repeating it is not a
                # reason to abort the transaction. Tell the model to move on and
                # let the normal call budget provide the outer bound.
                result = {
                    **result,
                    "duplicate_call": True,
                    "next_step": "This exact action already ran and its result is shown above. Do not repeat it; continue with another evidence check or persist the transaction result.",
                }
            if ctx.additional_model_calls:
                max_steps = min(max_steps + ctx.additional_model_calls, 24)
                ctx.additional_model_calls = 0
            logger.info(
                "agent_tool_call run_id=%s tx_id=%s phase=%s tool=%s count=%s",
                ctx.run_id, ctx.current_tx_id, phase, call["name"],
                ctx.tool_call_counts.get(call["name"], 0),
            )
            if isinstance(result, dict) and result.get("error"):
                issues = result.get("issues")
                diagnostic = "; ".join(str(issue) for issue in issues) if isinstance(issues, list) else str(result["error"])
                logger.warning(
                    "agent_tool_rejected run_id=%s tx_id=%s phase=%s tool=%s diagnostic=%s",
                    ctx.run_id, ctx.current_tx_id, phase, call["name"], diagnostic[:500],
                )
            if phase == "verify" and isinstance(result, dict):
                # Visible budget: the model plans its remaining checks instead of
                # discovering the limit by being cut off.
                result = {**result, "budget": {"calls_remaining": max(max_steps - step, 0)}}
            messages.append({
                "role": "tool",
                "name": call["name"],
                "tool_call_id": call["id"],
                "content": json.dumps(result, default=str),
            })
        if not ctx.finished and phase == "verify":
            _prune_stale_ocr(ctx, messages)
        if ctx.finished:
            ctx.stop_reason = "persisted_result"
            break
    else:
        ctx.stop_reason = "model_call_budget_exhausted"
        logger.warning("tool loop for phase %s hit max_steps=%s", phase, max_steps)

    if ctx.finished and ctx.stop_reason != "persisted_result":
        ctx.stop_reason = "finished"
    logger.info(
        "agent_loop_stop run_id=%s tx_id=%s phase=%s reason=%s model_calls=%s tool_calls=%s repeated_tool_calls=%s",
        ctx.run_id, ctx.current_tx_id, phase, ctx.stop_reason,
        ctx.model_call_count, ctx.tool_call_counts, ctx.repeated_tool_calls,
    )

    return ctx
