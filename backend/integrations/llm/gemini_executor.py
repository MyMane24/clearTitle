"""Gemini per-document structuring executor (extraction only)."""
import json
import re
import time

from google import genai
from google.genai import types

from backend.config import GEMINI_MAX_CONTEXT_CHARS
from backend.integrations.llm.gemini_client import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    _ensure_context_cache,
)
from backend.integrations.llm.rate_limiter import LLMCallTracker, gemini_limiter
from backend.logger import get_logger
from backend.services.extraction_prompts import _build_static_content, _build_user_content
from backend.shared.helpers import merge_dict_list

logger = get_logger(__name__)


def structure_document_with_gemini(merged_ocr: dict, doc_type: str,
                                    retry_count: int = 0) -> dict:
    """
    Extract structured fields from OCR in a single LLM call.
    Uses system_instruction for static content + context caching for cost reduction.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env")

    ocr_text = (merged_ocr.get("full_text") or "")[:GEMINI_MAX_CONTEXT_CHARS]
    page_count = merged_ocr.get("total_pages", 0)

    # Build system instruction (static per doc_type)
    static_content = _build_static_content(doc_type)

    # Build user content (dynamic per document)
    user_content = _build_user_content(ocr_text, page_count, doc_type)

    # Attempt context cache
    cache_name = _ensure_context_cache(doc_type)

    client = genai.Client(api_key=GEMINI_API_KEY)
    start = time.time()
    actual_retry_count = retry_count

    try:
        # Acquire rate limit token
        acquired = gemini_limiter.wait_and_acquire(tokens=max(1, len(ocr_text) // 100000))
        if not acquired:
            logger.warning("Rate limit wait timeout for Gemini %s", doc_type)

        gen_config = types.GenerateContentConfig(
            system_instruction=static_content,
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=65536,
            cached_content=cache_name if cache_name else None,
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_content,
            config=gen_config,
        )
    except Exception as e:
        error_msg = str(e).lower()
        if any(x in error_msg for x in ["429", "quota", "exhausted", "resource_exhausted", "rate"]):
            logger.warning("Gemini rate limited for %s: %s", doc_type, e)
            raise
        logger.error("Gemini API call failed for %s: %s", doc_type, e)
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
            raise
    if isinstance(result, list):
        result = merge_dict_list(result)
    if "document_type" not in result:
        result["document_type"] = doc_type

    if "file_metadata" in result and page_count:
        result["file_metadata"]["scanned_sheet_count"] = page_count

    usage = getattr(response, 'usage_metadata', None)
    input_tokens = usage.prompt_token_count if usage and hasattr(usage, 'prompt_token_count') else len(user_content) // 4
    output_tokens = usage.candidates_token_count if usage and hasattr(usage, 'candidates_token_count') else len(raw_response) // 4
    cached_tokens = 0
    if usage and hasattr(usage, 'cached_content_token_count'):
        cached_tokens = usage.cached_content_token_count or 0

    # Charged tokens = input - cached (cached content is billed at reduced rate)
    charged_input = max(0, input_tokens - cached_tokens)
    cost_usd = (charged_input / 1_000_000 * 0.15 * 0.5 if cached_tokens > 0 else charged_input / 1_000_000 * 0.15) + (output_tokens / 1_000_000 * 0.60)

    analytics = {
        "model": GEMINI_MODEL,
        "provider": "gemini",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "charged_input_tokens": charged_input,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_usd, 6),
        "retry_count": actual_retry_count,
        "cache_used": bool(cache_name) and cached_tokens > 0,
    }

    LLMCallTracker.record(
        provider="gemini", model=GEMINI_MODEL, doc_type=doc_type,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cached_tokens=cached_tokens, latency_ms=latency_ms,
        cost_usd=cost_usd, retry_count=actual_retry_count, status="success",
    )

    return {
        "structured_data": result,
        "_analytics": analytics,
    }
