"""Provider-agnostic LLM access for the ClearTitle agent.

Two entry points:

* ``complete_json``      — single-shot JSON reply (used for document summaries).
* ``complete_with_tools`` — one tool-calling turn of the agent loop.

The workflow never imports a vendor SDK. Switching the backing model
(Gemini in development → GPT-6 Luna in production) is a two-env-var change:

    CLEARTITLE_AGENT_PROVIDER=gemini|openai|luna
    CLEARTITLE_AGENT_MODEL=<model-name>

To add a provider, register one callable in ``_PROVIDERS`` (same kwargs) — or
call ``register_provider`` at runtime (used by tests). Nothing else changes.

Structured-output note: when a ``schema`` is supplied the provider is asked to
honour it; authoritative validation happens in the service layer
(``backend.services.agent_schemas``), not here.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Callable

from backend.config import (
    CLEARTITLE_AGENT_MODEL,
    CLEARTITLE_AGENT_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    OPENAI_API_VERSION,
)
from backend.logger import get_logger

logger = get_logger(__name__)

_MAX_ATTEMPTS = 5


class AgentLLMError(RuntimeError):
    """Raised when the configured provider cannot return a usable response."""


def _extract_json(raw: str) -> dict:
    try:
        data = json.loads(raw, strict=False)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw or "")
        if not m:
            raise RuntimeError("agent LLM returned unparseable JSON")
        data = json.loads(m.group(1), strict=False)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data}
    raise RuntimeError("agent LLM returned non-object JSON")


# ── tool-calling: provider-agnostic turn ──────────────────────────────────────
#
# ``messages`` is a list of dicts:
#   {"role": "user",      "content": str}
#   {"role": "assistant", "content": str|None, "tool_calls": [{"id","name","args"}]}
#   {"role": "tool",      "name": str, "tool_call_id": str, "content": str}
#
# ``tools`` is a list of {"name", "description", "parameters": <json-schema>}.
#
# The return value is {"tool_calls": [...], "content": str|None}.


def _gemini_contents(messages: list[dict]):
    from google.genai import types

    contents = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.get("content") or "")]))
        elif role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append(types.Part(text=msg["content"]))
            for call in msg.get("tool_calls") or []:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=call["name"], args=call.get("args") or {})
                    )
                )
            if not parts:
                parts.append(types.Part(text=""))
            contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=msg.get("name") or "tool",
                            response={"result": msg.get("content") or ""},
                        )
                    ],
                )
            )
    return contents


def _gemini_complete_with_tools(
    messages: list[dict], *, tools: list[dict], model: str, system: str | None, task: str
) -> dict:
    from google import genai
    from google.genai import types

    from backend.integrations.llm.rate_limiter import gemini_limiter

    if not GEMINI_API_KEY:
        raise AgentLLMError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=GEMINI_API_KEY)
    declarations = [
        types.FunctionDeclaration(
            name=t["name"], description=t.get("description", ""), parameters=t.get("parameters") or {}
        )
        for t in tools
    ]
    config = types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=32768,
        system_instruction=system or "You are a careful property title-verification agent.",
        tools=[types.Tool(function_declarations=declarations)] if declarations else None,
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        )
        if declarations
        else None,
    )

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            gemini_limiter.wait_and_acquire(tokens=1)
            response = client.models.generate_content(
                model=model, contents=_gemini_contents(messages), config=config
            )
            calls = []
            for i, fc in enumerate(response.function_calls or []):
                calls.append({"id": f"call_{i}", "name": fc.name, "args": dict(fc.args or {})})
            return {"tool_calls": calls, "content": response.text or None}
        except Exception as e:  # noqa: BLE001 - normalize transient retries
            last_exc = e
            transient = any(
                x in str(e).lower()
                for x in ["503", "429", "quota", "exhausted", "resource_exhausted",
                          "rate", "unavailable", "too many requests"]
            )
            if not transient or attempt == _MAX_ATTEMPTS:
                raise AgentLLMError(f"gemini tool call failed for task {task}: {e}") from e
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))

    raise AgentLLMError(f"gemini call failed for task {task}: {last_exc}")


def _openai_complete_with_tools(
    messages: list[dict], *, tools: list[dict], model: str, system: str | None, task: str
) -> dict:
    """OpenAI-compatible provider for GPT-6 Luna (or any OpenAI-compatible endpoint)."""
    if not OPENAI_API_KEY:
        raise AgentLLMError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE or None,
        default_query={"api-version": OPENAI_API_VERSION} if OPENAI_API_BASE else None,
    )

    openai_messages = []
    if system:
        openai_messages.append({"role": "system", "content": system})
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            openai_messages.append({"role": "user", "content": msg.get("content") or ""})
        elif role == "assistant":
            content = msg.get("content")
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                openai_messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": json.dumps(call.get("args") or {})}
                        }
                        for call in tool_calls
                    ]
                })
            elif content:
                openai_messages.append({"role": "assistant", "content": content})
        elif role == "tool":
            openai_messages.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id"),
                "name": msg.get("name") or "tool",
                "content": msg.get("content") or "",
            })

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}}
            }
        }
        for t in tools
    ]

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=openai_messages,
                tools=openai_tools if openai_tools else None,
                tool_choice="auto" if openai_tools else None,
                max_completion_tokens=32000,
                reasoning_effort="none",
            )
            choice = response.choices[0]
            calls = []
            for i, tc in enumerate(choice.message.tool_calls or []):
                calls.append({
                    "id": tc.id or f"call_{i}",
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments or "{}")
                })
            return {"tool_calls": calls, "content": choice.message.content}
        except Exception as e:
            last_exc = e
            transient = any(
                x in str(e).lower()
                for x in ["429", "rate", "timeout", "503", "502", "504", "quota", "unavailable"]
            )
            if not transient or attempt == _MAX_ATTEMPTS:
                raise AgentLLMError(f"openai tool call failed for task {task}: {e}") from e
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))

    raise AgentLLMError(f"openai call failed for task {task}: {last_exc}")


def _gemini_complete_json(
    prompt: str, *, model: str, schema: dict | None, system: str | None, task: str
) -> dict:
    from google import genai

    from backend.integrations.llm.rate_limiter import gemini_limiter

    if not GEMINI_API_KEY:
        raise AgentLLMError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=GEMINI_API_KEY)
    system_instruction = system or "You are a careful property title-verification agent. Reply with JSON only."
    if schema:
        system_instruction += f"\n\nEXPECTED JSON SHAPE:\n{json.dumps(schema, indent=2)}"

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            gemini_limiter.wait_and_acquire(tokens=1)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                    "max_output_tokens": 32768,
                    "system_instruction": system_instruction,
                },
            )
            return _extract_json(response.text or "")
        except Exception as e:  # noqa: BLE001 - normalize transient retries
            last_exc = e
            transient = any(
                x in str(e).lower()
                for x in ["503", "429", "quota", "exhausted", "resource_exhausted",
                          "rate", "unavailable", "too many requests"]
            )
            if not transient or attempt == _MAX_ATTEMPTS:
                raise AgentLLMError(f"gemini call failed for task {task}: {e}") from e
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))

    raise AgentLLMError(f"gemini call failed for task {task}: {last_exc}")


def _openai_complete_json(
    prompt: str, *, model: str, schema: dict | None, system: str | None, task: str
) -> dict:
    """OpenAI-compatible provider for JSON mode (used for summaries)."""
    if not OPENAI_API_KEY:
        raise AgentLLMError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE or None,
        default_query={"api-version": OPENAI_API_VERSION} if OPENAI_API_BASE else None,
    )

    system_instruction = system or "You are a careful property title-verification agent. Reply with JSON only."
    if schema:
        system_instruction += f"\n\nEXPECTED JSON SHAPE:\n{json.dumps(schema, indent=2)}"

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=32000,
                reasoning_effort="none",
                response_format={"type": "json_object"},
            )
            return _extract_json(response.choices[0].message.content or "")
        except Exception as e:
            last_exc = e
            transient = any(
                x in str(e).lower()
                for x in ["429", "rate", "timeout", "503", "502", "504", "quota", "unavailable"]
            )
            if not transient or attempt == _MAX_ATTEMPTS:
                raise AgentLLMError(f"openai call failed for task {task}: {e}") from e
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))

    raise AgentLLMError(f"openai call failed for task {task}: {last_exc}")


# ── provider registry ─────────────────────────────────────────────────────────

_JSON_PROVIDERS: dict[str, Callable] = {
    "gemini": _gemini_complete_json,
    "openai": _openai_complete_json,
    "luna": _openai_complete_json,
}
_TOOL_PROVIDERS: dict[str, Callable] = {
    "gemini": _gemini_complete_with_tools,
    "openai": _openai_complete_with_tools,
    "luna": _openai_complete_with_tools,
}


def register_provider(
    name: str, *,
    json_call: Callable | None = None,
    tool_call: Callable | None = None,
) -> None:
    """Register/replace a provider at runtime (tests, future vendors)."""
    if json_call is not None:
        _JSON_PROVIDERS[name] = json_call
    if tool_call is not None:
        _TOOL_PROVIDERS[name] = tool_call


def complete_json(
    prompt: str, *, schema: dict | None = None, system: str | None = None, task: str = "agent"
) -> dict:
    provider = (CLEARTITLE_AGENT_PROVIDER or "gemini").lower()
    fn = _JSON_PROVIDERS.get(provider)
    if fn is None:
        raise AgentLLMError(f"unknown agent provider {provider!r}")
    return fn(prompt, model=CLEARTITLE_AGENT_MODEL, schema=schema, system=system, task=task)


def complete_with_tools(
    messages: list[dict], *, tools: list[dict], system: str | None = None, task: str = "agent"
) -> dict:
    """One tool-calling turn. Returns {"tool_calls": [...], "content": str|None}."""
    provider = (CLEARTITLE_AGENT_PROVIDER or "gemini").lower()
    fn = _TOOL_PROVIDERS.get(provider)
    if fn is None:
        raise AgentLLMError(f"unknown agent provider {provider!r}")
    return fn(messages, tools=tools, model=CLEARTITLE_AGENT_MODEL, system=system, task=task)
