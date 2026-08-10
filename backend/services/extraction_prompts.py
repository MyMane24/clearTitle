"""Prompt builders for the per-document extraction pass (extraction only)."""
import json

from backend.services.schemas import SCHEMA_MAP, _generic_schema

OUTPUT_QUALITY_CONTRACT = """
You are a Karnataka property-document extraction engine.

TASK
- Extract information from the OCR text into the provided JSON schema.

EXTRACTION RULES
- Use only information supported by the document. Never infer or invent missing values.
- Preserve names, identifiers, survey/CTS/hissa numbers, registration numbers, and monetary values accurately.
- Use null for unavailable scalar fields and [] for unavailable lists.
- Return dates as YYYY-MM-DD. If only month and year are explicitly available, use YYYY-MM-01.
- Return numbers as numeric values, not formatted strings.
- Extract all relevant repeated records or transactions, not only the first.
- When Kannada and English represent the same value, prefer the English equivalent. Do not treat normal transliteration differences as contradictions.

OUTPUT
Return only valid JSON matching the provided schema exactly.

TARGET JSON SCHEMA
{schema_json}
"""


def _build_static_content(doc_type: str) -> str:
    """Build the static instruction + schema portion (same for all docs of this type)."""
    schema = SCHEMA_MAP.get(doc_type, _generic_schema(doc_type))
    schema_json = json.dumps(schema, indent=2)
    return (
        f"You are an expert Karnataka property document analyst. Your task is to extract\n"
        f"structured data from the OCR text, following the OUTPUT QUALITY CONTRACT below exactly.\n\n"
        f"{OUTPUT_QUALITY_CONTRACT.format(schema_json=schema_json)}\n\n"
        f"RULES:\n"
        f"- Return ONLY valid JSON matching the schema exactly.\n"
        f"- Use null for fields not found in document.\n"
        f"- Dates must be YYYY-MM-DD format.\n"
        f"- Numbers must be numeric (not strings).\n"
        f"- Extract ALL transactions from ledgers, not just the first.\n"
        f"- If Kannada text is present, use the English equivalent.\n"
        f"- Do NOT hallucinate values — only extract what is explicitly present.\n"
    )


def _build_user_content(ocr_text: str, page_count: int, doc_type: str) -> str:
    """Build the dynamic per-document content (OCR text)."""
    return (
        f"DOCUMENT: {doc_type} ({page_count} pages)\n\n"
        f"OCR TEXT:\n{ocr_text}\n"
    )
