"""Generic tool-calling loop for the ClearTitle agent.

One turn = ask the model, execute any tool calls it makes, feed the results back,
repeat until the model stops calling tools (or ``finish`` is called, or the step
budget is exhausted). The model decides *what* to investigate; the tool handlers
own *how* state is persisted.
"""

from __future__ import annotations

import json

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

    for step in range(1, max_steps + 1):
        resp = complete_with_tools(messages, tools=tools, system=system, task=phase)
        calls = resp.get("tool_calls") or []
        if not calls:
            break

        messages.append({"role": "assistant", "content": resp.get("content"), "tool_calls": calls})
        for call in calls:
            result = dispatch(ctx, call["name"], call.get("args") or {})
            messages.append({
                "role": "tool",
                "name": call["name"],
                "tool_call_id": call["id"],
                "content": json.dumps(result, default=str),
            })
        if ctx.finished:
            break
    else:
        logger.warning("tool loop for phase %s hit max_steps=%s", phase, max_steps)

    return ctx
