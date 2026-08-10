"""
Model Router — routes documents to the cheapest adequate model based on doc_type.
Configurable via env-driven MODEL_ROUTING_MAP (JSON string or env vars).
"""

from __future__ import annotations

import json

from backend.config import MODEL_ROUTING_MAP
from backend.logger import get_logger

logger = get_logger(__name__)

DETERMINISTIC_DOC_TYPES = {
    "E_PAYMENT_RECEIPT",
    "PROPERTY_TAX_ASSESSMENT",
    "TAX_RECEIPT",
    "PROPERTY_REGISTER_CARD",
    "RERA_CERTIFICATE",
    "LITIGATION_AFFIDAVIT",
    "ALLOTMENT_LETTER",
    "BUILDING_LICENSE",
    "COMPLETION_CERTIFICATE",
}

REASONING_DOC_TYPES = {
    "SALE_DEED",
    "ENCUMBRANCE_CERTIFICATE",
    "GIFT_DEED",
    "PARTITION_DEED",
}

DEFAULT_ROUTING_MAP = {
    "E_PAYMENT_RECEIPT": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "TAX_RECEIPT": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "PROPERTY_TAX_ASSESSMENT": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "PROPERTY_REGISTER_CARD": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "SALE_DEED": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "ENCUMBRANCE_CERTIFICATE": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "GIFT_DEED": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "PARTITION_DEED": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "KHATA": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    "MUTATION": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "RTC_PAHANI": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "LEGAL_HEIR_CERTIFICATE": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    "COURT_ORDER": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "POSSESSION_CERTIFICATE": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "CONVERSION_ORDER": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "CDP_PLAN": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "RERA_CERTIFICATE": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "LITIGATION_AFFIDAVIT": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "ALLOTMENT_LETTER": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "BUILDING_LICENSE": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "COMPLETION_CERTIFICATE": {"provider": "gemini", "model": "gemini-2.5-flash"},
}

FALLBACK_CHAIN = [
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    {"provider": "groq", "model": "llama-3.1-8b-instant"},
    {"provider": "gemini", "model": "gemini-2.5-flash"},
]


def _load_routing_map() -> dict:
    env_map = MODEL_ROUTING_MAP
    if env_map:
        try:
            return json.loads(env_map)
        except json.JSONDecodeError:
            logger.warning("Invalid MODEL_ROUTING_MAP JSON, using defaults")
    return dict(DEFAULT_ROUTING_MAP)


ROUTING_MAP = _load_routing_map()


def resolve_model(doc_type: str) -> tuple[str, str]:
    """
    Returns (provider, model) for the given doc_type.
    Falls back to default (gemini, gemini-2.5-flash) for unknown types.
    """
    route = ROUTING_MAP.get(doc_type)
    if route:
        return route["provider"], route["model"]
    if doc_type in REASONING_DOC_TYPES:
        return "gemini", "gemini-2.5-flash"
    return "groq", "llama-3.1-8b-instant"


def get_fallback_chain(doc_type: str) -> list[tuple[str, str]]:
    """
    Returns ordered list of (provider, model) to try for fallback.
    Primary first, then fallbacks.
    """
    primary_provider, primary_model = resolve_model(doc_type)
    chain = [(primary_provider, primary_model)]
    seen = {(primary_provider, primary_model)}
    for fallback in FALLBACK_CHAIN:
        key = (fallback["provider"], fallback["model"])
        if key not in seen:
            chain.append(key)
            seen.add(key)
    return chain


def is_deterministic_doc(doc_type: str) -> bool:
    return doc_type in DETERMINISTIC_DOC_TYPES


# ── Case-level analysis tasks ─────────────────────────────────────────────────

def resolve_analysis_task() -> tuple[str, str]:
    """Route the title-chain / verification analysis pass (needs strong reasoning)."""
    return "gemini", "gemini-2.5-flash"
