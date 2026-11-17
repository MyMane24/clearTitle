"""Builds the Pydantic AI model for the configured provider.

Switching the backing model stays a two-env-var change:

    CLEARTITLE_AGENT_PROVIDER=openai|luna|gemini
    CLEARTITLE_AGENT_MODEL=<model-name>
"""

from __future__ import annotations

import os

from pydantic_ai.models import Model

from backend.config import (
    CLEARTITLE_AGENT_MODEL,
    CLEARTITLE_AGENT_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_API_VERSION,
)
from backend.integrations.llm.agent_llm import AgentLLMError

_MAX_OUTPUT_TOKENS = 32000

# Pydantic AI prints a promotional banner on a process's first agent run; keep
# it out of the worker log.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def build_agent_model() -> Model:
    """Return the agent model for ``CLEARTITLE_AGENT_PROVIDER``.

    Raises:
        AgentLLMError: The provider is unknown or its API key is not set.
    """
    provider = (CLEARTITLE_AGENT_PROVIDER or "openai").lower()
    if provider in {"openai", "luna"}:
        return _openai_model()
    if provider == "gemini":
        return _gemini_model()
    raise AgentLLMError(f"unknown agent provider {provider!r}")


def _openai_model() -> Model:
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
    from pydantic_ai.providers.openai import OpenAIProvider

    if not OPENAI_API_KEY:
        raise AgentLLMError("OPENAI_API_KEY not set")
    client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE or None,
        default_query={"api-version": OPENAI_API_VERSION} if OPENAI_API_BASE else None,
    )
    return OpenAIChatModel(
        CLEARTITLE_AGENT_MODEL,
        provider=OpenAIProvider(openai_client=client),
        # Chat Completions supports tool calls on this model family only
        # with reasoning switched off.
        settings=OpenAIChatModelSettings(
            max_tokens=_MAX_OUTPUT_TOKENS, openai_reasoning_effort="none"
        ),
    )


def _gemini_model() -> Model:
    from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
    from pydantic_ai.providers.google import GoogleProvider

    if not GEMINI_API_KEY:
        raise AgentLLMError("GEMINI_API_KEY not set")
    return GoogleModel(
        CLEARTITLE_AGENT_MODEL,
        provider=GoogleProvider(api_key=GEMINI_API_KEY),
        settings=GoogleModelSettings(temperature=0.0, max_tokens=_MAX_OUTPUT_TOKENS),
    )
