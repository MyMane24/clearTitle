"""
Groq Structurer Service — primary LLM for document structuring (extraction only).
System prompt is consolidated into the system role so byte-identical requests
benefit from Groq's implicit prompt caching.
"""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy

import httpx
from groq import Groq

from backend.config import GROQ_API_KEY
from backend.integrations.llm.rate_limiter import LLMCallTracker, groq_limiter
from backend.logger import get_logger

logger = get_logger(__name__)

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# Import shared schemas
from backend.services.schemas import SCHEMA_MAP, _generic_schema
from backend.shared.helpers import merge_dict_list

SYSTEM_PROMPT_BASE = """You are an expert Karnataka property document analyst.

TASK — EXTRACT: Fill the JSON schema from the OCR text below.

Rules:
1. Return ONLY valid JSON matching the provided schema exactly.
2. Use null for fields not found in the document.
3. Dates must be YYYY-MM-DD format. If only month/year known, use YYYY-MM-01.
4. Numbers must be numeric types (not strings).
5. For Karnataka documents: CTS = City Survey number, RS = Rural Survey number.
6. Extract ALL transactions from EC historical ledger, not just the first one.
7. If Kannada text is present alongside English, use the English equivalent value.
8. Do not hallucinate values — only extract what is explicitly present in the text."""


def _build_system_message(doc_type: str) -> str:
    """Build a byte-identical system message per doc_type for implicit caching."""
    schema = deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
    schema_json = json.dumps(schema, indent=2)

    return (
        f"{SYSTEM_PROMPT_BASE}\n\n"
        f"TARGET JSON SCHEMA:\n{schema_json}"
    )


def structure_document(merged_ocr: dict, doc_type: str,
                        model_override: str | None = None,
                        retry_count: int = 0) -> dict:
    """
    Call Groq LLM to extract structured fields.
    Returns dict with structured_data and _analytics.
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set in .env")

    schema = deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
    ocr_text = merged_ocr.get("full_text", "")
    page_count = merged_ocr.get("total_pages", 0)

    system_msg = _build_system_message(doc_type)

    user_prompt = (
        f"OCR TEXT FROM DOCUMENT:\n{ocr_text}\n\n"
        f"Return ONLY the filled JSON. No explanation."
    )

    _http_client = httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))
    client = Groq(api_key=GROQ_API_KEY, http_client=_http_client)
    errors = []
    start = time.time()
    actual_retry_count = retry_count
    models_to_try = [model_override] if model_override else GROQ_MODELS

    for model in models_to_try:
        if model is None:
            continue
        try:
            # Acquire rate limit token
            acquired = groq_limiter.wait_and_acquire(tokens=max(1, len(ocr_text) // 100000))
            if not acquired:
                logger.warning("Rate limit wait timeout for Groq %s", doc_type)

            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=5000,
            )
            latency_ms = int((time.time() - start) * 1000)
            raw_content = resp.choices[0].message.content
            raw = (raw_content or "").strip()

            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
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

            usage = resp.usage
            input_tokens = usage.prompt_tokens if usage else len(system_msg + user_prompt) // 4
            output_tokens = usage.completion_tokens if usage else len(raw) // 4
            # gpt-oss-120b: $0.15/$0.60, gpt-oss-20b: $0.075/$0.30 per 1M tokens
            if "gpt-oss-120b" in model:
                cost_usd = (input_tokens / 1_000_000 * 0.15) + (output_tokens / 1_000_000 * 0.60)
            else:
                cost_usd = (input_tokens / 1_000_000 * 0.075) + (output_tokens / 1_000_000 * 0.30)

            analytics = {
                "model": model,
                "provider": "groq",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": 0,  # Groq doesn't expose cached token count
                "latency_ms": latency_ms,
                "cost_usd": round(cost_usd, 6),
                "retry_count": actual_retry_count,
                "cache_used": False,
            }

            LLMCallTracker.record(
                provider="groq", model=model, doc_type=doc_type,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cached_tokens=0, latency_ms=latency_ms,
                cost_usd=cost_usd, retry_count=actual_retry_count, status="success",
            )

            return {
                "structured_data": result,
                "_analytics": analytics,
            }

        except Exception as e:
            error_msg = str(e).lower()
            errors.append(f"{model}: {e}")
            if any(x in error_msg for x in ["429", "quota", "exhausted", "rate"]):
                logger.warning("Groq rate limited on %s: %s", model, e)
                actual_retry_count += 1
            continue

    raise RuntimeError("All Groq models failed. " + " | ".join(errors))
