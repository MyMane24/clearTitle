"""Generic Gemini analysis executor for case-level passes (title chain + verification)."""

from __future__ import annotations

import json
import re
import time

from google import genai

from backend.config import GEMINI_API_KEY
from backend.integrations.llm.model_router import resolve_analysis_task
from backend.integrations.llm.rate_limiter import LLMCallTracker, gemini_limiter
from backend.logger import get_logger
from backend.prompts.loader import load_prompt

logger = get_logger(__name__)

_ANALYSIS_SYSTEM_TEMPLATE = load_prompt("analysis_system")


def run_analysis(prompt: str, *, task: str, response_schema: dict) -> dict:
    """Run a single JSON-in/JSON-out Gemini call for a case-level analysis task.

    Returns ``{"result": {...}, "analytics": {...}}`` on success.
    Raises RuntimeError when the model returns unparseable JSON.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env")

    provider, model = resolve_analysis_task()
    client = genai.Client(api_key=GEMINI_API_KEY)
    start = time.time()

    try:
        acquired = gemini_limiter.wait_and_acquire(tokens=1)
        if not acquired:
            logger.warning("Rate limit wait timeout for analysis task %s", task)

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.0,
                "max_output_tokens": 32768,
                "system_instruction": (
                    f"{_ANALYSIS_SYSTEM_TEMPLATE}\n\n"
                    f"EXPECTED OUTPUT SHAPE:\n{json.dumps(response_schema, indent=2)}"
                ),
            },
        )
    except Exception as e:
        logger.error("Gemini analysis call failed for %s: %s", task, e)
        raise

    latency_ms = int((time.time() - start) * 1000)
    raw_response = response.text or ""

    try:
        result = json.loads(raw_response)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_response)
        if m:
            result = json.loads(m.group(1))
        else:
            raise RuntimeError(f"Analysis task {task} returned unparseable JSON")

    if not isinstance(result, dict):
        raise RuntimeError(f"Analysis task {task} returned non-object JSON")

    usage = getattr(response, "usage_metadata", None)
    input_tokens = usage.prompt_token_count if usage and hasattr(usage, "prompt_token_count") else len(prompt) // 4
    output_tokens = usage.candidates_token_count if usage and hasattr(usage, "candidates_token_count") else len(raw_response) // 4
    cached_tokens = 0
    if usage and hasattr(usage, "cached_content_token_count"):
        cached_tokens = usage.cached_content_token_count or 0

    charged_input = max(0, input_tokens - cached_tokens)
    cost_usd = (
        charged_input / 1_000_000 * 0.15 * 0.5 if cached_tokens > 0 else charged_input / 1_000_000 * 0.15
    ) + (output_tokens / 1_000_000 * 0.60)

    analytics = {
        "model": model,
        "provider": provider,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "charged_input_tokens": charged_input,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_usd, 6),
        "cache_used": cached_tokens > 0,
    }

    LLMCallTracker.record(
        provider=provider, model=model, doc_type=task,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cached_tokens=cached_tokens, latency_ms=latency_ms,
        cost_usd=cost_usd, retry_count=0, status="success",
    )

    return {"result": result, "analytics": analytics}
