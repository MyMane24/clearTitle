"""
Gemini Structurer Service
Uses Gemini for non-EC structured extraction with a larger context window.
"""

import json
import os
import re
from copy import deepcopy

from dotenv import load_dotenv
from google import genai

from backend.services.groq_structurer import (
    EC_SCHEMA,
    SALE_DEED_SCHEMA,
    SYSTEM_PROMPT,
    _generic_schema,
)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Keep a guardrail below Gemini's 1M-token context. This is chars, not tokens.
GEMINI_MAX_CONTEXT_CHARS = int(os.getenv("GEMINI_MAX_CONTEXT_CHARS", "800000"))

PROPERTY_REGISTER_CARD_SCHEMA = {
    "document_type": "PROPERTY_REGISTER_CARD",
    "document_metadata": {
        "issuing_authority": None,
        "taluka": None,
        "district": None,
        "application_number": None,
        "application_date": None,
        "copy_ready_on": None,
        "copy_delivered_on": None,
        "copy_applied_by": None,
    },
    "property_identification": {
        "division_number_or_local_area_number": None,
        "local_area_name": None,
        "pt_sheet_number": None,
        "city_survey_number": None,
        "area_sq_meters": None,
        "tenure": None,
    },
    "holders": [
        {
            "name": None,
            "share": None,
            "notes": None,
        }
    ],
    "easements": None,
    "lessee": None,
    "other_encumbrances": None,
    "guidance_value": {
        "value": None,
        "order_number": None,
        "order_date": None,
    },
    "property_boundaries_sketch_present": None,
    "mutation_or_transaction_entries": [
        {
            "date": None,
            "transaction": None,
            "volume_number": None,
            "new_holder_or_lessee_or_encumbrance": None,
            "attestation": None,
        }
    ],
    "fees": {
        "copying_fee": None,
        "comparing_fee": None,
        "form_fee": None,
        "copying_surcharge": None,
        "round_off": None,
        "total": None,
    },
    "certification": {
        "signed_by": None,
        "designation": None,
        "office": None,
    },
}

E_PAYMENT_RECEIPT_SCHEMA = {
    "document_type": "E_PAYMENT_RECEIPT",
    "document_metadata": {
        "issuing_authority": None,
        "city_or_local_body": None,
        "receipt_title": None,
        "source_website": None,
    },
    "consumer_details": {
        "owner_name": None,
        "pid": None,
        "ward_name": None,
    },
    "transaction_details": {
        "transaction_number": None,
        "payment_reference_number": None,
        "status": None,
        "receipt_date": None,
    },
    "service_details": {
        "service_type": None,
        "assessment_year": None,
        "sas_number": None,
    },
    "payment_details": {
        "service_charges": None,
        "amount_paid": None,
        "total_amount": None,
        "currency": "INR",
    },
    "notes": {
        "terms_and_conditions": [],
        "thank_you_message": None,
    },
}

PROPERTY_TAX_ASSESSMENT_SCHEMA = {
    "document_type": "PROPERTY_TAX_ASSESSMENT",
    "document_metadata": {
        "issuing_authority": None,
        "form_number": None,
        "pid": None,
        "old_assessment_number": None,
        "new_assessment_number": None,
        "date": None,
        "document_datetime_raw": None,
        "assessment_year": None,
        "property_type": None,
    },
    "property_owner": {
        "owner_name": None,
        "occupier_name": None,
        "pid": None,
        "old_assessment_number": None,
        "new_assessment_number": None,
        "ward_number": None,
    },
    "property_details": {
        "property_address": None,
        "street_or_area_name": None,
        "cts_number": None,
        "property_number": None,
        "usage": None,
        "site_total_area_sqft": None,
        "building_covered_land_area_sqft": None,
        "total_constructed_area_sqft": None,
        "building_plinth_area_sqft": None,
    },
    "assessment_table": {
        "raw_rows": [
            {
                "row_number": None,
                "label": None,
                "value": None,
            }
        ],
        "mapped_fields": {
            "owner_name": None,
            "occupier_name": None,
            "owner_address": None,
            "assessment_year": None,
            "ward_number": None,
            "street_or_area_name": None,
            "property_number": None,
            "site_total_area_sqft": None,
            "building_covered_land_area_sqft": None,
            "total_constructed_area_sqft": None,
            "plinth_factor": None,
            "vacant_land_area_sqft": None,
            "land_market_value": None,
            "land_market_value_50_percent": None,
            "building_type": None,
            "construction_cost_per_sqft": None,
            "building_plinth_area_sqft": None,
            "building_taxable_value": None,
            "usage": None,
            "property_tax_payable": None,
            "cess_details": {
                "health_cess": None,
                "library_cess": None,
                "beggary_cess": None,
                "urban_transport_cess": None,
            },
            "cess_total": None,
            "swm_cess": None,
            "swm_service_charges": None,
            "ugd_cess": None,
            "penalty": None,
            "total_payable": None,
            "payment_mode": None,
            "challan_number": None,
        },
    },
    "challan_copies": [
        {
            "copy_index": None,
            "copy_type": None,
            "copy_type_raw": None,
            "pid": None,
            "assessment_number": None,
            "payment_mode": None,
            "ward_number": None,
            "assessment_year": None,
            "owner_name": None,
            "property_address": None,
            "occupier_name": None,
            "property_tax_paid": None,
            "cess_paid": None,
            "swm_cess": None,
            "swm_service_charges": None,
            "penalty": None,
            "service_charge": None,
            "total_amount": None,
            "amount_in_words": None,
            "payment_date": None,
            "bank_account_or_challan_number": None,
        }
    ],
    "validity": {
        "valid_for_month": None,
        "issued_by": None,
    },
}

SCHEMA_MAP = {
    "SALE_DEED": SALE_DEED_SCHEMA,
    "ENCUMBRANCE_CERTIFICATE": EC_SCHEMA,
    "PROPERTY_REGISTER_CARD": PROPERTY_REGISTER_CARD_SCHEMA,
    "E_PAYMENT_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
    "PROPERTY_TAX_ASSESSMENT": PROPERTY_TAX_ASSESSMENT_SCHEMA,
    "TAX_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
}


def structure_document_with_gemini(merged_ocr: dict, doc_type: str) -> dict:
    """
    Extract structured fields from merged OCR using Gemini.
    EC documents should not call this; they are parsed deterministically.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env")

    schema = deepcopy(SCHEMA_MAP.get(doc_type, _generic_schema(doc_type)))
    prompt = _build_prompt(
        doc_type=doc_type,
        schema=schema,
        ocr_text=(merged_ocr.get("full_text") or "")[:GEMINI_MAX_CONTEXT_CHARS],
    )

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "temperature": 0.0,
        },
    )
    return _parse_json_response(response.text, doc_type)


def _build_prompt(*, doc_type: str, schema: dict, ocr_text: str) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Extract structured data from this {doc_type} document.\n\n"
        "Rules for this extraction:\n"
        "- Read the full OCR text provided below.\n"
        "- Return only fields supported by the target JSON schema.\n"
        "- Use null for missing values.\n"
        "- Do not hallucinate values.\n\n"
        f"TARGET JSON SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"OCR TEXT FROM DOCUMENT:\n{ocr_text}\n"
    )


def _parse_json_response(raw: str, doc_type: str) -> dict:
    clean = re.sub(r"```(?:json)?\s*", "", raw or "").strip()
    clean = re.sub(r"```\s*$", "", clean).strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            raise ValueError(f"Could not parse JSON from Gemini response: {exc}")
        parsed = json.loads(match.group())

    if "document_type" not in parsed:
        parsed["document_type"] = doc_type
    return parsed

