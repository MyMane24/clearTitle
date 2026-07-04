"""
Gemini Structurer Service
=========================
Two passes are available:

1. structure_document_with_gemini()
   Per-document pass: reads full OCR, extracts structured data AND generates
   within-document verification notes (e.g. "this document's own dates are out
   of order", "this document's own stamp duty % looks wrong"). Uses
   system_instruction for static content (schema + instructions) and explicit
   context caching to reduce cost and rate-limit consumption.

   ALL checks — including pure-arithmetic ones (date ordering, stamp duty
   ratio, the Section 269SS cash-payment check, dimension-vs-area math, EC
   gap-years, EC mortgage/release matching) — are performed by the LLM itself,
   per the per-doc-type instructions below. There is no Python-side
   deterministic check layer. Because LLMs are measurably worse at exact
   arithmetic than code, every check that involves a computation explicitly
   instructs the model to show the computation inline in "evidence" (e.g.
   "30 x 40 = 1200") so the math is auditable from the output alone rather
   than trusted blindly. Every verification_note is tagged "source": "llm".

2. cross_verify_documents()
   Cross-document pass: takes the already-extracted structured_data for ALL
   documents belonging to one property and checks they tell a consistent
   story — the way a property lawyer lays every document side by side and
   checks survey numbers, names, dates, valuations, mutation status, and
   chain of title against each other. This catches things no single document
   can reveal on its own (e.g. EC shows a mortgage with no release deed
   anywhere in the set; Property Register Card mutation hasn't caught up to
   the latest Sale Deed; declared consideration is far below guidance value).

Both passes follow the same OUTPUT QUALITY CONTRACT: every finding must cite
the literal field values that triggered it. A finding that only names a
*category* of problem ("CTS mismatch") without quoting the actual conflicting
values is not acceptable output and the prompt explicitly forbids it.
"""

import json
import os
import re
import time
from copy import deepcopy
from datetime import date, datetime

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.logger import get_logger
from backend.services.rate_limiter import gemini_limiter, LLMCallTracker

load_dotenv()

logger = get_logger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_CONTEXT_CHARS = int(os.getenv("GEMINI_MAX_CONTEXT_CHARS", "800000"))
CACHE_TTL_SECONDS = int(os.getenv("GEMINI_CACHE_TTL", "3600"))

# Minimum search window (years) Karnataka due-diligence practice expects an EC to cover.
EC_MIN_SEARCH_YEARS = 13
# Gap (years) between consecutive EC transactions worth flagging as an unexplained window.
EC_GAP_FLAG_YEARS = 3
# Acceptable band for stamp duty as a % of declared consideration before flagging.
STAMP_DUTY_PCT_MIN = 4.5
STAMP_DUTY_PCT_MAX = 8.5
# Section 269SS cash threshold limit
CASH_PAYMENT_269SS_THRESHOLD = 20000

# ── Schema definitions with verification_notes ────────────────────────────

VERIFICATION_NOTES_SCHEMA = {
    "verification_notes": [
        {
            "title": "Specific descriptive title explaining exactly what is wrong (e.g., 'Survey Number differs between Sale Deed and EC')",
            "severity": "critical | high | medium | low",
            "type": "DATE_INCONSISTENCY | FINANCIAL_MISMATCH | MISSING_DOCUMENT | PROPERTY_MISMATCH | PENDING_MORTGAGE | EC_GAP | MUTATION_PENDING | CONVERSION_MISSING | TAX_DEFAULT | GUIDANCE_VALUE_ISSUE | SUSPICIOUS_PATTERN",
            "confidence": 0.0,
            "what_was_detected": "Factual description of the issue detected in the document",
            "evidence": "Human readable exact evidence text from document (e.g., 'Sale Deed Page 3: Survey Number 663/1 Paiki'). Never show JSON paths",
            "reason": "Practical explanation of why this was flagged. Never write legal essays or general descriptions of the Acts.",
            "possible_causes": ["Cause 1", "Cause 2"],
            "impact": "Practical/business impact or risk if this is not resolved",
            "verification_steps": ["Step 1", "Step 2"],
            "legal_reference": "Optional collapsible legal statute reference (e.g. 'Section 54, Transfer of Property Act')"
        }
    ],
}

