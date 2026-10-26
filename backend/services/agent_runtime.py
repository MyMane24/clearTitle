"""Generic tool-calling loop for the ClearTitle agent.

One turn = ask the model, execute any tool calls it makes, feed the results back,
repeat until the model stops calling tools (or ``finish`` is called, or the step
budget is exhausted). The model decides *what* to investigate; the tool handlers
own *how* state is persisted.
"""

from __future__ import annotations

import json
from time import perf_counter

from backend.config import CLEARTITLE_AGENT_MODEL, CLEARTITLE_AGENT_PROVIDER
from backend.integrations.llm.agent_llm import complete_with_tools
from backend.logger import get_logger
from backend.services.agent_tools import ToolContext, dispatch, tools_for

logger = get_logger(__name__)


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
    while step < max_steps:
        if ctx.finished:
            break
        step += 1
        model_calls += 1
        ctx.model_call_count = model_calls
        started = perf_counter()
        task_trace = f"{phase}:run={ctx.run_id}:tx={ctx.current_tx_id or '-'}"
        resp = complete_with_tools(messages, tools=tools, system=system, task=task_trace)
        logger.info(
            "agent_model_call run_id=%s tx_id=%s phase=%s provider=%s model=%s call=%s budget=%s attempts=%s latency_ms=%s usage=%s",
            ctx.run_id, ctx.current_tx_id, phase, CLEARTITLE_AGENT_PROVIDER,
            CLEARTITLE_AGENT_MODEL, model_calls, max_steps, resp.get("attempts", 1),
            round((perf_counter() - started) * 1000), resp.get("usage"),
        )
        calls = resp.get("tool_calls") or []
        if not calls:
            break

        messages.append({"role": "assistant", "content": resp.get("content"), "tool_calls": calls})
        for call in calls:
            if ctx.finished:
                break
            repeated_before = ctx.repeated_tool_calls
            result = dispatch(ctx, call["name"], call.get("args") or {})
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
            messages.append({
                "role": "tool",
                "name": call["name"],
                "tool_call_id": call["id"],
                "content": json.dumps(result, default=str),
            })
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
