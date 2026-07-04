"""
Groq Structurer Service — primary LLM for document structuring.
System prompt + verification instructions are consolidated into the system role
so byte-identical requests benefit from Groq's implicit prompt caching.
"""

from __future__ import annotations

import json
import os
import re
import time
from copy import deepcopy

import httpx
from dotenv import load_dotenv
from groq import Groq

from backend.logger import get_logger
from backend.services.rate_limiter import groq_limiter, LLMCallTracker

load_dotenv()

logger = get_logger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

# Import shared schemas and verification instructions
from backend.services.gemini_structurer import (
    VERIFICATION_NOTES_SCHEMA,
    SCHEMA_MAP,
    _get_verification_instructions,
    _generic_schema,
    merge_dict_list,
)

SYSTEM_PROMPT_BASE = """You are an expert Karnataka property document analyst.

TASK 1 — EXTRACT: Fill the JSON schema from the OCR text below.
TASK 2 — VERIFY: While reading, check for document issues and populate the verification_notes array.

Rules:
1. Return ONLY valid JSON matching the provided schema exactly.
2. Use null for fields not found in the document.
3. Dates must be YYYY-MM-DD format. If only month/year known, use YYYY-MM-01.
4. Numbers must be numeric types (not strings).
5. For Karnataka documents: CTS = City Survey number, RS = Rural Survey number.
6. Extract ALL transactions from EC historical ledger, not just the first one.
7. If Kannada text is present alongside English, use the English equivalent value.
8. Do not hallucinate values — only extract what is explicitly present in the text.
9. verification_notes should be an empty array [] if no issues found.
10. Each verification_note MUST have: type, severity, confidence, summary, legal_detail, evidence, suggestion."""


def _build_system_message(doc_type: str) -> str:
    """Build a byte-identical system message per doc_type for implicit caching."""
    verification_instructions = _get_verification_instructions(doc_type)
    schema = deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
    schema_json = json.dumps(schema, indent=2)

    return (
        f"{SYSTEM_PROMPT_BASE}\n\n"
        f"{verification_instructions}\n\n"
        f"TARGET JSON SCHEMA:\n{schema_json}"
    )


def structure_document(merged_ocr: dict, doc_type: str,
                        model_override: str | None = None,
                        retry_count: int = 0) -> dict:
    """
    Call Groq LLM to extract structured fields AND generate verification notes.
    Returns dict with structured_data, verification_notes, _analytics.
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
                max_tokens=32000,
            )
            latency_ms = int((time.time() - start) * 1000)
            raw = resp.choices[0].message.content.strip()

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

            verification_notes = result.pop("verification_notes", [])
            usage = resp.usage
            input_tokens = usage.prompt_tokens if usage else len(system_msg + user_prompt) // 4
            output_tokens = usage.completion_tokens if usage else len(raw) // 4
            cost_usd = (input_tokens / 1_000_000 * 0.59) + (output_tokens / 1_000_000 * 0.79)

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
                "verification_notes": verification_notes,
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