SALE_DEED_SCHEMA = {
    "document_type": "SALE_DEED",
    "file_metadata": {
        "registration_number": None,
        "execution_date": None,
        "registration_date": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
    },
    "financial_summary": {
        "declared_consideration_amount": None,
        "stamp_duty_paid_amount": None,
        "total_registration_fees": None,
        "payment_dd_reference": None,
        "payment_breakdown": [
            {"amount": None, "mode": None, "instrument_reference": None, "instrument_date": None, "bank_branch": None}
        ],
    },
    "parties": {
        "vendors": [{"entity_name": None, "represented_by": None, "address": None}],
        "purchasers": [{"entity_name": None, "represented_by": None, "address": None}],
    },
    "property_schedule": {
        "cts_number": None,
        "survey_number": None,
        "apartment_or_shop_number": None,
        "floor_location": None,
        "project_name": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions_text": None,
            "super_built_up_area_sqft": None,
            "undivided_share_land_sqft": None,
            "total_land_area_sqmtr": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "intended_usage": None,
    },
    "statutory_valuation_endorsement": {
        "estimated_market_value": None,
        "prevention_of_undervaluation_referred": False,
        "form_1a_communication_date": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

EC_SCHEMA = {
    "document_type": "ENCUMBRANCE_CERTIFICATE",
    "file_metadata": {
        "application_number": None,
        "certificate_number": None,
        "reference_number": None,
        "search_start_date": None,
        "search_end_date": None,
        "search_period_years": None,
        "digital_signature_by": None,
        "issuing_office": None,
    },
    "search_criteria": {
        "target_village": None,
        "target_hobli": None,
        "target_district": None,
        "target_identifiers": {
            "cts_number": None,
            "survey_number": None,
            "converted_survey_number": None,
            "plot_number": None,
        },
    },
    "historical_ledger": [
        {
            "transaction_index": 1,
            "execution_date": None,
            "registration_reference": None,
            "transaction_type": None,
            "parent_survey_number_raw": None,
            "locality_raw": None,
            "share_fraction": None,
            "is_agreement_to_sell": False,
            "minor_or_legal_heir_party": False,
            "financials": {"consideration_amount": None, "market_value": None},
            "parties": {"vendors": [], "purchasers": []},
            "property_details": {
                "plot_no": None, "pid_no": None, "cts_no": None,
                "description": None, "measurements": {},
                "boundaries": {"north": None, "east": None, "west": None, "south": None},
                "location": None,
            },
        }
    ],
    **VERIFICATION_NOTES_SCHEMA,
}

PROPERTY_REGISTER_CARD_SCHEMA = {
    "document_type": "PROPERTY_REGISTER_CARD",
    "document_metadata": {
        "issuing_authority": None, "taluka": None, "district": None,
        "application_number": None, "application_date": None,
        "copy_ready_on": None, "copy_delivered_on": None,
        "copy_applied_by": None,
    },
    "property_identification": {
        "division_number_or_local_area_number": None, "local_area_name": None,
        "pt_sheet_number": None, "city_survey_number": None,
        "area_sq_meters": None, "tenure": None,
    },
    "holders": [{"name": None, "share": None, "notes": None}],
    "easements": None,
    "lessee": None,
    "other_encumbrances": None,
    "guidance_value": {"value": None, "order_number": None, "order_date": None},
    "property_boundaries_sketch_present": None,
    "mutation_or_transaction_entries": [
        {"date": None, "transaction": None, "volume_number": None,
         "new_holder_or_lessee_or_encumbrance": None, "attestation": None}
    ],
    "fees": {
        "copying_fee": None, "comparing_fee": None, "form_fee": None,
        "copying_surcharge": None, "round_off": None, "total": None,
    },
    "certification": {"signed_by": None, "designation": None, "office": None},
    **VERIFICATION_NOTES_SCHEMA,
}

E_PAYMENT_RECEIPT_SCHEMA = {
    "document_type": "E_PAYMENT_RECEIPT",
    "document_metadata": {
        "issuing_authority": None, "city_or_local_body": None,
        "receipt_title": None, "source_website": None,
    },
    "consumer_details": {"owner_name": None, "pid": None, "ward_name": None},
    "transaction_details": {
        "transaction_number": None, "payment_reference_number": None,
        "status": None, "receipt_date": None,
    },
    "service_details": {"service_type": None, "assessment_year": None, "sas_number": None},
    "payment_details": {
        "service_charges": None, "amount_paid": None,
        "total_amount": None, "currency": "INR",
    },
    "notes": {"terms_and_conditions": [], "thank_you_message": None},
    **VERIFICATION_NOTES_SCHEMA,
}

PROPERTY_TAX_ASSESSMENT_SCHEMA = {
    "document_type": "PROPERTY_TAX_ASSESSMENT",
    "document_metadata": {
        "issuing_authority": None, "form_number": None, "pid": None,
        "old_assessment_number": None, "new_assessment_number": None,
        "date": None, "document_datetime_raw": None,
        "assessment_year": None, "property_type": None,
    },
    "property_owner": {
        "owner_name": None, "occupier_name": None, "pid": None,
        "old_assessment_number": None, "new_assessment_number": None,
        "ward_number": None,
    },
    "assessment_rows": [
        {"row_number": None, "label": None, "value": None}
    ],
    "challan_copies": [
        {
            "copy_type": None,
            "pid": None,
            "challan_number": None,
            "receipt_number": None,
            "transaction_id": None,
            "bank_name": None,
            "bank_branch": None,
            "ward_number": None,
            "assessment_year": None,
            "owner_name": None,
            "property_address": None,
            "property_tax_amount": None,
            "penalty_amount": None,
            "service_charge": None,
            "rebate_amount": None,
            "total_amount_due": None,
            "amount_paid": None,
            "payment_date": None,
            "payment_mode": None,
            "payment_status": None,
            "remarks": None,
        }
    ],
    "validity": {"valid_for_month": None, "issued_by": None},
    **VERIFICATION_NOTES_SCHEMA,
}


GIFT_DEED_SCHEMA = {
    "document_type": "GIFT_DEED",
    "file_metadata": {
        "registration_number": None, "document_number": None,
        "book_number": None, "cd_number": None,
        "execution_date": None, "registration_date": None,
        "registration_time": None, "registration_district": None,
        "issuing_office": None, "scanned_sheet_count": None,
        "drafted_by": None, "stamp_paper_society": None,
        "stamp_paper_price": None,
    },
    "financial_summary": {
        "stamp_duty_amount": None, "stamp_duty_payment_mode": None,
        "stamp_duty_certificate_reference": None,
        "stamp_duty_certificate_date": None, "registration_fee": None,
        "scanning_fee": None, "scrutiny_fee": None,
        "total_registration_fees": None,
    },
    "parties": {
        "donors": [{"entity_name": None, "age": None, "occupation": None,
                      "address": None, "aadhar_number": None}],
        "donees": [{"entity_name": None, "age": None, "occupation": None,
                      "address": None, "aadhar_number": None}],
        "relationship_between_parties": None,
        "reason_for_gift": None,
    },
    "property_schedule": {
        "plot_number": None, "survey_number": None, "cts_number": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions": None, "total_land_area_sqft": None,
            "total_land_area_gunthas": None,
            "ground_floor_building_area_sqmtrs": None,
            "first_floor_building_area_sqmtrs": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "property_address": None, "property_type": None,
        "building_description": None,
    },
    "covenants": [],
    "registration_participants": {
        "presented_by": None, "executant": None, "claimant": None,
        "registering_officer_name": None,
        "registering_officer_designation": None,
    },
    "witnesses": [{"name": None, "address": None}],
    "certification": {
        "true_copy": None, "certifying_authority_name": None,
        "certifying_authority_qualification": None,
        "certifying_authority_location": None, "certification_date": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

RTC_PAHANI_SCHEMA = {
    "document_type": "RTC_PAHANI",
    "land_details": {
        "survey_number": None,          # Column 1
        "hissa_number": None,           # Column 2
        "village": None,
        "hobli": None,
        "taluk": None,
        "district": None,
        "extent_details": {             # Column 3
            "total_extent_acres_gunthas": None,
            "kharab_land_a_acres_gunthas": None,
            "kharab_land_b_acres_gunthas": None,
            "net_area_acres_gunthas": None,
        },
        "revenue_details": {            # Column 4
            "land_revenue": None,
            "jodi": None,
            "cess": None,
            "water_rate": None,
            "total_revenue": None,
        },
        "soil_type": None,              # Column 5 (e.g. Masari)
        "tenure_type": None,            # Column 6 (e.g. Government/Freehold)
        "trees_count": [],              # Column 7 (e.g. Name + Count)
    },
    "owners_column_9": [                # Column 9 and 10
        {
            "owner_name": None,
            "father_husband_name": None,
            "extent_owned_acres_gunthas": None,
            "khata_number": None,
            "acquisition_mode_column_10": None, # e.g. "MR H551/2012-2013"
            "acquisition_date": None,
        }
    ],
    "other_rights_and_liabilities_column_11": { # Column 11
        "conditions_notes": None,               # ಷರತ್ತುಗಳು (e.g. NA conversion)
        "liabilities_loans": [],                 # ಋಣಗಳು (e.g. Bank mortgages)
    },
    "cultivator_crop_details_column_12": [      # Columns 12 to 16
        {
            "year": None,                       # e.g. 2023-2024
            "season": None,                     # e.g. Mungaru / Hingaru
            "cultivator_name": None,
            "cultivation_type": None,
            "cultivated_area_acres_gunthas": None,
            "crop_name": None,
            "crop_area": None,
        }
    ],
    "certification_metadata": {
        "signed_by": None,
        "signed_date": None,
        "rtc_unique_number": None,              # RTC UniqueNumber
        "bhoomi_land_id": None,                 # Bhoomi Land ID
    },
    **VERIFICATION_NOTES_SCHEMA,
}

CONVERSION_ORDER_SCHEMA = {
    "document_type": "CONVERSION_ORDER",
    "file_metadata": {
        "order_number": None,                   # ಸಂಖ್ಯೆ (e.g. 386986)
        "order_date": None,                     # ದಿನಾಂಕ
        "issuing_office": None,                 # e.g. DC Office Dharwad
        "dc_name": None,                        # e.g. Gurudatta Narayana Hegde
        "applicant_name": None,                 # e.g. Chavan Ramesh
        "affidavit_number": None,
        "affidavit_date": None,
    },
    "financials": {
        "conversion_fee": None,                 # ಭೂ ಪರಿವರ್ತನಾ ಶುಲ್ಕ
        "podi_fee": None,                       # ಪೋಡಿ ಶುಲ್ಕ
        "kharab_fee": None,
        "penalty_fee": None,                    # ದಂಡ ಶುಲ್ಕ
        "total_fee_paid": None,
        "payment_challans": [                   # Challan references
            {"challan_number": None, "challan_date": None, "amount": None}
        ],
    },
    "property_details": {
        "survey_number": None,
        "total_extent_acres_gunthas": None,
        "converted_extent_acres_gunthas": None,
        "converted_purpose": None,              # e.g. Apartment - Residential
        "boundaries": {                         # ಚಕ್ಕುಬಂದಿ
            "east": None,
            "west": None,
            "north": None,
            "south": None,
        },
    },
    "conditions": [],                           # Conditions 1-9 & Additional Conditions 1-4
    **VERIFICATION_NOTES_SCHEMA,
}

MUTATION_SCHEMA = {
    "document_type": "MUTATION",
    "file_metadata": {
        "mutation_number": None,                # M.R. ನಂಬರ್
        "mutation_year": None,                  # ವಹಿವಾಟು ವರ್ಷ
        "village": None,
        "hobli": None,
        "taluk": None,
        "district": None,
        "acquisition_mode": None,               # e.g. ವಿಭಜನೆ (Partition)
        "order_date": None,
    },
    "transaction_details": [                    # Division of survey numbers
        {
            "old_survey_number": None,
            "old_extent_acres_gunthas": None,
            "old_revenue": None,
            "new_survey_number": None,
            "new_extent_acres_gunthas": None,
            "new_revenue": None,
            "owner_name": None,
        }
    ],
    "attestation": {
        "attested_by": None,
        "attested_date": None,
        "status": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

CDP_PLAN_SCHEMA = {
    "document_type": "CDP_PLAN",
    "file_metadata": {
        "approval_number": None,
        "approval_date": None,
        "approving_authority": None,
        "survey_numbers_covered": [],
    },
    "zoning_classification": None,
    "road_width_meters": None,
    **VERIFICATION_NOTES_SCHEMA,
}

GENERIC_SCHEMA_TEMPLATE = {
    "document_type": None,
    "file_metadata": {
        "document_title": None, "issuing_authority": None,
        "document_date": None, "document_number": None,
    },
    "key_identifiers": {
        "property_identifier": None, "owner_or_party_names": [],
        "location": None,
    },
    "key_values": {},
    **VERIFICATION_NOTES_SCHEMA,
}

SCHEMA_MAP = {
    "SALE_DEED": SALE_DEED_SCHEMA,
    "ENCUMBRANCE_CERTIFICATE": EC_SCHEMA,
    "PROPERTY_REGISTER_CARD": PROPERTY_REGISTER_CARD_SCHEMA,
    "E_PAYMENT_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
    "PROPERTY_TAX_ASSESSMENT": PROPERTY_TAX_ASSESSMENT_SCHEMA,
    "TAX_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
    "GIFT_DEED": GIFT_DEED_SCHEMA,
    "RTC_PAHANI": RTC_PAHANI_SCHEMA,
    "CONVERSION_ORDER": CONVERSION_ORDER_SCHEMA,
    "MUTATION": MUTATION_SCHEMA,
    "CDP_PLAN": CDP_PLAN_SCHEMA,
}

# Schema for the cross-document pass — note the extra "doc_ids_involved" field,
# which doesn't exist on the per-document schema because a per-document note is
# implicitly about the document it was extracted from.
CROSS_DOC_SCHEMA = {
    "cross_document_findings": [
        {
            "title": "Specific descriptive title explaining exactly what is wrong (e.g. 'Sale Consideration differs between Sale Deed and EC')",
            "severity": "critical | high | medium | low",
            "type": "DATE_INCONSISTENCY | FINANCIAL_MISMATCH | MISSING_DOCUMENT | PROPERTY_MISMATCH | PENDING_MORTGAGE | EC_GAP | MUTATION_PENDING | CONVERSION_MISSING | TAX_DEFAULT | GUIDANCE_VALUE_ISSUE | SUSPICIOUS_PATTERN",
            "confidence": 0.0,
            "doc_ids_involved": ["SALE_DEED", "ENCUMBRANCE_CERTIFICATE"],
            "what_was_detected": "Factual description of the issue detected across these documents",
            "evidence": "Human readable exact evidence (e.g. 'Sale Deed: Rs 25,00,000 vs EC: Rs 58,00,000'). Never show JSON paths",
            "reason": "Practical explanation of why this was flagged. Never write legal essays or general descriptions of the Acts.",
            "possible_causes": ["Cause 1", "Cause 2"],
            "impact": "Practical/business impact or risk if this is not resolved",
            "verification_steps": ["Step 1", "Step 2"],
            "legal_reference": "Optional collapsible legal statute reference (e.g. 'Section 54, Transfer of Property Act')"
        }
    ]
}

# ── Output quality contract (shared by both the per-document and cross-document prompts) ──
# This exists specifically to stop the model from producing findings that name a *category*
# of problem ("Inconsistency in CTS number...") without quoting the actual values, and from
# padding "legal_detail" with generic statute summaries that aren't tied to the real facts.

OUTPUT_QUALITY_CONTRACT = """
OUTPUT QUALITY CONTRACT — read this carefully, it fixes a known failure mode.

You must behave like a SENIOR PROPERTY DUE DILIGENCE LAWYER. Your job is to produce production-grade due diligence findings for property buyers, advocates, and bank loan verification teams. 

DO NOT write like a Law Professor or a Legal Research Assistant.
1. NEVER explain the history or general purposes of Acts or Sections.
2. NEVER write generic descriptions like "Under the Registration Act..." or "Section X states that...". 
3. Apply all legal rules SILENTLY. Write ONLY practical, business-driven, and evidence-supported risks.
4. Keep all findings understandable within 10 seconds.
5. All legal references must be optional, simple citations in the "legal_reference" field only.

BAD finding (do NOT produce output like this):
  title: "PROPERTY_MISMATCH"
  what_was_detected: "CTS number mismatch."
  evidence: "property_details.cts_number vs assessment_rows[2].value"
  reason: "Accurate property identification is crucial under the Karnataka Municipal Corporations Act, 1976. Section 58 of the Act dictates proper tax assessments. Discrepancies in CTS numbers can lead to ownership disputes and incorrect tax levies by local authorities."
  possible_causes: ["Incorrect data entry", "Invalid survey"]
  impact: "Ownership cannot be verified."
  verification_steps: ["Verify the correct CTS number."]
  legal_reference: "Karnataka Municipal Corporations Act, 1976 — Section 58"

GOOD finding (same underlying issue, produced correctly):
  title: "CTS Number Mismatch between Address and Tax Assessment"
  severity: "high"
  type: "PROPERTY_MISMATCH"
  confidence: 0.92
  what_was_detected: "CTS number is recorded as '1918' in property details but '1928 Bhag 1' in the tax assessment row."
  evidence: "Property Details -> CTS No: '1918' | Tax Assessment Row 2: '1928 Bhag 1'"
  reason: "Property tax is levied against a specific city survey subdivision. If 1918 and 1928 Bhag 1 are different subdivisions, this tax assessment may not belong to the property under review."
  possible_causes: ["Property subdivision not updated", "Tax record covers adjacent plot", "Typographical error in tax assessment"]
  impact: "Property tax cannot be verified as paid for the subject property, and ownership transfer may be delayed."
  verification_steps: [
    "Confirm with BBMP Revenue Department which CTS number applies",
    "Obtain latest City Survey Map/CTS sketch to verify the subdivision number",
    "Request updated tax assessment card from seller"
  ]
  legal_reference: "Section 58, Karnataka Municipal Corporations Act, 1976"

RULES FOR EVERY FINDING:
1. title: MUST be specific and describe what exactly is wrong (e.g. 'Survey Number differs between Sale Deed and EC'), NOT a generic category like 'PROPERTY_MISMATCH'.
2. evidence: MUST be human-readable text quoting exact values and where they appeared. NEVER show JSON paths or technical keys (e.g. show 'Sale Deed Page 3: 663/1 Paiki' instead of 'property_schedule.survey_number').
3. reason: 1-2 practical, direct sentences explaining why this matters. No statute explanations.
4. possible_causes: Bullet points/list of practical, likely reasons.
5. impact: Factual business or legal risk of this finding.
6. verification_steps: Specific, actionable, concrete next checks. No generic placeholders.
7. legal_reference: Simple citations (e.g., 'Section 54, Transfer of Property Act'), collapsed by default.
8. If no issues found, return an empty array [].
"""

# ── Context cache (per doc_type) ───────────────────────────────────────────
# Keys: doc_type -> {"cache_name": str, "cache_id": str, "created_at": float}

_context_caches: dict[str, dict] = {}
_cache_client = None


def _get_cache_client():
    global _cache_client
    if _cache_client is None:
        _cache_client = genai.Client(api_key=GEMINI_API_KEY)
    return _cache_client


def _build_static_content(doc_type: str) -> str:
    """Build the static instruction + schema portion (same for all docs of this type)."""
    schema = SCHEMA_MAP.get(doc_type, _generic_schema(doc_type))
    schema_json = json.dumps(schema, indent=2)
    verification_instructions = _get_verification_instructions(doc_type)
    return (
        f"You are an expert Karnataka property document analyst. Your task has TWO parts:\n\n"
        f"PART 1 — EXTRACT: Fill the JSON schema below from the OCR text.\n"
        f"PART 2 — VERIFY: While reading, check for issues and populate verification_notes,\n"
        f"following the OUTPUT QUALITY CONTRACT below exactly.\n\n"
        f"{OUTPUT_QUALITY_CONTRACT}\n\n"
        f"{verification_instructions}\n\n"
        f"TARGET JSON SCHEMA:\n{schema_json}\n\n"
        f"RULES:\n"
        f"- Return ONLY valid JSON matching the schema exactly.\n"
        f"- Use null for fields not found in document.\n"
        f"- Dates must be YYYY-MM-DD format.\n"
        f"- Numbers must be numeric (not strings).\n"
        f"- Extract ALL transactions from ledgers, not just the first.\n"
        f"- If Kannada text is present, use the English equivalent.\n"
        f"- Do NOT hallucinate values — only extract what is explicitly present.\n"
        f"- verification_notes should be an empty array [] if no issues found.\n"
        f"- Each verification_note MUST have exactly these fields: title, severity, type, confidence, what_was_detected, evidence, reason, possible_causes, impact, verification_steps, legal_reference.\n"
    )


def _ensure_context_cache(doc_type: str) -> str | None:
    """
    Create or refresh a Gemini context cache for the static content of this doc_type.
    Returns the cache name (e.g. "cachedContents/abc123") or None if caching fails.
    """
    try:
        import hashlib
        static_content = _build_static_content(doc_type)
        content_hash = hashlib.md5(static_content.encode("utf-8")).hexdigest()
        cache_client = _get_cache_client()

        existing = _context_caches.get(doc_type)
        if existing:
            if existing.get("hash") == content_hash:
                try:
                    # Refresh TTL on existing cache
                    cache_client.caches.update(
                        name=existing["cache_name"],
                        config={"ttl": f"{CACHE_TTL_SECONDS}s"},
                    )
                    return existing["cache_name"]
                except Exception:
                    pass
            else:
                # Delete stale cache on server
                try:
                    cache_client.caches.delete(name=existing["cache_name"])
                except Exception:
                    pass

        # Create new cache — SDK expects Content objects; wrap appropriately
        response = cache_client.caches.create(
            model=GEMINI_MODEL,
            config=types.CreateCachedContentConfig(
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=static_content)]
                    )
                ],
                ttl=f"{CACHE_TTL_SECONDS}s",
            ),
        )
        cache_name = response.name
        _context_caches[doc_type] = {
            "cache_name": cache_name,
            "hash": content_hash,
            "created_at": time.time(),
        }
        logger.info("Created context cache for %s: %s", doc_type, cache_name)
        return cache_name

    except Exception as e:
        logger.warning("Failed to create/refresh context cache for %s: %s", doc_type, e)
        return None


def _build_user_content(ocr_text: str, page_count: int, doc_type: str) -> str:
    """Build the dynamic per-document content (OCR text)."""
    return (
        f"DOCUMENT: {doc_type} ({page_count} pages)\n\n"
        f"OCR TEXT:\n{ocr_text}\n"
    )


def merge_dict_list(dict_list: list) -> dict:
    """
    Recursively merges a list of dictionaries into a single dictionary.
    - Concatenates lists.
    - Recursively merges nested dictionaries.
    - Combines primitive values (deduplicates, joins strings with comma, etc.).
    """
    if not dict_list:
        return {}
    
    if not all(isinstance(x, dict) for x in dict_list):
        non_null = [x for x in dict_list if x is not None]
        if not non_null:
            return None
        seen = []
        for x in non_null:
            if x not in seen:
                seen.append(x)
        if len(seen) == 1:
            return seen[0]
        return seen

    merged = {}
    all_keys = set()
    for d in dict_list:
        all_keys.update(d.keys())

    for key in all_keys:
        values = [d[key] for d in dict_list if key in d]
        non_null_values = [v for v in values if v is not None]
        
        if not non_null_values:
            merged[key] = None
            continue

        if all(isinstance(v, list) for v in non_null_values):
            combined_list = []
            for lst in non_null_values:
                combined_list.extend(lst)
            merged[key] = combined_list
        elif all(isinstance(v, dict) for v in non_null_values):
            merged[key] = merge_dict_list(non_null_values)
        else:
            unique_vals = []
            for v in non_null_values:
                if v not in unique_vals:
                    unique_vals.append(v)
            
            if len(unique_vals) == 1:
                merged[key] = unique_vals[0]
            else:
                if all(isinstance(v, bool) for v in unique_vals):
                    merged[key] = any(unique_vals)
                else:
                    str_vals = [str(v) for v in unique_vals if str(v).strip()]
                    merged[key] = ", ".join(str_vals)
                    
    return merged


# ── Per-document structuring + verification ────────────────────────────────

def structure_document_with_gemini(merged_ocr: dict, doc_type: str,
                                    retry_count: int = 0) -> dict:
    """
    Extract structured fields AND generate verification notes in a single LLM call.
    Every check — extraction AND verification, including arithmetic/date checks — is
    performed by the LLM per the instructions in _get_verification_instructions(); there
    is no separate Python-side deterministic check layer. Uses system_instruction for
    static content + context caching for cost reduction.
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

        config_kwargs = {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": 65536,
        }

        if cache_name:
            # Reference the cached content so Gemini bills at cached-content rates
            config_kwargs["cached_content"] = cache_name

        safe_kwargs = {k: v for k, v in config_kwargs.items() if k != "cached_content"}
        gen_config = types.GenerateContentConfig(
            system_instruction=static_content,
            **safe_kwargs,
        )

        if cache_name:
            # cached_content is passed at the config level in newer google-genai SDK
            gen_config.cached_content = cache_name

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

    raw_response = response.text

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

    llm_notes = result.pop("verification_notes", [])
    for n in llm_notes:
        n.setdefault("source", "llm")

    if "file_metadata" in result and page_count:
        result["file_metadata"]["scanned_sheet_count"] = page_count

    verification_notes = llm_notes

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
        "verification_notes": verification_notes,
        "_analytics": analytics,
    }


def _get_verification_instructions(doc_type: str) -> str:
    base = (
        "WHILE EXTRACTING, check for these issues and add them to verification_notes, "
        "following the OUTPUT QUALITY CONTRACT above exactly — every check below is a "
        "CROSS-FIELD comparison within this one document; cite both sides of the "
        "comparison with real values in 'evidence'.\n"
    )

    sale_deed_checks = (
        "SALE_DEED EXTRACTION NOTE: in addition to the schema's top-level fields, extract "
        "financial_summary.payment_breakdown as one entry PER payment mentioned in the "
        "'DETAILS OF PAYMENT'/payment section — e.g. a pay order/DD entry and a separate "
        "cash entry are TWO entries, each with its own amount and mode ('cash', 'cheque', "
        "'dd', 'pay_order', 'rtgs/neft', 'bank_transfer'). Also extract "
        "property_schedule.measurements.dimensions_text as the raw dimension string if the "
        "schedule states one (e.g. \"30' X 40'\"), verbatim, alongside the numeric area.\n\n"
        "SALE_DEED VERIFICATION CHECKS (compare these fields against each other and cite "
        "real values for both sides):\n"
        "- Are both vendors AND purchasers actually named (not just placeholders)?\n"
        "- Is survey_number or cts_number present and does it look like a real survey "
        "  number format (not a placeholder like '0' or 'NA')? If the survey number includes "
        "  a sub-division marker like 'Paiki'/'Part of' (indicating the parent survey number "
        "  is split among multiple owners), note this explicitly — it's relevant to the "
        "  cross-document over-sale check described below.\n"
        "- Compare statutory_valuation_endorsement.estimated_market_value against "
        "  financial_summary.declared_consideration_amount. If consideration is below "
        "  market value AND prevention_of_undervaluation_referred is false/null, flag "
        "  GUIDANCE_VALUE_ISSUE citing both numbers and the percentage shortfall.\n"
        "- If property_schedule.full_schedule_description or intended_usage mentions "
        "  'agricultural'/'farm'/'cultivation' in the SCHEDULE OF PROPERTY itself (not in "
        "  a party's address or a road name used only for location), flag CONVERSION_MISSING "
        "  and quote the exact phrase found. If a conversion order IS cited (order number + "
        "  date), quote it but note in 'suggestion' that the underlying order copy should be "
        "  independently obtained from the Deputy Commissioner's office — a cited order "
        "  number is not, by itself, proof the order is genuine or actually covers this land.\n"
        "- Count witnesses if listed elsewhere in the OCR; if fewer than 2, flag "
        "  MISSING_DOCUMENT/SUSPICIOUS_PATTERN citing how many were found.\n"
        "- Does the OCR reference a prior encumbrance/mortgage on this property without a "
        "  corresponding release shown anywhere in this same document? If so, flag "
        "  PENDING_MORTGAGE and quote the referencing sentence.\n"
        "- FRAUD PATTERN — execution via Power of Attorney: if 'represented_by' is populated "
        "  for the vendor (i.e. someone signed on the seller's behalf under a POA rather than "
        "  the owner personally), flag SUSPICIOUS_PATTERN at medium-high severity. Quote the "
        "  POA holder's name and note: under Suraj Lamp & Industries Pvt. Ltd. v. State of "
        "  Haryana (Supreme Court, 2011/2012), a sale executed merely under a General Power "
        "  of Attorney — without the principal also executing a registered conveyance — does "
        "  not by itself transfer valid title; the POA's own registration, validity, and the "
        "  principal's status at the time of use must be independently verified.\n"
        "- FRAUD PATTERN — impersonation risk: Karnataka's registration process requires a "
        "  photograph and biometric thumb-impression of each executant to be captured at "
        "  registration (introduced specifically to curb impersonation of absentee/NRI "
        "  owners). If the OCR text gives no indication that a photo/thumb-impression "
        "  annexure exists anywhere in the document set (look for endorsement language "
        "  referencing photograph/thumb impression capture), flag MISSING_DOCUMENT at medium "
        "  severity noting this annexure could not be confirmed from the text alone.\n"
        "- COMPUTE — date ordering: compare file_metadata.execution_date and "
        "  file_metadata.registration_date. Under Section 23/32, Registration Act, 1908, "
        "  execution must precede registration. If execution_date is AFTER "
        "  registration_date, flag DATE_INCONSISTENCY at high severity, quoting both dates "
        "  verbatim in evidence.\n"
        "- COMPUTE — stamp duty ratio: divide financial_summary.stamp_duty_paid_amount by "
        "  financial_summary.declared_consideration_amount and multiply by 100. SHOW this "
        "  division as text in 'evidence' (e.g. '168000 / 2500000 x 100 = 6.72%'). Karnataka's "
        f"  typical effective band is roughly {STAMP_DUTY_PCT_MIN}%-{STAMP_DUTY_PCT_MAX}% "
        "  depending on slab/surcharge/concession. If the computed ratio falls outside that "
        "  band, flag FINANCIAL_MISMATCH at medium severity; if within the band, do NOT "
        "  report anything for this check (passing checks should be silent).\n"
        "- COMPUTE — cash payment / Section 269SS: scan financial_summary.payment_breakdown "
        "  for any entry whose mode is 'cash' (not cheque/DD/pay order/RTGS/NEFT/bank "
        f"  transfer). If a cash entry's amount is >= ₹{CASH_PAYMENT_269SS_THRESHOLD:,}, flag "
        "  SUSPICIOUS_PATTERN at HIGH severity citing Section 269SS of the Income Tax Act, "
        "  1961 (cash receipts of ₹20,000+ toward an immovable property transfer are "
        "  prohibited; violation attracts a penalty under Section 271D equal to the amount "
        "  received). Quote the exact cash amount and what fraction of the total declared "
        "  consideration it represents (show the division, e.g. '900000 / 2500000 = 36%').\n"
        "- COMPUTE — dimension-vs-area math: if property_schedule.measurements."
        "  dimensions_text contains a 'LENGTH x WIDTH' pattern (e.g. \"30' X 40'\"), multiply "
        "  the two numbers and SHOW the multiplication in evidence (e.g. '30 x 40 = 1200'). "
        "  Compare that product to the declared area field (super_built_up_area_sqft or "
        "  undivided_share_land_sqft, whichever is populated). If they differ by more than "
        "  ~5%, flag PROPERTY_MISMATCH at medium severity, showing both the computed product "
        "  and the declared area. If they match, do NOT report anything for this check.\n"
    )

    ec_checks = (
        "ENCUMBRANCE_CERTIFICATE VERIFICATION & EXTRACTION CHECKS:\n"
        "- IMPORTANT — EXTRACT EVERY TRANSACTION: Scan the entire document from start to "
        "  finish. Extract ALL transactions in the EC ledger into historical_ledger. Do "
        "  not skip or summarize any row.\n"
        "  KEY EXTRACTION RULES:\n"
        "    a) Merge rows across all pages into one historical_ledger array.\n"
        "    b) Multi-row transaction: if a row has no date but contains data, append it "
        "       to the previous transaction rather than treating it as a new one.\n"
        "    c) Older ECs: handle 7-column formats where volume/page/references are "
        "       combined into a single cell.\n"
        "    d) Deduplicate: if the same transaction_index+date+reference appears more "
        "       than once (e.g. repeated across page breaks), keep only one copy.\n"
        "    e) PROPERTY DESCRIPTION BOUNDARIES WARNING: in the '(ಎ) ಆಸ್ತಿ ವಿವರ' (Property "
        "       Description) column, isolate the actual boundary sub-fields (North/East/"
        "       West/South). A survey number that appears only as a BOUNDARY landmark "
        "       (e.g. 'East: R.S.No. 694') belongs to an adjacent property, not the "
        "       transaction's own parent survey number — do not treat it as a mismatch.\n"
        "    f) DEFAULT PARENT SURVEY RULE: if a row matches the target plot/CTS number "
        "       and does not explicitly state a different parent survey for the main "
        "       property (e.g. it doesn't say 'out of R S No 677' or 'comprised in RS No "
        "       697/1'), assume it belongs to the target parent survey number and extract "
        "       it as such.\n\n"
        "  LLM-LEVEL LEGAL & VERIFICATION CHECKS — perform ALL of these yourself, there is "
        "  no separate code-side checking layer. Show all mathematical or subtraction computations "
        "  verbatim inside the 'evidence' field:\n\n"
        "  CHECK 1 — RELEVANCE FILTER (do this FIRST, before any chain-of-title check):\n"
        "    Compare each row's parent_survey_number_raw + locality_raw against the EC's own "
        "    search_criteria.target_identifiers (cts_number, survey_number, converted_survey_number, "
        "    plot_number) and target_village/target_hobli. A row that shares only the Plot No. "
        "    but has a different survey number AND a different locality than the target is "
        "    almost certainly an unrelated property swept in by a landmark-based search — "
        "    explicitly mark it 'not part of target chain' in your reasoning and EXCLUDE it "
        "    from checks 2-9 below. If a row's survey number is ambiguous or partially "
        "    overlapping (e.g. shares one digit, or is a sub-division of the target survey "
        "    number), say so explicitly and treat it as uncertain rather than silently including "
        "    or excluding it — flag PROPERTY_MISMATCH at low/medium severity recommending "
        "    manual confirmation rather than guessing.\n\n"
        "  CHECK 2 — CHAIN OF TITLE CONTINUITY (only on rows that passed Check 1):\n"
        "    Sort the relevant rows by execution_date. For each consecutive pair, the purchaser(s) "
        "    of the earlier row should be the vendor(s) of the later row (allowing for natural "
        "    changes like marriage-name updates, gift/inheritance within family, or GPA "
        "    representation of the same person). If a later row's vendor is NOT the same as — or "
        "    traceable to — the prior row's purchaser, with no transaction explaining the change, "
        "    flag this as a serious chain break: PROPERTY_MISMATCH or SUSPICIOUS_PATTERN at "
        "    HIGH severity, naming both rows, both party sets, and the gap.\n\n"
        "  CHECK 3 — DOUBLE-SALE / UNDISCLOSED PRIOR CONVEYANCE:\n"
        "    For every pair of rows (A, B) on the SAME relevant chain where A is earlier than B: "
        "    if A conveyed a partial interest (share_fraction is non-null, e.g. '1/2') or a partial "
        "    extent, and B — by the SAME vendor as A, or a vendor claiming full unencumbered "
        "    ownership — later conveys the WHOLE property with no row between A and B that "
        "    cancels/reconveys/releases A's share back, flag SUSPICIOUS_PATTERN at HIGH severity. "
        "    Name both rows' dates, parties, share/extent conveyed, and consideration, and state "
        "    explicitly: 'no intervening row undoes [A's] conveyance; confirm the current status "
        "    of [A's purchaser]'s share before relying on [B] as proof of full, unencumbered "
        "    ownership.' Apply this check also when row A conveys the full extent to party X and "
        "    row B (no intervening undoing row) later has a DIFFERENT vendor purporting to sell "
        "    the same property as if A never happened.\n\n"
        "  CHECK 4 — AGREEMENT-TO-SELL RESOLUTION TRACKING:\n"
        "    For every row where is_agreement_to_sell is true, look for EITHER: (a) a LATER row, "
        "    same parties (vendor -> that agreement's purchaser), that is an actual Sale/Conveyance "
        "    (completing the agreement), OR (b) a LATER row that is a Cancellation Deed/Reconveyance "
        "    between the same parties (terminating the agreement). If NEITHER exists anywhere "
        "    later in the ledger, flag MISSING_DOCUMENT or SUSPICIOUS_PATTERN at MEDIUM severity: "
        "    name the agreement's date/parties/amount and state that an unresolved agreement to "
        "    sell does not itself transfer title (Section 54, Transfer of Property Act) but a "
        "    purchaser who has paid and taken steps in reliance on it may have a part-performance "
        "    claim under Section 53A — so it should be confirmed as abandoned/settled before "
        "    treating the property as clear.\n\n"
        "  CHECK 5 — MORTGAGE / CHARGE RELEASE MATCHING:\n"
        "    Treat ALL of the following transaction_type values as creating a charge that must "
        "    later be released: 'Mortgage without Possession', 'Mortgage with Possession', "
        "    'Simple Mortgage', 'English Mortgage', 'Usufructuary Mortgage', 'Mortgage by "
        "    Conditional Sale', and 'DTD' / 'Deposit of Title Deeds' (an equitable mortgage under "
        "    Section 58(f), Transfer of Property Act). For each such row, look for a LATER row "
        "    of type 'Release Deed' or 'Reconveyance' naming the same parties/property. If none "
        "    exists, flag PENDING_MORTGAGE at HIGH severity, quoting the row's date, type, "
        "    parties, and amount.\n\n"
        "  CHECK 6 — GPA-EXECUTED TRANSACTION VALIDATION:\n"
        "    For every row where the vendor/executant is described as a GPA holder ('Rep'd by "
        "    GPA Holder', 'Authorized Signatory' under POA, etc.), check whether the named "
        "    PRINCIPAL (the actual owner the POA holder claims to represent) matches who the "
        "    chain-of-title (Check 2) shows as the rightful owner at that point. If the "
        "    principal's name doesn't match — or can't be confirmed from earlier rows — flag "
        "    SUSPICIOUS_PATTERN at HIGH severity, citing Suraj Lamp & Industries Pvt. Ltd. v. "
        "    State of Haryana (Supreme Court, 2011/2012): a transfer executed merely under a "
        "    General Power of Attorney does not itself convey valid title; the POA's registration, "
        "    continued validity, and the principal's status must be independently verified.\n\n"
        "  CHECK 7 — SAME NAME ON BOTH SIDES OF ONE TRANSACTION:\n"
        "    If any individual or set of named principals appears in BOTH the 'vendors'/executants "
        "    list AND the 'purchasers'/claimants list of the SAME row (even through different GPA "
        "    holders representing them on each side), flag SUSPICIOUS_PATTERN at MEDIUM severity "
        "    and quote both occurrences — this could be partition, data overlap, or a sham transaction.\n\n"
        "  CHECK 8 — UNDERVALUATION / TOKEN CONSIDERATION:\n"
        "    For every row where BOTH market_value and consideration_amount are present and "
        "    non-zero, divide consideration by market value and show the computation. If "
        "    consideration is substantially below market value (below 70-75% of market value), "
        "    flag GUIDANCE_VALUE_ISSUE at MEDIUM severity. Separately: if a row's transaction_type "
        "    is something that should normally involve real payment (e.g. 'Sale') but "
        "    consideration_amount is 0, Rs 1, or another token amount, flag SUSPICIOUS_PATTERN "
        "    at MEDIUM severity (nil/token consideration is NORMAL and should NOT be flagged for "
        "    Gift Deed, Release Deed, Cancellation Deed, or Reconveyance article types).\n\n"
        "  CHECK 9 — MINOR / LEGAL HEIR PARTY VALIDATION:\n"
        "    For every row where minor_or_legal_heir_party is true: if a minor's interest is "
        "    being conveyed (sold/mortgaged) by a natural guardian, flag MISSING_DOCUMENT at "
        "    MEDIUM severity noting that under Section 8, Hindu Minority and Guardianship Act, "
        "    1956, a natural guardian needs prior permission of the court to transfer a minor's "
        "    immovable property. If parties are described as 'legal heirs of [deceased],' check "
        "    whether the row appears to list ALL heirs; if only some heirs appear to be party to "
        "    a transaction affecting the whole property, flag MISSING_DOCUMENT at medium severity "
        "    recommending a succession certificate / legal heir certificate be obtained.\n\n"
        f"  CHECK 10 — SEARCH WINDOW & GAPS (apply only within the relevant chain identified in Check 1):\n"
        f"    Read or compute file_metadata.search_period_years. If under {EC_MIN_SEARCH_YEARS} years, "
        f"    flag EC_GAP at high severity. Sort the relevant chain rows by date and check for "
        f"    gaps exceeding {EC_GAP_FLAG_YEARS} years between consecutive entries; if found, flag "
        f"    EC_GAP at medium severity, showing the subtraction (e.g. '2015 - 1998 = 17 years') "
        "    and naming the two rows/dates either side of the gap. Do NOT compute this gap check "
        "    across irrelevant rows excluded by Check 1.\n\n"
        "  ARTICLE-TYPE REFERENCE TABLE:\n"
        "  Use the following lookup matrix to apply the correct checks based on row transaction_type/article:\n"
        "  | Article Name (as seen in Karnataka ECs)        | What must be checked                                                                 |\n"
        "  |-------------------------------------------------|----------------------------------------------------------------------------------------|\n"
        "  | Sale / Sale-Conveyance                          | Checks 2, 3, 6, 7, 8                                                                   |\n"
        "  | Agreement of Sale (possession given/not given)  | Check 4 (resolution tracking); do not treat as a transfer of title by itself           |\n"
        "  | Gift Deed                                       | Checks 2, 6, 7; consideration of 0 is normal, do not flag under Check 8                |\n"
        "  | Mortgage with/without Possession, Simple/English/Usufructuary Mortgage, Mortgage by Conditional Sale | Check 5 (release matching)                                  |\n"
        "  | DTD (Deposit of Title Deeds)                    | Check 5 — treat identically to a registered mortgage (Section 58(f), TPA)             |\n"
        "  | Release Deed                                    | Should be matched AS the resolution for an earlier mortgage/DTD/agreement row (Checks 4, 5) — if it doesn't match anything earlier, note that explicitly |\n"
        "  | Reconveyance                                    | Same as Release Deed — confirm it matches an earlier mortgage/agreement row            |\n"
        "  | Cancellation Deed                                | Confirm it matches and fully undoes an earlier row between the same parties (Check 3, 4)|\n"
        "  | Lease of Immovable Property                     | Note the lessee and term if stated — relevant for vacant-possession due diligence, not itself an encumbrance on title |\n"
        "  | Mortgage / DTD where mortgagor includes a GPA holder or a name not matching the registered owner | Checks 5 AND 6 together                                          |\n"
        "  | Partition Deed (if present)                     | Check that all co-sharers named in the partition match the full set of owners from the prior chain |\n"
        "  | Will / Succession Certificate / Court Decree (if present) | Apply Check 9's heir-completeness logic                                       |\n\n"
        "  NON-NEGOTIABLE TEST CASE — CRITICAL DOUBLE-SALE FAILURE MODE:\n"
        "  If the ledger contains a sequence like:\n"
        "    - Row A: vendor sells a fractional share (e.g. 1/2 undivided common share) of the property to purchaser X\n"
        "    - Row B (later): the same vendor sells the WHOLE property to purchaser Y as unencumbered, with no intermediate cancellation deed\n"
        "  You MUST raise a high-severity SUSPICIOUS_PATTERN or PROPERTY_MISMATCH note. Quote both row numbers, dates, parties, and the conflict explicitly.\n"
        "- If 'Nil Encumbrance' is stated, set historical_ledger to [] and skip checks "
        "  1, 2, 4, 5, 6, 7, 8, 9 above (there's nothing to compare) — but still run check 10 "
        "  (search window length), since that applies regardless of ledger content.\n"
    )

    prc_checks = (
        "PROPERTY_REGISTER_CARD VERIFICATION CHECKS:\n"
        "- Is city_survey_number present and does it match the format/value referenced "
        "  elsewhere in the OCR (e.g. in a guidance value order)? Quote both if they differ.\n"
        "- Are holders listed with full names, or is a holder slot blank/illegible where "
        "  the layout clearly expects a name?\n"
        "- Is a lessee recorded? If so, quote the lessee details — a lessee with "
        "  cultivation/possession rights matters for vacant-possession due diligence.\n"
        "- Are easements or other_encumbrances recorded? Quote them verbatim if present.\n"
        "- Is guidance_value.value present? If null, flag GUIDANCE_VALUE_ISSUE naming "
        "  exactly which downstream check (stamp duty adequacy) becomes impossible without it.\n"
        "- RESTRICTED TENURE: Check the tenure / classification field. Standard tenure should "
        "  be Freehold/Patta. If tenure is Government, Leasehold, Inam, or any restricted/service "
        "  category, flag PROPERTY_MISMATCH at HIGH severity noting transfer of ownership is restricted.\n"
        "- UN-ATTESTED MUTATION: For each mutation entry inside mutation_or_transaction_entries, "
        "  verify if the attestation field is populated. If it is blank/null, flag MUTATION_PENDING "
        "  at MEDIUM severity, quoting the transaction name and date.\n"
        "- Is area_sq_meters a plausible number for the stated property type (not zero, "
        "  not absurdly large)?\n"
    )

    tax_checks = (
        "PROPERTY_TAX_ASSESSMENT / E_PAYMENT_RECEIPT VERIFICATION CHECKS:\n"
        "- IMPORTANT — TAX TABLE: numbered rows are typically 1-44. Common mapping: "
        "  1=owner, 2=occupier, 4=assessment_year, 5=ward, 8=site_area, "
        "  16(A)=land_market_value, 16(B)=50% value, 24=plinth_area, 30=usage, "
        "  34/36=property_tax_payable, 43=total, 44=payment_mode. Capture sub-parts like "
        "  16(A)/16(B) as separate assessment_rows entries, don't merge them.\n"
        "- Identify CHALLAN COPIES separately from the main assessment_rows table.\n"
        "- Is owner_name present and is it a real name (not a template placeholder)?\n"
        "- Is pid present and does it match the format used elsewhere in this same document "
        "  (e.g. consumer_details.pid vs property_owner.pid)? Quote both if they differ.\n"
        "- TAX DEFAULT: Is transaction_details.status (or equivalent) a clear success/paid state? "
        "  If it reads as failed, pending, or anything other than success, flag TAX_DEFAULT "
        "  at HIGH severity quoting the exact status text.\n"
        "- Is assessment_year recent relative to today, or several years stale? Quote the "
        "  actual year found.\n"
    )

    gift_deed_checks = (
        "GIFT_DEED VERIFICATION CHECKS:\n"
        "- Are both donors AND donees named with real names (not blank/placeholder)?\n"
        "- Is parties.relationship_between_parties stated, and is it a close-family "
        "  relation (parent/child/spouse/sibling)? If the stated relationship is distant "
        "  or absent, quote what's actually written — this affects whether a concessional "
        "  gift-deed stamp duty rate properly applies. If the relationship is not family (or is "
        "  unspecified/absent) and financial_summary.stamp_duty_amount is less than 5% of "
        "  the estimated market value, flag FINANCIAL_MISMATCH at HIGH severity.\n"
        "- Is survey_number or cts_number present and does it match the value, if any, "
        "  referenced elsewhere in the same document (e.g. in the building description)?\n"
        "- COMPULSORY REGISTRATION: Is file_metadata.registration_number present? Under Section 17, "
        "  Registration Act, 1908, gift deeds of immovable property must be registered. "
        "  If genuinely absent, quote 'not found' and flag MISSING_DOCUMENT at HIGH severity.\n"
        "- WITNESS ATTESTATION: Are witnesses listed? Section 123 of the Transfer of Property "
        "  Act, 1882 requires a gift deed of immovable property to be attested by at least two "
        "  witnesses. If fewer than two witnesses are found, flag MISSING_DOCUMENT at HIGH severity "
        "  quoting the count of witnesses found.\n"
        "- Is financial_summary.stamp_duty_amount populated and non-zero?\n"
        "- COMPUTE — date ordering: compare file_metadata.execution_date and "
        "  file_metadata.registration_date. Execution must precede registration under "
        "  Section 23/32, Registration Act, 1908. If execution_date is AFTER "
        "  registration_date, flag DATE_INCONSISTENCY at high severity, quoting both dates "
        "  verbatim in evidence. If execution_date is before or equal to registration_date, "
        "  do NOT report anything for this check.\n"
    )

    mutation_checks = (
        "MUTATION REGISTER EXTRACTION & VERIFICATION CHECKS:\n"
        "- Extract all rows of transaction_details representing division/mutation of survey numbers.\n"
        "- Check attestation: Verify if the mutation is attested (signed and dated by a Tahsildar / Revenue Inspector). "
        "  If the attestation date, sign, or status is blank, null, or 'unattested', flag MUTATION_PENDING at "
        "  HIGH severity, quoting the mutation number in evidence.\n"
        "- Verify survey number: Check if the target survey number is present and matches the partition details.\n"
    )

    conversion_checks = (
        "CONVERSION_ORDER (NA Conversion Order) VERIFICATION CHECKS:\n"
        "- Extract order number, date, converted survey number, and converted extent.\n"
        "- Scan for the converted purpose: check if the land is converted for 'Residential', 'Apartment - Residential', "
        "  'Commercial', or 'Industrial'. If the target land use (e.g. building an apartment) differs from the "
        "  converted purpose (e.g. converted for agricultural/industrial), flag PROPERTY_MISMATCH at HIGH severity.\n"
        "- Scan for conditions: check if the order mentions conditions like road margin, buffer zones, or layout plan approvals. "
        "  Note in suggestions that layout plans must be approved by Town Planning Authority.\n"
        "- Ensure that the order number and date are cited in the findings, recommending that a certified copy be obtained from the DC Office.\n"
    )

    rtc_checks = (
        "RTC_PAHANI (Pahani / Form 16) VERIFICATION CHECKS:\n"
        "- Extract survey number, total extent, kharab land, net area, owners list (Column 9), liabilities (Column 11), and crops/cultivators (Column 12).\n"
        "- Check document recency: check the assessment year or print date. If it is older than 1 year (e.g. from a prior financial year), "
        "  flag DOCUMENT_EXPIRY at medium-low severity.\n"
        "- Check for liabilities: scan column 11/12/15 (other rights and liabilities) for any entries of bank mortgages, hypothecation, "
        "  outstanding loans, court injunctions, or family disputes. If any bank name or loan amount is found, flag PENDING_MORTGAGE "
        "  at HIGH severity, quoting the exact bank name and loan reference from the text.\n"
        "- Check for agricultural tenancy: if Column 12 (cultivator details) lists any individual other than the registered owners "
        "  as cultivator with tenancy rights, flag SUSPICIOUS_PATTERN at medium-high severity.\n"
        "- COMPUTE - Area consistency: add the net area and kharab area (A + B). If this sum differs from the total extent by more than 1%, "
        "  flag PROPERTY_MISMATCH at medium severity, showing the math (e.g., 'net + kharab != total').\n"
    )

    cdp_checks = (
        "CDP_PLAN (Comprehensive Development Plan / Zoning Plan) VERIFICATION CHECKS:\n"
        "- Extract zoning classification (e.g., Residential, Commercial, Agricultural, Green Belt, Forest, Buffer Zone).\n"
        "- Zoning restriction check: If the zoning classification is 'Agricultural', 'Green Belt', 'Forest', or 'Buffer Zone', "
        "  but the target usage of the property is residential or commercial, flag PROPERTY_MISMATCH at HIGH severity. "
        "  State that development in restricted zones violates the Karnataka Town and Country Planning (KTCP) Act.\n"
        "- Check road width: if road width is listed, extract it.\n"
    )

    generic_checks = (
        "GENERIC DOCUMENT VERIFICATION CHECKS:\n"
        "- What type of document does this actually appear to be, based on its content?\n"
        "- Is there a document number, date, or issuing authority you can quote verbatim?\n"
        "- Does it reference a specific, quotable property identifier (survey/CTS/PID/plot)?\n"
        "- Does it reference specific, quotable person/party names?\n"
        "- Any apparent inconsistencies between two parts of THIS SAME document? Quote both sides.\n"
    )

    checks = {
        "SALE_DEED": sale_deed_checks,
        "ENCUMBRANCE_CERTIFICATE": ec_checks,
        "PROPERTY_REGISTER_CARD": prc_checks,
        "E_PAYMENT_RECEIPT": tax_checks,
        "PROPERTY_TAX_ASSESSMENT": tax_checks,
        "TAX_RECEIPT": tax_checks,
        "GIFT_DEED": gift_deed_checks,
        "MUTATION": mutation_checks,
        "CONVERSION_ORDER": conversion_checks,
        "RTC_PAHANI": rtc_checks,
        "CDP_PLAN": cdp_checks,
    }

    return base + checks.get(doc_type, generic_checks)


def _generic_schema(doc_type: str) -> dict:
    schema = deepcopy(GENERIC_SCHEMA_TEMPLATE)
    schema["document_type"] = doc_type
    return schema
