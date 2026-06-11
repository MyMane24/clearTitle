"""
Groq Structurer Service
Takes merged OCR output and a doc_type, calls Groq LLM,
returns structured JSON matching the target schema.

Models tried in order:
  1. llama-3.3-70b-versatile  (best quality)
  2. openai/gpt-oss-120b       (strong production fallback)
  3. qwen/qwen3-32b            (large-context fallback)
  4. llama-3.1-8b-instant      (fast fallback)
"""

import os
import json
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODELS   = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
MAX_CONTEXT_CHARS = 28_000   # ~7k tokens — safe for all Groq models


# ── Schema definitions ─────────────────────────────────────────────────────────

SALE_DEED_SCHEMA = {
    "document_type": "SALE_DEED",
    "file_metadata": {
        "registration_number": None,
        "execution_date":      None,
        "registration_date":   None,
        "issuing_office":      None,
        "scanned_sheet_count": None,
    },
    "financial_summary": {
        "declared_consideration_amount": None,
        "stamp_duty_paid_amount":        None,
        "total_registration_fees":       None,
        "payment_dd_reference":          None,
    },
    "parties": {
        "vendors": [
            {
                "entity_name":     None,
                "represented_by":  None,
                "address":         None,
            }
        ],
        "purchasers": [
            {
                "entity_name":     None,
                "represented_by":  None,
                "address":         None,
            }
        ],
    },
    "property_schedule": {
        "cts_number":              None,
        "survey_number":           None,
        "apartment_or_shop_number": None,
        "floor_location":          None,
        "project_name":            None,
        "full_schedule_description": None,
        "measurements": {
            "super_built_up_area_sqft":  None,
            "undivided_share_land_sqft": None,
            "total_land_area_sqmtr":     None,
        },
        "boundaries": {
            "north": None,
            "east":  None,
            "west":  None,
            "south": None,
        },
        "intended_usage": None,
    },
    "statutory_valuation_endorsement": {
        "estimated_market_value":          None,
        "prevention_of_undervaluation_referred": False,
        "form_1a_communication_date":      None,
    },
}

EC_SCHEMA = {
    "document_type": "ENCUMBRANCE_CERTIFICATE",
    "file_metadata": {
        "application_number": None,
        "reference_number":   None,
        "search_start_date":  None,
        "search_end_date":    None,
        "digital_signature_by": None,
        "issuing_office":     None,
    },
    "search_criteria": {
        "target_village": None,
        "target_hobli":   None,
        "target_identifiers": {
            "cts_number":              None,
            "survey_number":           None,
            "converted_survey_number": None,
            "plot_number":             None,
        },
    },
    "historical_ledger": [
        {
            "transaction_index":    1,
            "execution_date":       None,
            "registration_reference": None,
            "transaction_type":     None,
            "financials": {
                "consideration_amount": None,
                "market_value":         None,
            },
            "parties": {
                "vendors":    [],
                "purchasers": [],
            },
            "property_details": {
                "plot_no":    None,
                "pid_no":     None,
                "cts_no":     None,
                "description": None,
                "measurements": {},
                "boundaries": {
                    "north": None,
                    "east":  None,
                    "west":  None,
                    "south": None,
                },
                "location":   None,
            },
        }
    ],
}

SCHEMA_MAP = {
    "SALE_DEED":               SALE_DEED_SCHEMA,
    "ENCUMBRANCE_CERTIFICATE": EC_SCHEMA,
}


# ── Prompts ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert property document extraction AI for Karnataka, India.
You receive OCR text from scanned property documents (Kannada + English) and extract structured data.

Rules:
1. Return ONLY valid JSON matching the provided schema exactly — no markdown, no preamble.
2. Use null for fields not found in the document.
3. Dates must be in YYYY-MM-DD format. If only month/year known, use YYYY-MM-01.
4. Numbers must be numeric types (not strings).
5. For Karnataka documents: CTS = City Survey number, RS = Rural Survey number.
6. Extract ALL transactions from EC historical ledger, not just the first one.
7. If Kannada text is present alongside English, use the English equivalent value.
8. Do not hallucinate values — only extract what is explicitly present in the text.
"""

USER_PROMPT_TEMPLATE = """Extract structured data from this {doc_type} document.

TARGET JSON SCHEMA:
{schema}

OCR TEXT FROM DOCUMENT:
{ocr_text}

Return ONLY the filled JSON. No explanation."""


def structure_document(merged_ocr: dict, doc_type: str) -> dict:
    """
    Call Groq LLM to extract structured fields from merged OCR output.
    Returns structured dict.
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set in .env")

    schema = SCHEMA_MAP.get(doc_type, _generic_schema(doc_type))

    # Truncate OCR text to fit context window
    ocr_text = merged_ocr.get("full_text", "")[:MAX_CONTEXT_CHARS]

    user_prompt = USER_PROMPT_TEMPLATE.format(
        doc_type = doc_type,
        schema   = json.dumps(schema, indent=2),
        ocr_text = ocr_text,
    )

    client = Groq(api_key=GROQ_API_KEY)
    errors = []

    for model in GROQ_MODELS:
        try:
            resp = client.chat.completions.create(
                model    = model,
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature = 0.0,
                max_tokens  = 4096,
            )
            raw = resp.choices[0].message.content.strip()
            return _parse_json_response(raw, doc_type)

        except Exception as e:
            errors.append(f"{model}: {e}")
            # Try next model on rate limit or error
            continue

    raise RuntimeError("All Groq models failed. " + " | ".join(errors))


def _parse_json_response(raw: str, doc_type: str) -> dict:
    """
    Extract JSON from LLM response.
    Handles cases where model wraps output in markdown code fences.
    """
    # Strip markdown code fences if present
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    clean = re.sub(r"```\s*$", "", clean).strip()

    try:
        parsed = json.loads(clean)
        # Ensure document_type is set
        if "document_type" not in parsed:
            parsed["document_type"] = doc_type
        return parsed
    except json.JSONDecodeError as e:
        # Try to extract first JSON object in the response
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        raise ValueError(f"Could not parse JSON from Groq response: {e}\n\nRaw:\n{raw[:500]}")


def _generic_schema(doc_type: str) -> dict:
    """Fallback schema for unrecognised document types."""
    return {
        "document_type":  doc_type,
        "file_metadata":  {
            "registration_number": None,
            "execution_date":      None,
            "registration_date":   None,
            "issuing_office":      None,
        },
        "parties": {
            "vendors":    [],
            "purchasers": [],
        },
        "property_details": {
            "survey_number": None,
            "location":      None,
        },
        "raw_notes": "Schema not defined for this document type. Key fields extracted.",
    }
