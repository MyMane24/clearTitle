import json
import os
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

# ── Schema definitions with verification_notes ────────────────────────────

VERIFICATION_NOTES_SCHEMA = {
    "verification_notes": [
        {
            "type": "DATE_INCONSISTENCY | FINANCIAL_MISMATCH | MISSING_DOCUMENT | PROPERTY_MISMATCH | PENDING_MORTGAGE | EC_GAP | MUTATION_PENDING | CONVERSION_MISSING | TAX_DEFAULT | GUIDANCE_VALUE_ISSUE | SUSPICIOUS_PATTERN",
            "severity": "high | medium | low",
            "confidence": 0.0,
            "summary": "Short description of the issue — MUST include the actual conflicting values, not just the field name",
            "legal_detail": "Legal reasoning under relevant Karnataka statutes, applied to THESE SPECIFIC facts (not a general explanation of the law)",
            "evidence": "Pipe-separated '<field_path>: <exact_value>' pairs taken verbatim from the extracted data",
            "suggestion": "Actionable recommendation naming who to contact or what document to obtain",
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
    "property_details": {
        "property_address": None, "street_or_area_name": None,
        "cts_number": None, "property_number": None, "usage": None,
        "site_total_area_sqft": None, "building_covered_land_area_sqft": None,
        "total_constructed_area_sqft": None, "building_plinth_area_sqft": None,
    },
    "assessment_rows": [
        {"row_number": None, "label": None, "value": None}
    ],
    "challan_copies": [
        {"copy_type": None, "pid": None, "amount_paid": None,
         "payment_date": None, "payment_mode": None}
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
}

# Schema for the cross-document pass — note the extra "doc_ids_involved" field,
# which doesn't exist on the per-document schema because a per-document note is
# implicitly about the document it was extracted from.
CROSS_DOC_SCHEMA = {
    "cross_document_findings": [
        {
            "type": "DATE_INCONSISTENCY | FINANCIAL_MISMATCH | MISSING_DOCUMENT | PROPERTY_MISMATCH | PENDING_MORTGAGE | EC_GAP | MUTATION_PENDING | CONVERSION_MISSING | TAX_DEFAULT | GUIDANCE_VALUE_ISSUE | SUSPICIOUS_PATTERN",
            "severity": "high | medium | low",
            "confidence": 0.0,
            "summary": "Short description including the actual values from each document being compared",
            "legal_detail": "Legal reasoning under relevant Karnataka statutes, tied to these specific facts",
            "evidence": "Pipe-separated '<doc_id> <field_path>: <exact_value>' pairs for every document side of the comparison",
            "doc_ids_involved": ["DOC_001", "DOC_002"],
            "suggestion": "Actionable recommendation naming who to contact or what document to obtain",
        }
    ]
}

# ── Output quality contract (shared by both the per-document and cross-document prompts) ──
# This exists specifically to stop the model from producing findings that name a *category*
# of problem ("Inconsistency in CTS number...") without quoting the actual values, and from
# padding "legal_detail" with generic statute summaries that aren't tied to the real facts.

OUTPUT_QUALITY_CONTRACT = """
OUTPUT QUALITY CONTRACT — read this carefully, it fixes a known failure mode.

A real property-document verifier (a lawyer doing title due diligence) never writes a
finding like "there is an inconsistency in the CTS number" without immediately saying
WHAT the two conflicting numbers actually are. The reader should be able to resolve the
issue from your note alone, without re-opening the source document.

BAD finding (do NOT produce output like this):
  summary: "Inconsistency in CTS number between property address and assessment row."
  legal_detail: "Accurate property identification is crucial under the Karnataka
    Municipal Corporations Act, 1976, for proper tax assessment and ownership records.
    Discrepancies in property identifiers like CTS numbers can lead to misidentification
    of the property..."
  evidence: (no actual values quoted)
  suggestion: "Verify the correct CTS number with official property records."
This is USELESS — it names the category of problem and recites the law in the abstract,
but never tells the reader what the two actual numbers are or where they came from.

GOOD finding (same underlying issue, produced correctly):
  type: "PROPERTY_MISMATCH"
  severity: "high"
  confidence: 0.92
  summary: "CTS number mismatch: property_details.cts_number = '1918' vs
    assessment_rows[2] ('CTS No.') = '1928 Bhag 1'."
  legal_detail: "Property tax under the Karnataka Municipal Corporations Act, 1976 is
    levied against a specific CTS number; if 1918 and 1928 Bhag 1 are different survey
    sub-divisions, this assessment may not correspond to the property under review."
  evidence: "property_details.cts_number: 1918 | assessment_rows[2].label: 'CTS No.' |
    assessment_rows[2].value: '1928 Bhag 1'"
  suggestion: "Confirm with the BBMP Revenue Department or City Survey office which CTS
    number — 1918 or 1928 Bhag 1 — applies to this property before relying on this
    assessment as proof of ownership."

RULES for every finding you produce:
1. "evidence" MUST be a pipe-separated list of "<field_path>: <exact_value>" pairs taken
   verbatim from the extracted data. If you cannot quote a real value on both sides of a
   comparison, do NOT raise the finding — silence is better than a vague finding.
2. "summary" MUST itself contain the actual conflicting/relevant values, not just name
   which field has a problem.
3. "legal_detail" must be 1-2 sentences that apply the statute to THESE SPECIFIC facts.
   Do not write a general explanation of what a law is "for" — only write legal_detail
   if you can connect it directly to the actual numbers/names/dates in evidence.
4. "suggestion" must name a concrete next action and, where relevant, WHO to contact
   (which office/authority) or WHAT specific document to obtain — never "verify with the
   relevant authority" as a generic placeholder.
5. "confidence": use 0.9+ only when both compared values are clearly legible and
   unambiguous; 0.6-0.8 when there is OCR ambiguity (garbled characters, unclear
   formatting, partial dates); below 0.5 — do not report it at all, treat it as noise.
6. Do not raise a finding purely because a field is null/missing UNLESS the absence
   itself is the legally significant fact (e.g. "guidance_value.value is null — without
   it, adequacy of stamp duty under Section 45B Karnataka Stamp Act cannot be checked
   for this Rs. <consideration> transaction"). In that case still name the specific
   transaction/value that's affected by the absence.
7. Never pad legal_detail with boilerplate about why correct records "are important in
   general." If you have nothing case-specific to say, leave legal_detail short and
   factual instead of inventing generic filler.
8. If everything checked is consistent, return an empty array. Do not manufacture a
   finding just to have something to report.
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
        f"- Each verification_note MUST have: type, severity, confidence, summary, legal_detail, evidence, suggestion.\n"
    )


def _ensure_context_cache(doc_type: str) -> str | None:
    """
    Create or refresh a Gemini context cache for the static content of this doc_type.
    Returns the cache name (e.g. "cachedContents/abc123") or None if caching fails.
    """
    try:
        static_content = _build_static_content(doc_type)
        cache_client = _get_cache_client()

        existing = _context_caches.get(doc_type)
        if existing:
            try:
                # Refresh TTL on existing cache
                cache_client.caches.update(
                    name=existing["cache_name"],
                    config={"ttl": f"{CACHE_TTL_SECONDS}s"},
                )
                return existing["cache_name"]
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


# ── Deterministic (non-LLM, pure-Python) checks ───────────────────────────
# These cover anything that's pure arithmetic/date logic. Computing them in code
# instead of asking the LLM means they cannot hallucinate — the numbers are taken
# straight from the parsed JSON and compared with real Python date/number ops.

def _parse_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _det_note(type_, severity, confidence, summary, legal_detail, evidence, suggestion) -> dict:
    return {
        "type": type_,
        "severity": severity,
        "confidence": confidence,
        "summary": summary,
        "legal_detail": legal_detail,
        "evidence": evidence,
        "suggestion": suggestion,
        "source": "deterministic",
    }


def _check_execution_before_registration(result: dict, exec_field="execution_date",
                                          reg_field="registration_date") -> list[dict]:
    fm = result.get("file_metadata", {}) or {}
    exec_raw, reg_raw = fm.get(exec_field), fm.get(reg_field)
    exec_d, reg_d = _parse_date(exec_raw), _parse_date(reg_raw)
    if exec_d and reg_d and exec_d > reg_d:
        return [_det_note(
            type_="DATE_INCONSISTENCY", severity="high", confidence=0.95,
            summary=f"file_metadata.{exec_field} ({exec_raw}) is AFTER file_metadata.{reg_field} ({reg_raw}).",
            legal_detail=(
                "Section 23 read with Section 32 of the Registration Act, 1908 requires "
                "presentation for registration to follow execution; an execution date "
                "later than the registration date is not legally possible for a validly "
                "executed and registered document."
            ),
            evidence=f"file_metadata.{exec_field}: {exec_raw} | file_metadata.{reg_field}: {reg_raw}",
            suggestion=(
                "Re-check the original document for the correct dates — this is likely an "
                "OCR misread of one of the two dates, but if both are confirmed correct as "
                "read, ask the registering Sub-Registrar's office to explain the discrepancy "
                "before relying on this document."
            ),
        )]
    return []


def _check_stamp_duty_ratio(result: dict) -> list[dict]:
    fs = result.get("financial_summary", {}) or {}
    consideration = fs.get("declared_consideration_amount")
    stamp_duty = fs.get("stamp_duty_paid_amount")
    if not (isinstance(consideration, (int, float)) and isinstance(stamp_duty, (int, float))):
        return []
    if consideration <= 0:
        return []
    pct = stamp_duty / consideration * 100
    if pct < STAMP_DUTY_PCT_MIN or pct > STAMP_DUTY_PCT_MAX:
        return [_det_note(
            type_="FINANCIAL_MISMATCH", severity="medium", confidence=0.85,
            summary=(
                f"Stamp duty paid is {pct:.2f}% of declared consideration "
                f"(₹{stamp_duty:,.0f} stamp duty on ₹{consideration:,.0f} consideration); "
                f"the typical Karnataka effective band is roughly "
                f"{STAMP_DUTY_PCT_MIN}%–{STAMP_DUTY_PCT_MAX}% depending on slab/surcharge."
            ),
            legal_detail=(
                "Stamp duty rates and any applicable surcharge/cess under the Karnataka "
                "Stamp Act, 1957 are charged on the higher of consideration or guidance "
                "value. A ratio outside the usual band can mean a concessional rate "
                "applied (e.g. for women purchasers, affordable housing), an extraction "
                "error, or an underpayment that should be confirmed."
            ),
            evidence=(
                f"financial_summary.declared_consideration_amount: {consideration} | "
                f"financial_summary.stamp_duty_paid_amount: {stamp_duty} | "
                f"computed_stamp_duty_pct: {pct:.2f}%"
            ),
            suggestion=(
                "Confirm the stamp duty slab/rate applicable on the registration_date and "
                "location shown in file_metadata, and check whether a concessional rate "
                "applies, before treating this as a real underpayment."
            ),
        )]
    return []


def _check_ec_search_window(result: dict) -> list[dict]:
    fm = result.get("file_metadata", {}) or {}
    years = fm.get("search_period_years")
    if not isinstance(years, (int, float)):
        return []
    if years < EC_MIN_SEARCH_YEARS:
        return [_det_note(
            type_="EC_GAP", severity="high", confidence=0.9,
            summary=(
                f"EC search period is only {years} years "
                f"({fm.get('search_start_date')} to {fm.get('search_end_date')}); "
                f"standard Karnataka title-due-diligence practice expects at least "
                f"{EC_MIN_SEARCH_YEARS} years (30 preferred)."
            ),
            legal_detail=(
                "An EC only certifies what's registered within its own search window; a "
                "short window cannot rule out encumbrances created before search_start_date."
            ),
            evidence=(
                f"file_metadata.search_period_years: {years} | "
                f"file_metadata.search_start_date: {fm.get('search_start_date')} | "
                f"file_metadata.search_end_date: {fm.get('search_end_date')}"
            ),
            suggestion=(
                f"Apply for an additional EC covering the period before "
                f"{fm.get('search_start_date')} to extend total coverage to at least "
                f"{EC_MIN_SEARCH_YEARS} years."
            ),
        )]
    return []


def _check_ec_transaction_gaps(result: dict) -> list[dict]:
    ledger = result.get("historical_ledger") or []
    dated = []
    for tx in ledger:
        d = _parse_date(tx.get("execution_date"))
        if d:
            dated.append((d, tx))
    dated.sort(key=lambda x: x[0])

    notes = []
    for i in range(1, len(dated)):
        gap_days = (dated[i][0] - dated[i - 1][0]).days
        if gap_days > EC_GAP_FLAG_YEARS * 365:
            prev_d, prev_tx = dated[i - 1]
            cur_d, cur_tx = dated[i]
            notes.append(_det_note(
                type_="EC_GAP", severity="medium", confidence=0.8,
                summary=(
                    f"{gap_days // 365}-year gap with no registered transaction between "
                    f"{prev_d} (transaction #{prev_tx.get('transaction_index')}) and "
                    f"{cur_d} (transaction #{cur_tx.get('transaction_index')})."
                ),
                legal_detail=(
                    "A long gap between registered transactions isn't itself illegal, but "
                    "the EC cannot confirm what happened to the property during that "
                    "window — e.g. unregistered agreements, possession disputes, or "
                    "succession that never got formally recorded."
                ),
                evidence=(
                    f"historical_ledger[#{prev_tx.get('transaction_index')}].execution_date: {prev_d} | "
                    f"historical_ledger[#{cur_tx.get('transaction_index')}].execution_date: {cur_d}"
                ),
                suggestion=(
                    "Ask the seller for any documentation of ownership/possession during "
                    "this gap, and separately check RTC/mutation revenue records for the "
                    "same window."
                ),
            ))
    return notes


def _check_ec_unreleased_mortgages(result: dict) -> list[dict]:
    ledger = result.get("historical_ledger") or []
    dated = []
    for tx in ledger:
        d = _parse_date(tx.get("execution_date"))
        dated.append((d, tx))
    dated.sort(key=lambda x: (x[0] is None, x[0] or date.min))

    open_mortgages: list[tuple] = []
    for d, tx in dated:
        ttype = (tx.get("transaction_type") or "").lower()
        if any(k in ttype for k in ("mortgage", "charge", "lien")):
            open_mortgages.append((d, tx))
        elif any(k in ttype for k in ("release", "discharge", "redemption")):
            if open_mortgages:
                open_mortgages.pop(0)

    notes = []
    for d, tx in open_mortgages:
        notes.append(_det_note(
            type_="PENDING_MORTGAGE", severity="high", confidence=0.75,
            summary=(
                f"Mortgage/charge transaction #{tx.get('transaction_index')} "
                f"(execution_date {d}, type '{tx.get('transaction_type')}') has no "
                f"matching release/discharge entry later in this EC's historical_ledger."
            ),
            legal_detail=(
                "An unreleased mortgage/charge remains a valid encumbrance on the "
                "property; absent a registered release/discharge entry, the property "
                "cannot be treated as free of that charge."
            ),
            evidence=(
                f"historical_ledger[#{tx.get('transaction_index')}].execution_date: {d} | "
                f"historical_ledger[#{tx.get('transaction_index')}].transaction_type: "
                f"{tx.get('transaction_type')} | "
                f"historical_ledger[#{tx.get('transaction_index')}].registration_reference: "
                f"{tx.get('registration_reference')}"
            ),
            suggestion=(
                "Obtain the registered release/discharge deed for this specific charge "
                "directly from the lender or the Sub-Registrar's office, or written "
                "confirmation that the loan is closed and the charge withdrawn. Note: "
                "this is a heuristic match (oldest open mortgage matched to next release "
                "found) — confirm manually if multiple mortgages overlap."
            ),
        ))
    return notes


def _apply_deterministic_checks(doc_type: str, result: dict) -> list[dict]:
    notes: list[dict] = []
    if doc_type == "SALE_DEED":
        notes += _check_execution_before_registration(result)
        notes += _check_stamp_duty_ratio(result)
    elif doc_type == "GIFT_DEED":
        notes += _check_execution_before_registration(result)
    elif doc_type == "ENCUMBRANCE_CERTIFICATE":
        notes += _check_ec_search_window(result)
        notes += _check_ec_transaction_gaps(result)
        notes += _check_ec_unreleased_mortgages(result)
    return notes


# ── Per-document structuring + verification ────────────────────────────────

def structure_document_with_gemini(merged_ocr: dict, doc_type: str,
                                    retry_count: int = 0) -> dict:
    """
    Extract structured fields AND generate verification notes in a single LLM call,
    then layer on deterministic (code-computed) checks that don't depend on the LLM.
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

    client = _get_cache_client()
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

    result = json.loads(raw_response)
    if "document_type" not in result:
        result["document_type"] = doc_type

    llm_notes = result.pop("verification_notes", [])
    for n in llm_notes:
        n.setdefault("source", "llm")

    if "file_metadata" in result and page_count:
        result["file_metadata"]["scanned_sheet_count"] = page_count

    # Layer deterministic checks on top — these run against the same parsed `result`
    # and cannot hallucinate since they're plain arithmetic/date comparisons.
    deterministic_notes = _apply_deterministic_checks(doc_type, result)
    verification_notes = deterministic_notes + llm_notes

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
        "SALE_DEED VERIFICATION CHECKS (compare these fields against each other and cite "
        "real values for both sides):\n"
        "- Are both vendors AND purchasers actually named (not just placeholders)?\n"
        "- Is survey_number or cts_number present and does it look like a real survey "
        "  number format (not a placeholder like '0' or 'NA')?\n"
        "- Compare statutory_valuation_endorsement.estimated_market_value against "
        "  financial_summary.declared_consideration_amount. If consideration is below "
        "  market value AND prevention_of_undervaluation_referred is false/null, flag "
        "  GUIDANCE_VALUE_ISSUE citing both numbers and the percentage shortfall.\n"
        "- If property_schedule.full_schedule_description or intended_usage mentions "
        "  'agricultural'/'farm'/'cultivation' in the SCHEDULE OF PROPERTY itself (not in "
        "  a party's address or a road name used only for location), flag CONVERSION_MISSING "
        "  and quote the exact phrase found.\n"
        "- Count witnesses if listed elsewhere in the OCR; if fewer than 2, flag "
        "  MISSING_DOCUMENT/SUSPICIOUS_PATTERN citing how many were found.\n"
        "- Does the OCR reference a prior encumbrance/mortgage on this property without a "
        "  corresponding release shown anywhere in this same document? If so, flag "
        "  PENDING_MORTGAGE and quote the referencing sentence.\n"
        "(Date ordering and stamp duty % are checked deterministically in code — do not "
        "duplicate those as LLM findings.)\n"
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
        "       it as such.\n"
        "  LLM-LEVEL LEGAL CHECKS (gaps, search-window length, and mortgage/release "
        "  matching are ALSO computed deterministically in code afterward — focus your "
        "  own checks on things code can't compute):\n"
        "    1. CHAIN OF TITLE CONTINUITY WITHIN THIS EC: does each transaction's "
        "       purchaser become the next transaction's vendor? If a name doesn't carry "
        "       forward, quote both transaction indices and both names — this is a real "
        "       break in the chain, not a formatting issue.\n"
        "    2. PROPERTY IDENTIFIER CONSISTENCY ACROSS TRANSACTIONS: do plot_no/pid_no/"
        "       cts_no stay consistent across all transactions for this one EC (excluding "
        "       boundary mentions per rule (e) above)? Quote any transaction whose own "
        "       identifier differs from the rest.\n"
        "- If 'Nil Encumbrance' is stated, set historical_ledger to [] and skip the chain/"
        "  identifier checks above (there's nothing to compare).\n"
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
        "- Are mutation_or_transaction_entries populated and does the most recent entry's "
        "  date look plausible relative to document_metadata.application_date (i.e. not "
        "  dated after the card itself was issued)?\n"
        "- Is tenure one of the standard Karnataka categories (e.g. Freehold/Patta, "
        "  Leasehold, Government/Inam)? If it's an abbreviation or code you can't expand "
        "  with confidence (e.g. a single letter), quote it verbatim rather than guessing "
        "  its meaning, and flag PROPERTY_MISMATCH/SUSPICIOUS_PATTERN noting it needs "
        "  clarification from the issuing office — do NOT invent what the abbreviation means.\n"
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
        "- Cess components in Karnataka municipal tax are commonly: Health 15%, Library "
        "  6%, Beggary 3%, Urban Transport 2% (of the base property tax) — if individual "
        "  cess line items AND a total are both present in assessment_rows, check whether "
        "  they sum consistently; if they clearly don't (not just a few-rupee rounding "
        "  difference), flag FINANCIAL_MISMATCH quoting each line item value and the stated "
        "  total. If you can't find the individual line items, do not guess — skip this check.\n"
        "- Is owner_name present and is it a real name (not a template placeholder)?\n"
        "- Is pid present and does it match the format used elsewhere in this same document "
        "  (e.g. consumer_details.pid vs property_owner.pid)? Quote both if they differ.\n"
        "- Is transaction_details.status (or equivalent) a clear success/paid state? If it "
        "  reads as failed/pending/anything other than success, flag TAX_DEFAULT quoting "
        "  the exact status text.\n"
        "- Is assessment_year recent relative to today, or several years stale? Quote the "
        "  actual year found.\n"
    )

    gift_deed_checks = (
        "GIFT_DEED VERIFICATION CHECKS:\n"
        "- Are both donors AND donees named with real names (not blank/placeholder)?\n"
        "- Is parties.relationship_between_parties stated, and is it a close-family "
        "  relation (parent/child/spouse/sibling)? If the stated relationship is distant "
        "  or absent, quote what's actually written — this affects whether a concessional "
        "  gift-deed stamp duty rate properly applies.\n"
        "- Is survey_number or cts_number present and does it match the value, if any, "
        "  referenced elsewhere in the same document (e.g. in the building description)?\n"
        "- Is file_metadata.registration_number present? Gift deeds are compulsorily "
        "  registrable under Section 17, Registration Act, 1908 — quote 'not found' "
        "  explicitly if it's genuinely absent rather than skipping the check silently.\n"
        "- Are witnesses listed (Section 123, Transfer of Property Act requires "
        "  attestation by at least two witnesses for a gift of immovable property)? Quote "
        "  how many were actually found.\n"
        "- Is financial_summary.stamp_duty_amount populated and non-zero?\n"
        "(Date ordering of execution_date vs registration_date is checked deterministically "
        "in code — do not duplicate it as an LLM finding.)\n"
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
    }

    return base + checks.get(doc_type, generic_checks)


def _generic_schema(doc_type: str) -> dict:
    schema = deepcopy(GENERIC_SCHEMA_TEMPLATE)
    schema["document_type"] = doc_type
    return schema
