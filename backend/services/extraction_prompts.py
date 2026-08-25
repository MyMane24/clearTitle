"""Prompt builders for the per-document extraction pass (extraction only)."""
import json

from backend.prompts.loader import load_prompt
from backend.services.schemas import SCHEMA_MAP, _generic_schema

_EXTRACTION_CONTRACT_TEMPLATE = load_prompt("extraction_contract")
_GEMINI_SYSTEM_TEMPLATE = load_prompt("gemini_system")
_GEMINI_USER_TEMPLATE = load_prompt("gemini_user")


def _build_static_content(doc_type: str) -> str:
    """Build the static instruction + schema portion (same for all docs of this type)."""
    schema = SCHEMA_MAP.get(doc_type, _generic_schema(doc_type))
    schema_json = json.dumps(schema, indent=2)
    quality_contract = _EXTRACTION_CONTRACT_TEMPLATE.format(schema_json=schema_json)
    return _GEMINI_SYSTEM_TEMPLATE.format(quality_contract=quality_contract)


def _build_user_content(ocr_text: str, page_count: int, doc_type: str) -> str:
    """Build the dynamic per-document content (OCR text)."""
    return _GEMINI_USER_TEMPLATE.format(
        doc_type=doc_type, page_count=page_count, ocr_text=ocr_text,
    )
