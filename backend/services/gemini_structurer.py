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


PARTITION_DEED_SCHEMA = {
    "document_type": "PARTITION_DEED",
    "file_metadata": {
        "registration_number": None,
        "document_number": None,
        "book_number": None,
        "cd_number": None,
        "execution_date": None,
        "registration_date": None,
        "registration_time": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
        "drafted_by": None,
    },
    "financial_summary": {
        "stamp_duty_paid_amount": None,
        "stamp_duty_payment_mode": None,
        "stamp_duty_certificate_reference": None,
        "stamp_duty_certificate_date": None,
        "registration_fee": None,
        "scanning_fee": None,
        "conversion_fee": None,
        "scrutiny_fee": None,
        "total_other_fees": None,
        "payment_breakdown": [
            {"amount": None, "mode": None, "instrument_reference": None, "instrument_date": None, "bank_branch": None}
        ],
    },
    "parties": {
        "coparceners": [{"entity_name": None, "age": None, "occupation": None, "address": None, "party_number": None}],
    },
    "property_schedule_a": {
        "survey_number": None,
        "cts_number": None,
        "municipal_number": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions_text": None,
            "total_land_area_sqyds": None,
            "total_land_area_sqft": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "property_address": None,
    },
    "allocated_schedules": [
        {
            "schedule_name": None,
            "allocated_to_party_name": None,
            "survey_number": None,
            "cts_number": None,
            "municipal_number": None,
            "full_schedule_description": None,
            "measurements": {
                "dimensions_text": None,
                "total_land_area_sqyds": None,
                "total_land_area_sqft": None,
                "built_up_area_sqft": None,
            },
            "boundaries": {"north": None, "east": None, "west": None, "south": None},
            "property_address": None,
        }
    ],
    "witnesses": [{"name": None, "address": None}],
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

RERA_CERTIFICATE_SCHEMA = {
    "document_type": "RERA_CERTIFICATE",
    "file_metadata": {
        "registration_number": None,
        "acknowledgement_number": None,
        "acknowledgement_date": None,
        "approval_date": None,
        "expiry_date": None,
        "issuing_authority": None,
    },
    "project_details": {
        "project_name": None,
        "promoter_name": None,
        "project_address": None,
        "survey_numbers": [],
        "cts_numbers": [],
        "plots_covered": [],
        "locality": None,
    },
    "promoter_details": {
        "registered_office_address": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

LITIGATION_AFFIDAVIT_SCHEMA = {
    "document_type": "LITIGATION_AFFIDAVIT",
    "file_metadata": {
        "stamp_certificate_number": None,
        "stamp_certificate_date": None,
        "stamp_duty_amount": None,
        "notary_name": None,
        "notary_exp_date": None,
        "notary_reg_number": None,
        "deponent_name": None,
    },
    "project_details": {
        "project_name": None,
        "promoter_name": None,
        "survey_number": None,
        "cts_number": None,
        "plot_number": None,
        "total_area_sq_meters": None,
    },
    "declaration_details": {
        "is_free_from_encumbrances": None,
        "no_claims_or_litigations": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

ALLOTMENT_LETTER_SCHEMA = {
    "document_type": "ALLOTMENT_LETTER",
    "file_metadata": {
        "letter_number": None,
        "letter_date": None,
        "rera_registration_number": None,
    },
    "allotment_details": {
        "project_name": None,
        "promoter_name": None,
        "allottee_name": None,
        "unit_number": None,
        "floor_number": None,
        "wing_or_block": None,
        "carpet_area_sq_mts": None,
        "carpet_area_sq_ft": None,
        "parking_allotted": None,
        "parking_details": None,
        "project_address": None,
        "survey_numbers": [],
        "cts_numbers": [],
        "plots_covered": [],
    },
    "financial_details": {
        "total_consideration_amount": None,
        "booking_amount_received": None,
        "booking_amount_pct": None,
        "booking_payment_date": None,
    },
    "possession_date": None,
    **VERIFICATION_NOTES_SCHEMA,
}

BUILDING_LICENSE_SCHEMA = {
    "document_type": "BUILDING_LICENSE",
    "file_metadata": {
        "license_number": None,
        "license_date": None,
        "application_number": None,
        "application_date": None,
        "issuing_authority": None,
        "valid_from": None,
        "valid_to": None,
    },
    "property_details": {
        "owner_name": None,
        "survey_number": None,
        "cts_number": None,
        "site_number": None,
        "plot_area_sq_meters": None,
        "far_approved": None,
        "boundaries": {
            "east": None,
            "west": None,
            "north": None,
            "south": None,
        },
    },
    "building_specifications": {
        "floors": [
            {"floor_name": None, "use": None, "area_sq_meters": None}
        ],
        "total_built_up_area_sq_meters": None,
    },
    "financial_details": {
        "total_fee_paid": None,
        "receipt_number": None,
        "receipt_date": None,
    },
    **VERIFICATION_NOTES_SCHEMA,
}

COMPLETION_CERTIFICATE_SCHEMA = {
    "document_type": "COMPLETION_CERTIFICATE",
    "file_metadata": {
        "certificate_number": None,
        "certificate_date": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
    },
    "application_details": {
        "applicant_name": None,
        "application_date": None,
        "building_permission_letter_reference": None,
        "building_permission_letter_date": None,
    },
    "inspection_details": {
        "inspected_by": None,
        "inspection_date": None,
    },
    "property_details": {
        "survey_number": None,
        "cts_number": None,
        "location": None,
        "supervising_architect_engineer": None,
        "fit_for_occupation_floors": [],
        "intended_use": None,
    },
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
    "RERA_CERTIFICATE": RERA_CERTIFICATE_SCHEMA,
    "LITIGATION_AFFIDAVIT": LITIGATION_AFFIDAVIT_SCHEMA,
    "ALLOTMENT_LETTER": ALLOTMENT_LETTER_SCHEMA,
    "BUILDING_LICENSE": BUILDING_LICENSE_SCHEMA,
    "PARTITION_DEED": PARTITION_DEED_SCHEMA,
    "COMPLETION_CERTIFICATE": COMPLETION_CERTIFICATE_SCHEMA,
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
You are a Karnataka property-document extraction and verification engine.

TASK
1. Extract information from the OCR text into the provided JSON schema.
2. Perform only the document-specific verification checks provided below.
3. Record detected issues in verification_notes.

EXTRACTION RULES
- Use only information supported by the document. Never infer or invent missing values.
- Preserve names, identifiers, survey/CTS/hissa numbers, registration numbers, and monetary values accurately.
- Use null for unavailable scalar fields and [] for unavailable lists.
- Return dates as YYYY-MM-DD. If only month and year are explicitly available, use YYYY-MM-01.
- Return numbers as numeric values, not formatted strings.
- Extract all relevant repeated records or transactions, not only the first.
- When Kannada and English represent the same value, prefer the English equivalent. Do not treat normal transliteration differences as contradictions.

VERIFICATION RULES
- Verify only issues supported by this document. Do not perform cross-document comparisons.
- Report only actual issues; do not report passing checks.
- Every finding must be grounded in specific evidence from the document.
- For a mismatch or comparison, quote the actual values being compared.
- Do not use JSON paths or internal field names as evidence.
- Do not flag an issue solely because OCR text is unclear or a value is absent unless the document-specific checks explicitly require that field.
- Do not write generic legal explanations. State the practical reason and impact.
- Use legal_reference only for a concise citation when relevant.
- If no issue is found, return verification_notes as [].

FINDING QUALITY
Each verification_note must:
- have a specific title describing the actual issue;
- use an allowed severity and finding type;
- assign confidence based on evidence strength;
- state exactly what was detected;
- include human-readable evidence with the relevant values or text;
- explain why the issue matters in practical terms;
- list plausible causes only when supported or reasonably possible;
- state the practical impact;
- provide concrete verification steps.

OUTPUT
Return only valid JSON matching the provided schema exactly.

TARGET JSON SCHEMA
{schema_json}

DOCUMENT-SPECIFIC INSTRUCTIONS
{verification_instructions}
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

   
    sale_deed_checks = f""" SALE DEED

                ACCURACY
                Extract exact values from the OCR. Never guess, infer, complete, or normalize a value unless explicitly instructed. Map each value to the correct schema field based on context and labels. Preserve identifiers exactly. Use null when a value cannot be reliably determined.

                EXTRACT
                - All vendors and purchasers.
                - Every payment as a separate payment_breakdown entry: amount, mode, instrument reference/date, and bank/branch if stated.
                - Complete property schedule: survey/CTS, hissa/subdivision/Paiki/Part-of references, property number, area, intended use, boundaries, and dimensions_text verbatim.
                - Execution and registration dates separately.
                - Any market/guidance value, undervaluation reference, mortgage/encumbrance/release, conversion-order reference, POA/GPA representation, and witnesses.

                VERIFY — report only supported issues; passing checks stay silent.

                1. PARTIES: Flag if both vendor and purchaser are not identifiable, only when genuine absence can be established.

                2. PROPERTY ID: Flag if neither usable survey nor CTS number exists, or if conflicting identifiers appear. Preserve Hissa/Paiki/Part-of references; their presence alone is not an issue.

                3. DATES: If execution_date > registration_date, flag DATE_INCONSISTENCY with both dates.

                4. VALUATION: If declared consideration < stated market/guidance value and no referral/resolution is shown, flag GUIDANCE_VALUE_ISSUE with both values and percentage difference.

                5. PAYMENTS:
                - Compare identifiable payment totals with declared consideration; flag only a material unexplained difference when payment details are sufficiently complete.
                - If explicitly stated cash payment >= ₹{CASH_PAYMENT_269SS_THRESHOLD:,}, flag SUSPICIOUS_PATTERN with the exact amount.

                6. STAMP DUTY: Compute (stamp duty / consideration) × 100. If outside {STAMP_DUTY_PCT_MIN}%–{STAMP_DUTY_PCT_MAX}%, flag FINANCIAL_MISMATCH and show the calculation.

                7. AREA: For clear length × width dimensions, compute area and compare only with an equivalent declared area for the same property component/unit. If difference >5%, flag PROPERTY_MISMATCH and show the calculation. Never compare non-equivalent areas.

                8. CONVERSION: If the subject-property schedule identifies agricultural/farm/cultivation land and indicates non-agricultural use without conversion evidence, flag CONVERSION_MISSING. Ignore such words in addresses, roads, boundaries, or unrelated recitals. A cited conversion order is a reference, not proof of validity.

                9. ENCUMBRANCE: If the deed acknowledges a mortgage/encumbrance affecting the subject property without stating discharge/release, flag PENDING_MORTGAGE. Do not infer an active mortgage from historical recital language alone.

                10. POA/GPA: If a vendor executes through a representative, flag SUSPICIOUS_PATTERN for authority verification. Quote available principal, representative, and POA details. Do not claim POA execution itself invalidates the sale.

                11. WITNESSES: If an execution/attestation section is clearly present and fewer than 2 witnesses are identified, flag for verification. Do not flag solely because OCR may have missed signature pages.

                Follow the OUTPUT QUALITY CONTRACT for every finding.
                """

    ec_checks = f"""ENCUMBRANCE CERTIFICATE (EC)

            ACCURACY
            Extract exact values from the OCR. Never guess missing values. Preserve names, dates, document references, survey/CTS/plot numbers, shares, extents, transaction types, and amounts accurately.

            EXTRACT
            - Scan the entire EC and extract EVERY transaction into historical_ledger; never summarize or skip rows.
            - Merge transactions across all pages.
            - If a continuation row has no date but contains transaction data, merge it with the previous transaction.
            - Support older 7-column EC formats with combined volume/page/reference fields.
            - Deduplicate repeated rows using transaction index + date + reference.
            - Separate the subject property's identifiers from survey/CTS numbers appearing only in North/East/West/South boundary descriptions; boundary properties are not the transaction property.
            - If a row matches the target plot/CTS and does not explicitly state a different parent survey, associate it with the target parent survey.
            - If the EC explicitly states Nil Encumbrance, set historical_ledger=[].

            VERIFY
            First determine which transactions belong to the target property. Apply chain checks only to relevant or reasonably matching rows. Report only supported issues; passing checks stay silent.

            1. RELEVANCE
            Compare each row's property identifiers and locality with search_criteria target survey/CTS/converted-survey/plot number and village/hobli.
            - Exclude a row from the title chain when it matches only a plot number but has both a different survey number and different locality.
            - If identity is ambiguous, including possible subdivisions of the target survey, do not guess; flag PROPERTY_MISMATCH at low/medium severity for manual confirmation.

            2. TITLE CHAIN
            Sort relevant title-transfer rows by execution date. The earlier purchaser should be the later vendor or be traceably connected through another transaction, inheritance, family transfer, name variation, or valid representation.
            If ownership changes without an explaining transaction, flag PROPERTY_MISMATCH or SUSPICIOUS_PATTERN at HIGH severity with both rows, dates, and party sets.

            3. DOUBLE SALE / PRIOR CONVEYANCE
            Flag SUSPICIOUS_PATTERN at HIGH severity when:
            - a vendor first conveys a share/partial extent and later conveys the whole property without an intervening cancellation, reconveyance, release, or other transaction restoring that interest; or
            - the full property was already conveyed and a later unrelated vendor again purports to convey the same property without an intervening transaction explaining title.
            Quote both transactions, dates, parties, shares/extents, and consideration.

            4. AGREEMENT OF SALE
            An Agreement of Sale is not itself a title transfer. For each agreement, look later for:
            - a Sale/Conveyance completing it; or
            - a Cancellation Deed/Reconveyance terminating it.
            If neither exists, flag MISSING_DOCUMENT or SUSPICIOUS_PATTERN at MEDIUM severity with the agreement date, parties, and amount, and recommend confirming its current status.

            5. MORTGAGE / CHARGE
            Treat Mortgage with/without Possession, Simple Mortgage, English Mortgage, Usufructuary Mortgage, Mortgage by Conditional Sale, and DTD/Deposit of Title Deeds as charges.
            For each, find a later matching Release Deed or Reconveyance for the same property/obligation. If none exists, flag PENDING_MORTGAGE at HIGH severity with transaction date, type, parties, and amount.
            If a Release/Reconveyance does not match any earlier charge or agreement, note the unmatched resolution.

            6. GPA / POA TRANSACTIONS
            When a vendor/executant acts through a GPA/POA/authorized representative, verify that the represented principal matches the owner shown by the preceding title chain.
            If the principal conflicts with or cannot be traced to the owner, flag SUSPICIOUS_PATTERN at HIGH severity and require verification of the POA's authority, registration, validity, and principal's ownership. Do not treat POA representation alone as invalid.

            7. SAME PARTY ON BOTH SIDES
            If the same person/principal appears as both vendor/executant and purchaser/claimant in one transaction, including through different representatives, flag SUSPICIOUS_PATTERN at MEDIUM severity. Note that partition, extraction overlap, or another legitimate structure may explain it and requires confirmation.

            8. VALUE / CONSIDERATION
            - When market_value and consideration_amount are both non-zero, compute consideration / market value × 100. If consideration is below 70–75% of market value, flag GUIDANCE_VALUE_ISSUE at MEDIUM severity and show the calculation.
            - For transactions normally requiring consideration, such as Sale, flag zero/₹1/token consideration as SUSPICIOUS_PATTERN at MEDIUM severity.
            - Do NOT apply the token-consideration check to Gift Deed, Release Deed, Cancellation Deed, or Reconveyance.

            9. MINOR / LEGAL HEIRS
            - If a minor's property interest is sold or mortgaged through a natural guardian, flag MISSING_DOCUMENT at MEDIUM severity and require verification of necessary court permission.
            - If a transaction affecting the whole property is executed by only some apparent legal heirs, flag MISSING_DOCUMENT at MEDIUM severity and recommend verifying complete succession/legal-heir records.

            10. SEARCH COVERAGE & GAPS
            - If the EC search period is under {EC_MIN_SEARCH_YEARS} years, flag EC_GAP at HIGH severity.
            - Sort relevant transactions by date. If consecutive relevant transactions are more than {EC_GAP_FLAG_YEARS} years apart, flag EC_GAP at MEDIUM severity and show the date subtraction.
            - Never calculate transaction gaps using rows excluded as unrelated.

            TRANSACTION RULES
            - Sale/Conveyance: title-chain, double-sale, GPA, same-party, and valuation checks.
            - Agreement of Sale: resolution tracking; do not treat as title transfer.
            - Gift Deed: title-chain/GPA/same-party checks; zero consideration is normal.
            - Mortgage/DTD: require matching release/reconveyance.
            - Release Deed/Reconveyance: match to the earlier obligation it resolves.
            - Cancellation Deed: verify which earlier transaction it cancels.
            - Lease: extract lessee and term; do not treat the lease itself as a title transfer.
            - Partition Deed: verify co-sharers against the preceding ownership chain.
            - Will/Succession Certificate/Court Decree: apply succession and heir-completeness checks.

            If Nil Encumbrance is stated, keep historical_ledger=[] and perform only the EC search-coverage check.

            For every calculation, show the computation in evidence.
            Follow the OUTPUT QUALITY CONTRACT for every finding.
            """

    prc_checks = """PROPERTY REGISTER CARD (PRC)

            ACCURACY
            Extract exact OCR values; never guess. Preserve CTS numbers, holder names, tenure, area, mutation entries, lessee, easements, encumbrances and guidance value.

            VERIFY — WITHIN THIS PRC ONLY
            Report only supported issues; passing checks stay silent.

            1. PROPERTY ID: Flag conflicting city survey/CTS numbers appearing within the PRC; quote both values.

            2. HOLDERS: Flag a missing holder only when the document layout clearly contains an expected holder field that is genuinely blank/illegible.

            3. LESSEE/RIGHTS: If a lessee, easement or other encumbrance is recorded, report the exact details because they may affect possession or property rights.

            4. GUIDANCE VALUE: If guidance_value.value is absent, flag GUIDANCE_VALUE_ISSUE and state that stamp-duty adequacy cannot be assessed from this PRC.

            5. TENURE: If tenure is Government, Leasehold, Inam or another restricted/service category rather than standard Freehold/Patta, flag PROPERTY_MISMATCH, HIGH, because transfer rights may be restricted.

            6. MUTATION: For each mutation_or_transaction_entries record, if attestation is genuinely blank/null, flag MUTATION_PENDING, MEDIUM, with transaction name and date.

            7. AREA: Flag area_sq_meters only if it is zero or clearly implausible for the property described.

            Follow the OUTPUT QUALITY CONTRACT for every finding.
            """

    tax_checks = """PROPERTY TAX / PAYMENT RECEIPT

            ACCURACY
            Extract exact OCR values; never guess. Keep assessment-table rows and challan/receipt copies separate.

            EXTRACT
            - For assessment tables, extract all numbered rows. Common mapping: 1=owner, 2=occupier, 4=assessment year, 5=ward, 8=site area, 16(A)=land market value, 16(B)=50% value, 24=plinth area, 30=usage, 34/36=property tax payable, 43=total, 44=payment mode.
            - Keep sub-rows such as 16(A) and 16(B) as separate assessment_rows.
            - Extract each challan/receipt copy separately.

            VERIFY — WITHIN THIS DOCUMENT ONLY
            1. OWNER: Flag if owner_name is genuinely missing or only a template placeholder.
            2. PID: If multiple PID fields appear within this document, flag PROPERTY_MISMATCH only when their exact values conflict.
            3. PAYMENT STATUS: If status explicitly says failed, pending, unsuccessful, or another non-paid state, flag TAX_DEFAULT, HIGH, quoting the exact status. Do not flag when status is absent.
            4. RECENCY: If assessment_year is clearly stale, flag TAX_DEFAULT at low/medium severity and quote the actual year.

            Report only supported issues; passing checks stay silent.
            Follow the OUTPUT QUALITY CONTRACT.
            """
    gift_deed_checks = """GIFT DEED

            ACCURACY
            Extract exact OCR values; never guess. Preserve party names, relationship, property IDs, dates, registration details, stamp duty and witnesses.

            VERIFY — WITHIN THIS GIFT DEED ONLY
            Report only supported issues; passing checks stay silent.

            1. PARTIES: Flag if donor or donee is genuinely missing/placeholder.

            2. RELATIONSHIP & STAMP DUTY: Extract the stated donor-donee relationship. If it is non-family or unspecified AND stamp duty is below 5% of the stated estimated market value, flag FINANCIAL_MISMATCH, HIGH. Show the calculation. Do not assume a relationship not stated in the deed.

            3. PROPERTY ID: Flag conflicting survey/CTS identifiers within the deed. Do not flag merely because one identifier is absent when another valid property identifier exists.

            4. REGISTRATION: If the deed concerns immovable property and the registration number is genuinely absent from a sufficiently complete document, flag MISSING_DOCUMENT, HIGH. Do not flag solely because OCR may have missed the registration endorsement.

            5. WITNESSES: If the execution/attestation section is available and fewer than 2 witnesses are identified, flag MISSING_DOCUMENT, HIGH, with the count found. Do not flag solely because OCR may have missed signature pages.

            6. STAMP DUTY: If stamp_duty_amount is explicitly zero, flag FINANCIAL_MISMATCH. If merely missing/unreadable, do not treat it as zero.

            7. DATES: If execution_date > registration_date, flag DATE_INCONSISTENCY, HIGH, quoting both dates.

            Follow the OUTPUT QUALITY CONTRACT.
            """
    mutation_checks = """MUTATION REGISTER (MR)

            ACCURACY
            Extract exact OCR values; never guess. Extract every mutation/division row and preserve MR number, survey/hissa, area, previous/new owners, mutation reason, supporting-document reference, dates, status and attestation details.

            VERIFY — WITHIN THIS MUTATION DOCUMENT ONLY
            Report only supported issues; passing checks stay silent.

            1. MR NUMBER: If the mutation number is genuinely absent or clearly invalid, flag MUTATION_PENDING.

            2. PROPERTY: Flag conflicting survey/hissa/area values within this document. Do not compare with RTC or Sale Deed here.

            3. OWNERSHIP: Extract previous and new owners exactly. Flag only internal contradictions or genuinely missing ownership details.

            4. BASIS: Extract the mutation reason (Sale/Gift/Partition/Inheritance/Court Order/etc.) and supporting-document reference. If the basis is stated but the expected reference is genuinely absent, flag MISSING_DOCUMENT.

            5. DATES: If both supporting-document and mutation dates are present and mutation predates its supporting transaction, flag DATE_INCONSISTENCY with both dates.

            6. APPROVAL: If the mutation is explicitly pending, rejected, or unattested, flag MUTATION_PENDING, MEDIUM, quoting the exact status.

            7. AUTHENTICATION: If the document is complete enough to assess authentication and no official signature, seal, attestation or digital authentication is present, flag MUTATION_PENDING. Do not flag solely because OCR may have missed a seal/signature.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    conversion_checks = """CONVERSION / NA ORDER

            ACCURACY
            Extract exact OCR values; never guess. Preserve survey/hissa, area, applicant/owner, order details, conversion purpose, challan/fees, conditions, authority and authentication details.

            VERIFY — WITHIN THIS DOCUMENT ONLY
            Report only supported issues; passing checks stay silent.

            1. PROPERTY: Flag conflicting survey/hissa or area values within the document.

            2. ORDER: Extract order number, order date and issuing authority. Flag genuinely missing essential order details.

            3. APPLICANT/OWNER: Extract applicant and owner exactly. Flag only internal contradictions or genuinely missing identity details.

            4. PURPOSE: Extract the approved conversion purpose/use exactly. Flag conflicting purposes stated within the document.

            5. FEES: Extract challan/payment references, amounts and payment status. If fees are explicitly unpaid, pending or deficient, flag FINANCIAL_MISMATCH.

            6. CONDITIONS: Extract all government/authority conditions and restrictions. Flag any condition explicitly shown as pending, violated or unfulfilled.

            7. AUTHENTICATION: If the document is complete enough to assess authenticity and lacks official signature, seal or digital authentication, flag MISSING_DOCUMENT. Do not flag solely because OCR may have missed visual authentication.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    rtc_checks = """RTC / PAHANI

            ACCURACY
            Extract exact OCR values; never guess. Preserve survey/hissa, total extent, kharab land, net area, owners (Column 9), rights/liabilities and cultivators/crops (Column 12).

            VERIFY — WITHIN THIS RTC ONLY
            Report only supported issues; passing checks stay silent.

            1. RECENCY: If the assessment year or print date is clearly older than 1 year, flag DOCUMENT_EXPIRY at low/medium severity with the actual date/year.

            2. LIABILITIES: If rights/liability columns explicitly record a bank mortgage, hypothecation, outstanding loan, court injunction or dispute, flag PENDING_MORTGAGE or SUSPICIOUS_PATTERN as appropriate, quoting the exact entry. Do not infer a liability from unrelated text.

            3. TENANCY: If a person other than the recorded owner is explicitly shown as cultivator with tenancy or occupancy rights, flag SUSPICIOUS_PATTERN, medium/high. Do not flag a different cultivator unless the RTC indicates a legally relevant right.

            4. AREA: If total extent, net area and kharab area are available in equivalent units, compute net + kharab. If the result differs from total extent by more than 1%, flag PROPERTY_MISMATCH, MEDIUM, and show the calculation.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    rera_checks = """RERA CERTIFICATE

            ACCURACY
            Extract exact OCR values; never guess. Preserve project name, promoter name, registration number, acknowledgement details, approval and expiry dates, and property identifiers.

            VERIFY — WITHIN THIS RERA CERTIFICATE ONLY
            Report only supported issues; passing checks stay silent.

            1. DOCUMENT EXPIRY: Compare the registration's expiry_date with the current date (2026-07-15). If the expiry_date is in the past, flag DOCUMENT_EXPIRY at HIGH severity.

            2. IDENTIFIERS: If there are no clear property identifiers (survey numbers, CTS numbers, or plots covered), flag PROPERTY_MISMATCH at MEDIUM severity.

            3. REGISTRATION NUMBER: If the project registration number is missing, flag MISSING_DOCUMENT at HIGH severity.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    litigation_checks = """LITIGATION AFFIDAVIT
            
            ACCURACY
            Extract exact OCR values; never guess. Preserve certificate number, date, stamp duty amount, notary details, promoter name, project name, land extent, and deponent details.

            VERIFY — WITHIN THIS LITIGATION AFFIDAVIT ONLY
            Report only supported issues; passing checks stay silent.

            1. NOTARY VALIDITY: Compare the notary's commission expiration date (notary_exp_date) with the current date (2026-07-15). If expired, flag DOCUMENT_EXPIRY at HIGH severity.
            
            2. LAND DECLARATION: Check the deponent's declaration. If the affidavit indicates the project land is NOT free from encumbrances or contains pending litigations/claims, flag PENDING_MORTGAGE or SUSPICIOUS_PATTERN at HIGH severity.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    allotment_checks = """ALLOTMENT LETTER
            
            ACCURACY
            Extract exact OCR values; never guess. Preserve letter date, unit number, project name, promoter name, allottee, total cost/consideration, and booking amount details.

            VERIFY — WITHIN THIS ALLOTMENT LETTER ONLY
            Report only supported issues; passing checks stay silent.

            1. BOOKING AMOUNT LIMIT: Compute the booking amount as a percentage of the total unit cost. If it exceeds 10% of the total unit cost, flag FINANCIAL_MISMATCH at MEDIUM severity.
            
            2. PROJECT COMPLETION DATE: Verify the stated possession date. If the project completion/possession date is in the past relative to the current date (2026-07-15), flag DOCUMENT_EXPIRY at HIGH severity.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    building_license_checks = """BUILDING LICENSE
            
            ACCURACY
            Extract exact OCR values; never guess. Preserve license number, license date, owner/applicant name, survey/CTS numbers, plot area, boundaries, floor specifications, total built-up area, and fees paid.

            VERIFY — WITHIN THIS BUILDING LICENSE ONLY
            Report only supported issues; passing checks stay silent.

            1. LICENSE VALIDITY: Compare the license's valid_to date with the current date (2026-07-15). If valid_to is in the past, flag DOCUMENT_EXPIRY at HIGH severity.
            
            2. PROPERTY IDENTIFIERS: If there are conflicting survey or CTS numbers within the document, flag PROPERTY_MISMATCH at MEDIUM severity.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    partition_deed_checks = """PARTITION DEED

            ACCURACY
            Extract exact OCR values; never guess. Map each value to the correct schema field based on context and labels. Preserve identifiers, names, survey/CTS/municipal numbers, boundaries, and measurements exactly.

            EXTRACT
            - File metadata: registration number, document number, book number, cd number, execution/registration date, issuing office.
            - Financial summary: stamp duty paid, registration fee, scanning fee, conversion fee, scrutiny fee, total other fees, and details of any DD or payments.
            - Parties: all coparceners / family members (names, ages, occupations, addresses, and party number/role).
            - Schedule A (total property being partitioned): full description, identifiers, measurements, boundaries.
            - Allocated Schedules (First Schedule, Second Schedule, etc.): schedule name, allocated party name, description, boundaries, measurements.
            - Witnesses.

            VERIFY — WITHIN THIS PARTITION DEED ONLY
            Report only supported issues; passing checks stay silent.

            1. PARTIES: Flag if fewer than 2 parties/coparceners are identified in the deed.
            2. PROPERTY ID: Flag if neither a usable survey nor CTS number exists for Schedule A or any allocated schedule.
            3. DATES: If execution_date > registration_date, flag DATE_INCONSISTENCY with both dates.
            4. WITNESSES: If the execution/attestation section is available and fewer than 2 witnesses are identified, flag MISSING_DOCUMENT, HIGH.
            5. STAMP DUTY: If stamp_duty_paid_amount is explicitly zero, flag FINANCIAL_MISMATCH.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    completion_certificate_checks = """COMPLETION CERTIFICATE

            ACCURACY
            Extract exact OCR values; never guess. Map each value to the correct schema field based on context and labels. Preserve identifiers, names, survey/CTS/municipal numbers, and dates exactly.

            EXTRACT
            - File metadata: certificate number, certificate date, issuing office.
            - Application details: applicant name, application date, building permission letter reference, building permission letter date.
            - Inspection details: inspected by (e.g. JE, Town Planning Officer), inspection date.
            - Property details: survey number, CTS number, location, supervising architect/engineer, fit for occupation floors (e.g. GF, FF, SF), intended use.

            VERIFY — WITHIN THIS DOCUMENT ONLY
            Report only supported issues; passing checks stay silent.

            1. PROPERTY ID: Flag if neither a usable survey nor CTS number exists.
            2. DATES: If certificate_date < application_date, flag DATE_INCONSISTENCY with both dates.

            Follow the OUTPUT QUALITY CONTRACT.
            """

    generic_checks = """GENERIC DOCUMENT

            Extract exact OCR values; never guess.

            VERIFY — WITHIN THIS DOCUMENT ONLY
            - Identify the apparent document type.
            - Extract document number, date, issuing authority, property identifiers and party names when present.
            - Flag only clear internal inconsistencies, quoting the conflicting values.

            Report only supported issues; passing checks stay silent.
            Follow the OUTPUT QUALITY CONTRACT.
            """

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
        "RERA_CERTIFICATE": rera_checks,
        "LITIGATION_AFFIDAVIT": litigation_checks,
        "ALLOTMENT_LETTER": allotment_checks,
        "BUILDING_LICENSE": building_license_checks,
        "PARTITION_DEED": partition_deed_checks,
        "COMPLETION_CERTIFICATE": completion_certificate_checks,
    }

    return base + checks.get(doc_type, generic_checks)


def _generic_schema(doc_type: str) -> dict:
    schema = deepcopy(GENERIC_SCHEMA_TEMPLATE)
    schema["document_type"] = doc_type
    return schema
