"""Provider-agnostic LLM access for single-shot JSON calls.

Used for document summaries and other one-call structured replies.

The workflow never imports a vendor SDK. Switching the backing model
(Gemini in development → GPT-6 Luna in production) is a two-env-var change:

    CLEARTITLE_AGENT_PROVIDER=gemini|openai|luna
    CLEARTITLE_AGENT_MODEL=<model-name>
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable

from backend.config import (
    CLEARTITLE_AGENT_MAX_ATTEMPTS,
    CLEARTITLE_AGENT_MODEL,
    CLEARTITLE_AGENT_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_API_VERSION,
)
from backend.logger import get_logger

logger = get_logger(__name__)

_MAX_ATTEMPTS = CLEARTITLE_AGENT_MAX_ATTEMPTS


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
        except Exception as e:
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
                extra_body={"reasoning_effort": "none"},
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


# -- provider registry ---------------------------------------------------------

_JSON_PROVIDERS: dict[str, Callable] = {
    "gemini": _gemini_complete_json,
    "openai": _openai_complete_json,
    "luna": _openai_complete_json,
}


def complete_json(
    prompt: str, *, schema: dict | None = None, system: str | None = None, task: str = "agent"
) -> dict:
    provider = (CLEARTITLE_AGENT_PROVIDER or "gemini").lower()
    fn = _JSON_PROVIDERS.get(provider)
    if fn is None:
        raise AgentLLMError(f"unknown agent provider {provider!r}")
    return fn(prompt, model=CLEARTITLE_AGENT_MODEL, schema=schema, system=system, task=task)
