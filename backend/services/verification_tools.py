"""
Deterministic verification tool functions.
Uses the actual structured JSON schemas from gemini_structurer.py / groq_structurer.py.

Layer 1 — per-document: verify each document individually
Layer 2 — cross-document: verify consistency across the bundle

Each tool returns list[dict] — empty list means no issues found.
All fields are populated in the summary — no separate details field.
doc_ids uses document type names (e.g. "SALE_DEED") so the agent can identify
which document type has the issue.
"""

from __future__ import annotations

import json
from datetime import datetime, date
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────────────

def _get(d: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return default
    return d if d != {} else default


def _parse_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _today() -> date:
    return date.today()


# ──────────────────────────────────────────────────────────────────────────
# LAYER 1 — Per-document tools
# ──────────────────────────────────────────────────────────────────────────

# ── SALE_DEED ────────────────────────────────────────────────────────────

def verify_sale_deed(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Verify SALE_DEED using its structured schema:
      file_metadata (registration_number, execution_date, registration_date, issuing_office, scanned_sheet_count)
      financial_summary (declared_consideration_amount, stamp_duty_paid_amount, total_registration_fees, payment_dd_reference)
      parties.vendors[].entity_name, parties.purchasers[].entity_name
      property_schedule (cts_number, survey_number, measurements, boundaries)
      statutory_valuation_endorsement (estimated_market_value, prevention_of_undervaluation_referred)
    """
    findings: list[dict] = []
    doc_id = next((did for did, dt in doc_type_map.items() if dt == "SALE_DEED"), None)
    if not doc_id:
        return []
    data = documents.get(doc_id, {})

    fm = _get(data, "file_metadata", default={})
    fin = _get(data, "financial_summary", default={})
    parties = _get(data, "parties", default={})
    ps = _get(data, "property_schedule", default={})
    sve = _get(data, "statutory_valuation_endorsement", default={})

    reg_no = fm.get("registration_number")
    exec_dt = fm.get("execution_date")
    reg_dt = fm.get("registration_date")
    consideration = fin.get("declared_consideration_amount")
    stamp_duty = fin.get("stamp_duty_paid_amount")
    survey = ps.get("survey_number") or ps.get("cts_number")
    vendors = _get(parties, "vendors", default=[])
    purchasers = _get(parties, "purchasers", default=[])

    if not reg_no:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: file_metadata.registration_number is null. Under Section 17(1)(a) of the Registration Act, 1908, a Sale Deed is compulsorily registrable and the Sub-Registrar assigns a unique registration number. Without it the deed cannot be cross-verified against the Encumbrance Certificate or traced through the Kaveri portal (https://kaveri.karnataka.gov.in), and the fact of proper registration itself cannot be confirmed.",
                         "suggestion": "Obtain the registration number from the original deed or a certified copy from the Sub-Registrar's office under Section 57(5) of the Registration Act. Search the Kaveri portal using party names and approximate year of execution."})

    if not exec_dt:
        findings.append({"type": "DATE_INCONSISTENCY", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: file_metadata.execution_date is null. The execution date establishes when the parties signed the deed and is essential for determining priority under Section 48 of the Registration Act, computing limitation periods under the Limitation Act, 1963, and verifying chronological order with the registration date and other documents in the chain.",
                         "suggestion": "Extract from the deed's opening paragraph ('made and executed this ___ day of ___') or near the witness signatures. Request a clearer scan if OCR failed."})

    if not reg_dt:
        findings.append({"type": "DATE_INCONSISTENCY", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: file_metadata.registration_date is null. Under Section 61 of the Registration Act, 1908, the registering officer endorses the date of registration on the deed. This date determines priority between competing interests under Section 47 and is essential for cross-referencing with the Encumbrance Certificate's historical ledger entries.",
                         "suggestion": "The registration date is typically stamped on the first or last page with the Sub-Registrar's seal. Provide a clearer scan of the registration endorsement page."})

    if exec_dt and reg_dt:
        ed = _parse_date(exec_dt)
        rd = _parse_date(reg_dt)
        if ed and rd and ed > rd:
            findings.append({"type": "DATE_INCONSISTENCY", "severity": "high", "doc_ids": ["SALE_DEED"],
                             "summary": f"SALE_DEED: execution_date ({exec_dt}) is AFTER registration_date ({reg_dt}), which is legally impossible. Under Section 32 of the Registration Act, 1908, a deed must be executed (signed by the parties) before it can be presented for registration. An execution date after registration indicates one or both dates were incorrectly extracted from the OCR.",
                             "suggestion": "Re-examine the original deed. The execution date appears in the opening paragraph and near the signatures. The registration date appears on the Sub-Registrar's endorsement stamp. Correct the extracted dates before relying on this document."})

    if not consideration:
        findings.append({"type": "FINANCIAL_MISMATCH", "severity": "high", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: financial_summary.declared_consideration_amount is null. The sale consideration is the price paid by the purchaser to the vendor and is the essence of a contract of sale under Section 54 of the Transfer of Property Act, 1882. This amount determines the stamp duty payable under Schedule 1 to the Karnataka Stamp Act, 1957, and must be cross-checked against the guidance value. Without this figure the transaction's financial legitimacy cannot be assessed.",
                         "suggestion": "Extract the consideration from the deed's operative clause ('for a consideration of Rs. ___') or the payment details section. If OCR failed due to poor scan quality, obtain a clearer copy of the relevant page."})

    if not stamp_duty:
        findings.append({"type": "FINANCIAL_MISMATCH", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: financial_summary.stamp_duty_paid_amount is null. Stamp duty is collected under the Karnataka Stamp Act, 1957, at the time of registration on the higher of declared consideration or guidance value. Without this field, compliance with the Stamp Act and detection of potential undervaluation under Section 47A cannot be verified.",
                         "suggestion": "Check the stamp paper itself or the treasury challan / bank DD details section within the deed for the stamp duty amount."})

    if not survey:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: property_schedule.survey_number and cts_number are both null. Karnataka property identification requires either an R.S. No. (Rural Survey Number under the Karnataka Land Revenue Act, 1964) or a C.T.S. No. (City Survey Number maintained by the City Survey Office). Without at least one of these identifiers, the property cannot be cross-matched to the Encumbrance Certificate, Property Register Card, or tax receipts.",
                         "suggestion": "Check the full_schedule_description field or raw OCR for 'R.S.No. ___', 'Survey No. ___', or 'CTS No. ___'. The number may be present in the text but not extracted into the structured field."})

    if not vendors:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: parties.vendors is empty. Every Sale Deed must identify the seller/transferor. Under Section 7 of the Transfer of Property Act, 1882, only the absolute owner or their authorized representative can convey title. Without a named vendor: (a) the deed is invalid for want of a transferor, (b) the ownership chain from the Encumbrance Certificate cannot be traced, (c) no due diligence can be performed on the vendor's title.",
                         "suggestion": "Re-examine the deed's opening paragraph ('THIS DEED OF SALE is made by ___') and testimonium clause ('Signed and delivered by ___'). Obtain a clearer scan if OCR failed."})

    if not purchasers:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: parties.purchasers is empty. Every Sale Deed must identify the buyer/transferee. Without a named purchaser: (a) the deed is legally incomplete, (b) the party holding title after the transaction cannot be determined, (c) the Property Register Card and Khata cannot be updated to reflect the correct owner.",
                         "suggestion": "Look for the purchaser's name in the opening paragraph ('in favour of ___') and the acceptance/execution clause. Obtain a clearer scan if needed."})

    if sve.get("prevention_of_undervaluation_referred") is True:
        findings.append({"type": "GUIDANCE_VALUE_ISSUE", "severity": "medium", "doc_ids": ["SALE_DEED"],
                         "summary": "SALE_DEED: statutory_valuation_endorsement.prevent_of_undervaluation_referred is True. Under Section 47A of the Karnataka Stamp Act, 1957, and the Karnataka Stamp (Prevention of Undervaluation of Instruments) Rules, if the Sub-Registrar suspects the market value is understated, the matter is referred to the Deputy Commissioner for determination of correct market value. Additional stamp duty plus penalty (up to 2x the deficit duty) may be payable after the final valuation order.",
                         "suggestion": "Check the status of the Form 1A proceeding with the Sub-Registrar. If a final order has been passed, obtain it and verify that additional duty has been paid. If the proceeding is pending, factor the potential liability into the transaction."})

    return findings


# ── GIFT_DEED ────────────────────────────────────────────────────────────

def verify_gift_deed(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Verify GIFT_DEED using its schema:
      file_metadata, financial_summary (stamp_duty_amount, registration_fee, etc.)
      parties.donors, parties.donees, relationship_between_parties, reason_for_gift
      property_schedule (same structure as SALE_DEED)
      covenants, witnesses, certification
    """
    findings: list[dict] = []
    doc_id = next((did for did, dt in doc_type_map.items() if dt == "GIFT_DEED"), None)
    if not doc_id:
        return []
    data = documents.get(doc_id, {})

    fm = _get(data, "file_metadata", default={})
    parties = _get(data, "parties", default={})
    ps = _get(data, "property_schedule", default={})

    exec_dt_str = fm.get("execution_date")
    reg_dt_str = fm.get("registration_date")
    donors = _get(parties, "donors", default=[])
    donees = _get(parties, "donees", default=[])
    relationship = parties.get("relationship_between_parties")
    reg_no = fm.get("registration_number")

    if not donors:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": ["GIFT_DEED"],
                         "summary": "GIFT_DEED: parties.donors is empty. Every Gift Deed must identify the donor(s) who are transferring the property without consideration. Under the Transfer of Property Act, 1882, a gift must be made by a donor competent to contract. Without a named donor the deed is invalid.",
                         "suggestion": "Re-examine the deed for the donor's name in the opening paragraph. Obtain a clearer scan if OCR failed."})

    if not donees:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": ["GIFT_DEED"],
                         "summary": "GIFT_DEED: parties.donees is empty. Every Gift Deed must identify the donee(s) who are receiving the property. Under Section 122 of the Transfer of Property Act, 1882, a gift requires a donee capable of taking the property. Without a named donee the deed is invalid.",
                         "suggestion": "Look for the donee's name in the deed's operative clause ('in favour of ___'). Obtain a clearer scan if needed."})

    if relationship:
        if relationship.lower() not in ("mother", "father", "son", "daughter", "wife", "husband",
                                         "brother", "sister", "grandson", "granddaughter",
                                         "grandmother", "grandfather"):
            findings.append({"type": "SUSPICIOUS_PATTERN", "severity": "low", "doc_ids": ["GIFT_DEED"],
                             "summary": f"GIFT_DEED: unusual donor-donee relationship '{relationship}' — Gift Deeds under the Gift Tax Act are typically between close relatives as defined under the Income Tax Act. A relationship outside the immediate family may trigger tax implications or indicate a transaction structured as a gift to avoid stamp duty.",
                             "suggestion": "Verify that the relationship is genuine and that the gift is not a disguised sale. Under Section 56(2)(x) of the Income Tax Act, gifts from non-relatives exceeding Rs. 50,000 may be taxable."})

    ed = _parse_date(exec_dt_str)
    rd = _parse_date(reg_dt_str)
    if ed and rd and ed > rd:
        findings.append({"type": "DATE_INCONSISTENCY", "severity": "high", "doc_ids": ["GIFT_DEED"],
                         "summary": f"GIFT_DEED: execution_date ({exec_dt_str}) is AFTER registration_date ({reg_dt_str}), which is legally impossible. Under Section 32 of the Registration Act, 1908, a deed must be executed (signed) before it can be presented for registration. Either one or both dates were incorrectly extracted.",
                         "suggestion": "Re-examine the original deed. The execution date appears in the opening paragraph and near the signatures. The registration date appears on the Sub-Registrar's endorsement stamp."})

    if not ps.get("survey_number"):
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["GIFT_DEED"],
                         "summary": "GIFT_DEED: property_schedule.survey_number is null. Without a survey number or CTS number, the property being gifted cannot be cross-referenced against other documents (EC, PRC, tax records) for due diligence.",
                         "suggestion": "Obtain the survey number from the original deed's property schedule — it typically appears as 'R.S.No. ___' or 'Survey No. ___'."})

    if not reg_no:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["GIFT_DEED"],
                         "summary": "GIFT_DEED: file_metadata.registration_number is null. Under Section 17(1)(a) of the Registration Act, 1908, a Gift Deed of immovable property is compulsorily registrable. Without the registration number the document cannot be traced in official records.",
                         "suggestion": "Obtain the registration number from the original deed or a certified copy from the Sub-Registrar's office."})

    return findings


# ── ENCUMBRANCE_CERTIFICATE ─────────────────────────────────────────────

def verify_encumbrance_certificate(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Verify ENCUMBRANCE_CERTIFICATE using EC_SCHEMA:
      file_metadata.application_number, search_start_date, search_end_date, issuing_office
      search_criteria.target_village, target_hobli, target_identifiers (cts_number, survey_number, converted_survey_number, plot_number)
      historical_ledger[].execution_date, registration_reference, transaction_type, financials, parties, property_details
    """
    findings: list[dict] = []
    doc_id = next((did for did, dt in doc_type_map.items() if dt == "ENCUMBRANCE_CERTIFICATE"), None)
    if not doc_id:
        return []
    data = documents.get(doc_id, {})

    fm = _get(data, "file_metadata", default={})
    sc = _get(data, "search_criteria", default={})
    identifiers = _get(sc, "target_identifiers", default={})
    ledger = _get(data, "historical_ledger", default=[])

    app_no = fm.get("application_number")
    search_start = fm.get("search_start_date")
    search_end = fm.get("search_end_date")
    survey_no = identifiers.get("survey_number")

    if not app_no:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: file_metadata.application_number is null. The application number is the administrative reference assigned by the Sub-Registrar's office when the EC was applied for. Without it the EC cannot be traced back to the application for verification of search parameters.",
                         "suggestion": "Check the original EC for the application number at the top of the certificate."})

    if not search_start:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: file_metadata.search_start_date is null. Without the start date of the search period, the coverage of the EC cannot be determined. An EC must specify its search period to establish which transactions are covered.",
                         "suggestion": "Verify the search period from the original EC. The start date is typically the date from which the encumbrance search was conducted."})

    if not search_end:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: file_metadata.search_end_date is null. Without the end date, the coverage of the EC is incomplete. The search period must be known to verify that all relevant transactions are captured.",
                         "suggestion": "Verify the search end date from the original EC. This is typically the date up to which the search was conducted."})

    if not survey_no:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: search_criteria.target_identifiers.survey_number is null. The EC was issued without a survey number in its search criteria, making it unclear which property's encumbrance history was searched.",
                         "suggestion": "Verify that the EC was issued for the correct property by checking the search criteria section for any property identifier (CTS number, plot number, or converted survey number)."})

    if not ledger:
        findings.append({"type": "EC_GAP", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: historical_ledger is empty — no transactions recorded for the entire search period. While a 'nil' EC (no encumbrances) is common, an empty ledger could also indicate the EC was issued for the wrong property or the search period is incorrect.",
                         "suggestion": "Confirm the search period and property identifiers are correct. If the purpose is to verify a specific transaction (e.g., a Sale Deed), the EC should ideally show that transaction or confirm the period before it. Obtain a fresh EC if needed."})
        return findings

    dated = []
    for txn in ledger:
        d = _parse_date(txn.get("execution_date"))
        if d:
            dated.append((d, txn))
    dated.sort(key=lambda x: x[0])

    for i in range(1, len(dated)):
        gap = (dated[i][0] - dated[i - 1][0]).days
        if gap > 365 * 3:
            prev_d = dated[i - 1][1].get("execution_date", "?")
            curr_d = dated[i][1].get("execution_date", "?")
            findings.append({"type": "EC_GAP", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                             "summary": f"ENCUMBRANCE_CERTIFICATE: gap of {gap//365} years in the historical ledger between {prev_d} and {curr_d}. Under the Transfer of Property Act, 1882, unregistered transactions during this period could affect title. A gap of more than 3 years in registered transactions is unusual and may indicate unregistered dealings or a break in the ownership chain.",
                             "suggestion": "Obtain an affidavit explaining the gap from the current owner or a supplementary EC covering the gap period from the Sub-Registrar's office."})

    mortgage_terms = ["mortgage", "loan", "charge", "lien", "hypothecation", "security"]
    release_terms = ["release", "satisfaction", "discharge", "redemption", "closure"]
    has_mortgage = False
    has_release = False
    for txn in ledger:
        ttype = (txn.get("transaction_type") or "").lower()
        if any(t in ttype for t in mortgage_terms):
            if any(t in ttype for t in release_terms):
                has_release = True
            else:
                has_mortgage = True
    if has_mortgage and not has_release:
        findings.append({"type": "PENDING_MORTGAGE", "severity": "high", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                         "summary": "ENCUMBRANCE_CERTIFICATE: the historical ledger contains mortgage or charge entries without corresponding release, satisfaction, or discharge entries. Under the Transfer of Property Act, 1882, an outstanding mortgage is a charge on the property that must be discharged before clear title can be transferred.",
                         "suggestion": "Obtain loan closure letters from the respective banks and register satisfactions of mortgage (Form 17 under the Registration Act) at the Sub-Registrar's office. A clear EC showing all mortgages as 'satisfied' or 'discharged' is required."})

    return findings


# ── PROPERTY_REGISTER_CARD ──────────────────────────────────────────────

def verify_property_register_card(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Verify PROPERTY_REGISTER_CARD using its schema:
      document_metadata.issuing_authority, taluka, district
      property_identification.division_number_or_local_area_number, local_area_name, city_survey_number, area_sq_meters, tenure
      holders[].name, share, notes
      easements, lessee, other_encumbrances
      guidance_value.value, order_number, order_date
      mutation_or_transaction_entries[].date, transaction, volume_number, new_holder_or_lessee_or_encumbrance, attestation
      fees, certification
    """
    findings: list[dict] = []
    doc_id = next((did for did, dt in doc_type_map.items() if dt == "PROPERTY_REGISTER_CARD"), None)
    if not doc_id:
        return []
    data = documents.get(doc_id, {})

    dm = _get(data, "document_metadata", default={})
    pi = _get(data, "property_identification", default={})
    holders = _get(data, "holders", default=[])
    gv = _get(data, "guidance_value", default={})
    mutations = _get(data, "mutation_or_transaction_entries", default=[])
    lessee = data.get("lessee")
    easements = data.get("easements")
    encumbrances = data.get("other_encumbrances")

    cs_number = pi.get("city_survey_number")
    area = pi.get("area_sq_meters")
    tenure = pi.get("tenure")

    if not dm.get("issuing_authority"):
        findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: document_metadata.issuing_authority is null. The issuing authority (City Survey Office or Tahsildar) establishes the official source of the PRC. Without it, the document's origin cannot be verified.",
                         "suggestion": "Check the original PRC for the issuing authority's name and seal, typically at the top or bottom of the certificate."})

    if not cs_number:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: property_identification.city_survey_number is null. The City Survey Number is the primary identifier for urban properties in Karnataka and is essential for cross-matching this PRC to other documents like the Sale Deed and Encumbrance Certificate.",
                         "suggestion": "Obtain the correct PRC for this property by verifying the CTS number from the Sale Deed or EC and requesting a matching PRC from the City Survey Office."})

    if not area:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: property_identification.area_sq_meters is null. The area of the property in square meters is not recorded. While this does not block verification, it limits the ability to cross-check property dimensions across documents.",
                         "suggestion": "Check the original PRC for the area in square meters. If available in the raw OCR text but not extracted, update the structured field."})

    if not holders:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: holders array is empty. The PRC does not list any current holders or owners of the property. This is a critical omission because the PRC is the primary government record for establishing current ownership. Without holder information, the ownership chain from the Sale Deed cannot be confirmed.",
                         "suggestion": "Obtain a current PRC with complete holder details from the City Survey Office or Tahsildar. Mutation records should reflect the current owner's name as per the latest registered deed."})
    else:
        for h in holders:
            if isinstance(h, dict) and not h.get("name"):
                findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                                 "summary": "PROPERTY_REGISTER_CARD: a holder entry in the holders array is missing the 'name' field. An incomplete holder record limits the ability to verify the ownership chain.",
                                 "suggestion": "Check the original PRC for the complete holder name. If the OCR failed to capture it, update from the original document."})

    if lessee:
        findings.append({"type": "OWNERSHIP_GAP", "severity": "medium", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": f"PROPERTY_REGISTER_CARD: a lessee is recorded on the property. A leasehold interest means the property is subject to a lease agreement that grants possession rights to the lessee. Under the Transfer of Property Act, 1882, the rights of a lessee may affect the owner's ability to transfer vacant possession.",
                         "suggestion": "Verify the lease terms and whether the lessee has provided consent (if required) for the current transaction. Check if the lease is registered under Section 17 of the Registration Act."})

    if easements:
        findings.append({"type": "SUSPICIOUS_PATTERN", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: easements are recorded on the property. Easements (rights of way, drainage, light, etc.) affect the property's use and enjoyment under the Indian Easements Act, 1882.",
                         "suggestion": "Review the specific easements recorded to ensure they do not conflict with the intended use of the property."})

    if encumbrances:
        findings.append({"type": "PENDING_MORTGAGE", "severity": "medium", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: other encumbrances are recorded on the property. These may include mortgages, liens, court attachments, or other claims that affect the title. Under the Transfer of Property Act, encumbrances must typically be cleared before a clean title can be conveyed.",
                         "suggestion": "Review each encumbrance entry and verify that it has been satisfied or released. Obtain clearance certificates where applicable."})

    gv_value = gv.get("value")
    gv_order = gv.get("order_number")
    gv_date_str = gv.get("order_date")
    if gv_value:
        gv_date = _parse_date(gv_date_str)
        if gv_date and (_today() - gv_date).days > 365 * 2:
            findings.append({"type": "GUIDANCE_VALUE_ISSUE", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                             "summary": f"PROPERTY_REGISTER_CARD: guidance value from {gv_date_str} is over 2 years old. Under the Karnataka Stamp Act, 1957, guidance values are revised periodically by the Inspector General of Registration. An outdated guidance value may not reflect the current market rates for stamp duty calculation.",
                             "suggestion": "Check the latest guidance value circular from the Inspector General of Registration or consult the Kaveri portal for the current guidance value for this property."})
        if not gv_order:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                             "summary": "PROPERTY_REGISTER_CARD: guidance_value has a value but no order_number. The order number references the government circular that sets the guidance value. Without it, the specific revision cannot be verified.",
                             "suggestion": "Check the original PRC for the GV order reference number."})
    else:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: guidance_value.value is null. The guidance value is used for stamp duty calculation under the Karnataka Stamp Act, 1957. Without it, the declared consideration in the Sale Deed cannot be cross-checked against the government's minimum valuation for the property.",
                         "suggestion": "Obtain the guidance value from the Sub-Registrar's office or from the Kaveri online portal for this specific property (based on survey/CTS number and locality)."})

    if holders and not mutations:
        findings.append({"type": "MUTATION_PENDING", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": "PROPERTY_REGISTER_CARD: holders are listed but mutation_or_transaction_entries is empty. The mutation history should show how the current holders acquired title. Under the Karnataka Land Revenue Act, 1964, mutation entries record the chain of succession of ownership.",
                         "suggestion": "Check if the property has a separate mutation register. The mutation entries may be on a different page or volume of the PRC."})

    if tenure and tenure.lower() not in ("freehold", "leasehold", "government", ""):
        findings.append({"type": "PROPERTY_MISMATCH", "severity": "low", "doc_ids": ["PROPERTY_REGISTER_CARD"],
                         "summary": f"PROPERTY_REGISTER_CARD: unusual tenure type '{tenure}' — expected 'Freehold', 'Leasehold', or 'Government'. An unusual tenure classification may indicate an error in the PRC or a special category of land holding.",
                         "suggestion": "Verify tenure classification with the Tahsildar or City Survey Office. Certain tenure types (e.g., 'Inam', 'Grant') may have restrictions on transferability."})

    return findings


# ── TAX_RECEIPT / E_PAYMENT_RECEIPT ─────────────────────────────────────

def verify_tax_receipt(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Verify E_PAYMENT_RECEIPT using its schema:
      document_metadata.issuing_authority, city_or_local_body
      consumer_details.owner_name, pid, ward_name
      transaction_details.transaction_number, payment_reference_number, status, receipt_date
      service_details.service_type, assessment_year, sas_number
      payment_details.service_charges, amount_paid, total_amount, currency
    """
    findings: list[dict] = []
    doc_ids = [did for did, dt in doc_type_map.items()
               if dt in ("E_PAYMENT_RECEIPT", "TAX_RECEIPT", "PROPERTY_TAX_ASSESSMENT")]
    if not doc_ids:
        return []

    for doc_id in doc_ids:
        data = documents.get(doc_id, {})
        dtype = doc_type_map.get(doc_id, "")
        cd = _get(data, "consumer_details", default={})
        td = _get(data, "transaction_details", default={})
        sd = _get(data, "service_details", default={})
        pd = _get(data, "payment_details", default={})

        owner = cd.get("owner_name")
        pid = cd.get("pid")
        txn_no = td.get("transaction_number")
        status = td.get("status")
        rcp_dt_str = td.get("receipt_date")
        asmt_year = sd.get("assessment_year")
        amount = pd.get("amount_paid") or pd.get("total_amount")

        if not owner:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: consumer_details.owner_name is null. The name of the property owner who paid the tax is not recorded. Without it the receipt cannot be linked to the parties in the Sale Deed or the holders in the PRC.",
                             "suggestion": "Obtain a corrected receipt with the owner's name from the municipal corporation."})

        if not pid:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: consumer_details.pid is null. The Property ID (PID) is the unique identifier assigned by the municipal corporation for property tax purposes. Without it the receipt cannot be matched to the specific property.",
                             "suggestion": "Obtain the PID from the municipal corporation's property tax portal or from a previous tax bill."})

        if not txn_no:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: transaction_details.transaction_number is null. The transaction number is the reference for the specific payment transaction. Without it the payment cannot be verified against the municipal corporation's records.",
                             "suggestion": "Check the original receipt for the transaction/acknowledgment number."})

        if status and status.lower() != "success":
            findings.append({"type": "TAX_DEFAULT", "severity": "high", "doc_ids": [dtype],
                             "summary": f"{dtype}: transaction_details.status is '{status}' — the payment was not marked as successful. An unsuccessful payment means the property tax has not been properly paid, which could result in arrears and potential legal action by the municipal corporation.",
                             "suggestion": "Ensure the tax payment is completed successfully through the municipal corporation's payment portal and obtain a new receipt with 'Success' status."})

        rcp_date = _parse_date(rcp_dt_str)
        if rcp_date and (_today() - rcp_date).days > 365 * 2:
            findings.append({"type": "TAX_DEFAULT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: receipt date {rcp_dt_str} is over 2 years old. Property tax is payable annually and an old receipt does not confirm that current taxes have been paid. Outstanding property tax can become a charge on the property under the respective municipal corporation act.",
                             "suggestion": "Obtain a recent tax paid receipt or a No Dues Certificate from the municipal corporation to confirm current tax status."})

        if not asmt_year:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: service_details.assessment_year is null. The assessment year for which the tax was paid is not identified, making it unclear which period the receipt covers.",
                             "suggestion": "Check the original receipt or municipal portal to confirm which assessment year the payment covers."})

        if not amount:
            findings.append({"type": "TAX_DEFAULT", "severity": "low", "doc_ids": [dtype],
                             "summary": f"{dtype}: payment_details.amount_paid is null or zero. No payment amount was recorded, which suggests the tax receipt may not evidence any actual payment of property tax.",
                             "suggestion": "Verify the actual amount paid from the original receipt. If the receipt shows an amount, update the extraction."})

    return findings


# ──────────────────────────────────────────────────────────────────────────
# LAYER 2 — Cross-document tools
# ──────────────────────────────────────────────────────────────────────────

def verify_property_identity(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Cross-document check: Survey Number, CTS Number, PID across all docs.
    Extracts using the correct schema field paths for each type.
    """
    findings: list[dict] = []
    extracted: dict[str, dict[str, str | None]] = {}

    for doc_id, data in documents.items():
        dtype = doc_type_map.get(doc_id, "")
        info: dict[str, str | None] = {"survey": None, "cts": None, "pid": None}
        if dtype == "SALE_DEED":
            ps = _get(data, "property_schedule", default={})
            info["survey"] = ps.get("survey_number")
            info["cts"] = ps.get("cts_number")
        elif dtype == "GIFT_DEED":
            info["survey"] = _get(data, "property_schedule", "survey_number")
            info["cts"] = _get(data, "property_schedule", "cts_number")
        elif dtype == "ENCUMBRANCE_CERTIFICATE":
            info["survey"] = _get(data, "search_criteria", "target_identifiers", "survey_number")
            info["cts"] = _get(data, "search_criteria", "target_identifiers", "cts_number")
        elif dtype == "PROPERTY_REGISTER_CARD":
            info["survey"] = _get(data, "property_identification", "city_survey_number")
        elif dtype == "E_PAYMENT_RECEIPT":
            info["pid"] = _get(data, "consumer_details", "pid")
        elif dtype in ("PROPERTY_TAX_ASSESSMENT", "TAX_RECEIPT"):
            info["pid"] = _get(data, "document_metadata", "pid") or _get(data, "property_owner", "pid")
            info["cts"] = _get(data, "property_details", "cts_number")
        extracted[doc_id] = info

    # Survey number comparison
    surveys = {doc_type_map.get(did, did): v["survey"] for did, v in extracted.items() if v.get("survey")}
    unique_surveys = set(surveys.values())
    if len(unique_surveys) > 1:
        survey_details = ", ".join(f"{dtype}: {val}" for dtype, val in surveys.items())
        findings.append({"type": "PROPERTY_MISMATCH", "severity": "high",
                         "doc_ids": list(surveys.keys()),
                         "summary": f"PROPERTY_IDENTITY: survey number is not consistent across documents — {survey_details}. Under the Karnataka Land Revenue Act, 1964, the same physical property must have the same survey number on all official documents. A mismatch indicates either: (a) a data entry error in one or more documents, (b) the documents refer to different properties, or (c) the property has been subdivided and the survey numbers have changed without all documents being updated.",
                         "suggestion": "Obtain the correct survey number from the City Survey Office or Tahsildar's records. Request correction of the inconsistent document(s) from the issuing authority."})

    # CTS number comparison
    cts_vals = {doc_type_map.get(did, did): v["cts"] for did, v in extracted.items() if v.get("cts")}
    unique_cts = set(cts_vals.values())
    if len(unique_cts) > 1:
        cts_details = ", ".join(f"{dtype}: {val}" for dtype, val in cts_vals.items())
        findings.append({"type": "PROPERTY_MISMATCH", "severity": "high",
                         "doc_ids": list(cts_vals.keys()),
                         "summary": f"PROPERTY_IDENTITY: CTS number is not consistent across documents — {cts_details}. The City Survey (CTS) number is the primary identifier for urban properties in Karnataka and must match across all documents for the same property. A mismatch may indicate different properties or incorrect recording.",
                         "suggestion": "Get the correct CTS number from the City Survey Office and ensure all documents are updated to reflect the same number."})

    # Deed missing survey — can't cross-check
    deed_id = next((did for did, dt in doc_type_map.items() if dt in ("SALE_DEED", "GIFT_DEED")), None)
    if deed_id and not extracted.get(deed_id, {}).get("survey"):
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": [doc_type_map.get(deed_id, "DEED")],
                         "summary": f"PROPERTY_IDENTITY: {doc_type_map.get(deed_id, 'DEED')} has no survey number — cannot cross-check property identity across documents. Without a survey or CTS number on the primary deed, the property described in the deed cannot be matched to other documents in the bundle.",
                         "suggestion": "Obtain the survey number from the original deed's property schedule or from a supplementary document such as the PRC or EC."})

    return findings


def verify_ownership_chain(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Cross-document check: trace ownership from EC → deed → PRC.
    EC: historical_ledger[].parties.vendors[] / purchasers[]
    Deed: parties.vendors[].entity_name, parties.purchasers[].entity_name
    PRC: holders[].name
    """
    findings: list[dict] = []

    ec_id = next((did for did, dt in doc_type_map.items() if dt == "ENCUMBRANCE_CERTIFICATE"), None)
    deed_id = next((did for did, dt in doc_type_map.items() if dt in ("SALE_DEED", "GIFT_DEED")), None)
    prc_id = next((did for did, dt in doc_type_map.items() if dt == "PROPERTY_REGISTER_CARD"), None)

    if not deed_id:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "high", "doc_ids": [],
                         "summary": "OWNERSHIP_CHAIN: no transfer deed (SALE_DEED or GIFT_DEED) found in the document bundle. A deed of transfer is the primary document establishing current ownership under the Transfer of Property Act, 1882, and is essential for verifying the ownership chain.",
                         "suggestion": "Upload the transfer deed for this property to enable ownership chain verification."})
        return findings

    deed_doc = documents.get(deed_id, {})
    deed_type = doc_type_map.get(deed_id, "") if deed_id else ""
    if deed_type == "SALE_DEED":
        deed_vendors = [_get(v, "entity_name") for v in _get(deed_doc, "parties", "vendors", default=[]) if isinstance(v, dict)]
        deed_donors = []
        deed_purchasers = [_get(p, "entity_name") for p in _get(deed_doc, "parties", "purchasers", default=[]) if isinstance(p, dict)]
        deed_donees = []
    else:
        deed_vendors = [_get(v, "entity_name") for v in _get(deed_doc, "parties", "vendors", default=[]) if isinstance(v, dict)]
        deed_donors = [_get(d, "entity_name") for d in _get(deed_doc, "parties", "donors", default=[]) if isinstance(d, dict)]
        deed_purchasers = [_get(p, "entity_name") for p in _get(deed_doc, "parties", "purchasers", default=[]) if isinstance(p, dict)]
        deed_donees = [_get(d, "entity_name") for d in _get(deed_doc, "parties", "donees", default=[]) if isinstance(d, dict)]

    transferors = deed_vendors + deed_donors
    transferees = deed_purchasers + deed_donees

    def norm(n):
        return (n or "").strip().upper().replace(".", "").replace(",", "")

    transferor_norm = [norm(n) for n in transferors if n]
    transferee_norm = [norm(n) for n in transferees if n]

    if ec_id:
        ec_data = documents.get(ec_id, {})
        ledger = _get(ec_data, "historical_ledger", default=[])
        if ledger:
            last_txn = ledger[-1]
            if last_txn:
                parties = _get(last_txn, "parties", default={})
                ec_vendors = _get(parties, "vendors", default=[])
                ec_purchasers = _get(parties, "purchasers", default=[])

                ec_last_seller = ec_vendors[-1] if ec_vendors else None
                ec_last_buyer = ec_purchasers[-1] if ec_purchasers else None

                if isinstance(ec_last_seller, str) and transferor_norm:
                    if norm(ec_last_seller) not in transferor_norm:
                        findings.append({"type": "OWNERSHIP_MISMATCH", "severity": "high",
                                         "doc_ids": ["ENCUMBRANCE_CERTIFICATE", deed_type],
                                         "summary": f"OWNERSHIP_CHAIN: the last EC transaction seller '{ec_last_seller}' does not match the {deed_type} transferor(s) {transferors}. Under the Transfer of Property Act, 1882, a valid chain of title requires that the person selling the property in the current deed acquired title from the previous registered transaction. This break in the chain may indicate a missing deed in the sequence.",
                                         "suggestion": "A missing transaction may exist between the EC's last seller and the deed transferor. Obtain a complete EC covering additional years or trace the gap through prior deeds and mutation records."})

                if isinstance(ec_last_buyer, str) and transferee_norm:
                    if norm(ec_last_buyer) not in transferee_norm:
                        findings.append({"type": "OWNERSHIP_MISMATCH", "severity": "high",
                                         "doc_ids": ["ENCUMBRANCE_CERTIFICATE", deed_type],
                                         "summary": f"OWNERSHIP_CHAIN: the last EC transaction buyer '{ec_last_buyer}' does not match the {deed_type} transferee(s) {transferees}. The EC should end with the same party who is now the transferor in the current deed. A mismatch indicates the chain of title is broken.",
                                         "suggestion": "Verify the chain by obtaining a supplementary EC covering the period up to the deed execution date. There may be additional transactions not captured in this EC."})
        else:
            findings.append({"type": "EC_GAP", "severity": "medium", "doc_ids": ["ENCUMBRANCE_CERTIFICATE"],
                             "summary": "OWNERSHIP_CHAIN: the EC has no historical entries. Without transaction data, the ownership chain cannot be traced from the EC to the current deed.",
                             "suggestion": "Obtain an EC that covers the relevant period and contains the historical transaction entries."})

    if prc_id and transferee_norm:
        prc = documents.get(prc_id, {})
        holders = _get(prc, "holders", default=[])
        holder_names = [norm(h.get("name", "")) for h in holders if isinstance(h, dict) and h.get("name")]

        if holder_names:
            if not any(h in transferee_norm for h in holder_names):
                findings.append({"type": "MUTATION_PENDING", "severity": "medium",
                                 "doc_ids": [deed_type, "PROPERTY_REGISTER_CARD"],
                                 "summary": f"OWNERSHIP_CHAIN: PRC holder(s) do not match {deed_type} transferee(s). PRC holders: {[h.get('name','') for h in holders if isinstance(h, dict)]}. Deed transferees: {transferees}. Under Section 128 of the Karnataka Land Revenue Act, 1964, mutation of records must be applied for after every transfer of ownership. If the PRC still shows the previous holder, mutation is pending.",
                                 "suggestion": "Apply for mutation at the Sub-Registrar's office (Form 12 under the Karnataka Land Revenue Rules) to update the PRC with the current owner's name. A mutated PRC is essential for establishing current title."})

    return findings


def check_red_flags(documents: dict[str, dict], doc_type_map: dict[str, str]) -> list[dict]:
    """
    Cross-document red flag check: missing critical docs, agricultural conversion,
    missing Khata, deed date vs EC coverage, suspicious patterns.
    """
    findings: list[dict] = []
    doc_types = set(doc_type_map.values())

    deed_id = next((did for did, dt in doc_type_map.items() if dt in ("SALE_DEED", "GIFT_DEED")), None)
    ec_id = next((did for did, dt in doc_type_map.items() if dt == "ENCUMBRANCE_CERTIFICATE"), None)
    prc_id = next((did for did, dt in doc_type_map.items() if dt == "PROPERTY_REGISTER_CARD"), None)
    deed_type = doc_type_map.get(deed_id, "DEED") if deed_id else "SALE_DEED or GIFT_DEED"

    required = [
        (deed_id, "SALE_DEED or GIFT_DEED", "a deed of transfer (primary title document)", "high"),
        (ec_id, "ENCUMBRANCE_CERTIFICATE", "an Encumbrance Certificate showing encumbrances typically for the last 12-15 years", "high"),
        (prc_id, "PROPERTY_REGISTER_CARD", "a Property Register Card showing current holder and guidance value", "medium"),
    ]
    for cid, name, purpose, sev in required:
        if not cid:
            findings.append({"type": "MISSING_DOCUMENT", "severity": sev, "doc_ids": [name],
                             "summary": f"RED FLAGS: missing {name} — {purpose}. Without this document, a critical aspect of the title due diligence cannot be completed.",
                             "suggestion": f"Upload {name} to enable complete verification."})

    has_tax = any(dt in ("E_PAYMENT_RECEIPT", "TAX_RECEIPT", "PROPERTY_TAX_ASSESSMENT") for dt in doc_types)
    if not has_tax:
        findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": ["TAX_RECEIPT"],
                         "summary": "RED FLAGS: no property tax document found in the bundle. Without a recent tax receipt or property tax assessment, the current property tax status cannot be confirmed. Outstanding property tax may constitute a charge on the property.",
                         "suggestion": "Upload a recent property tax paid receipt or a No Dues Certificate from the municipal corporation."})

    for doc_id, dtype in doc_type_map.items():
        data = documents.get(doc_id, {})
        desc = json.dumps(data).lower()
        if any(w in desc for w in ("agriculture", "agricultural", "farm", "cultivation", "agri")):
            if "CONVERSION_ORDER" not in doc_types:
                findings.append({"type": "CONVERSION_MISSING", "severity": "high", "doc_ids": [dtype],
                                 "summary": f"RED FLAGS: property is described as agricultural in '{dtype}' but no Conversion Order (NA Order) is present in the bundle. Under Section 95 of the Karnataka Land Revenue Act, 1964, agricultural land must be converted to non-agricultural (NA) use before it can be sold for non-agricultural purposes. Sale of agricultural land without conversion is void.",
                                 "suggestion": "Obtain the NA Conversion Order from the Deputy Commissioner's office under Section 95 of the Karnataka Land Revenue Act, 1964. Verify that the conversion was obtained before the sale deed was executed."})
            break

    if deed_id:
        if "KHATA_CERTIFICATE" not in doc_types and "KHATA_EXTRACT" not in doc_types:
            findings.append({"type": "MISSING_DOCUMENT", "severity": "medium", "doc_ids": [deed_type],
                             "summary": "RED FLAGS: missing Khata Certificate or Khata Extract for the recently transferred property. After a property transfer under the Karnataka Municipal Corporations Act, the Khata (property tax account) must be transferred to the new owner's name through Form 12 or Form 14. Without a Khata, the new owner cannot pay property tax or obtain utilities.",
                             "suggestion": "Apply for Khata transfer at the municipal corporation office with a copy of the registered Sale Deed and the previous Khata."})

    if deed_id and ec_id:
        deed_doc = documents.get(deed_id, {})
        exec_dt = _parse_date(_get(deed_doc, "file_metadata", "execution_date", default=""))
        if exec_dt:
            ec_data = documents.get(ec_id, {})
            ec_end = _parse_date(_get(ec_data, "file_metadata", "search_end_date", default=""))
            if ec_end and exec_dt > ec_end:
                findings.append({"type": "EC_GAP", "severity": "medium", "doc_ids": [deed_type, "ENCUMBRANCE_CERTIFICATE"],
                                 "summary": f"RED FLAGS: {deed_type} execution date ({exec_dt}) is AFTER the EC search period ended ({ec_end}). The Encumbrance Certificate does not cover the period up to the current deed execution, meaning any encumbrances created between the EC end date and the deed date are not reflected in this EC. The current deed transaction itself is also not recorded.",
                                 "suggestion": "Obtain a supplementary EC covering the period from the original EC end date up to the deed execution date to confirm no encumbrances were created. A fresh EC or supplementary EC should confirm the property was free from encumbrances at the time of sale."})

    if deed_id and prc_id:
        deed_doc = documents.get(deed_id, {})
        consideration = _get(deed_doc, "financial_summary", "declared_consideration_amount")
        prc_data = documents.get(prc_id, {})
        gv_value = _get(prc_data, "guidance_value", "value")

        if isinstance(consideration, (int, float)) and isinstance(gv_value, (int, float)) and gv_value > 0:
            if consideration < gv_value * 0.9:
                pct_below = ((gv_value - consideration) / gv_value) * 100
                findings.append({"type": "GUIDANCE_VALUE_ISSUE", "severity": "medium",
                                 "doc_ids": [deed_type, "PROPERTY_REGISTER_CARD"],
                                 "summary": f"RED FLAGS: {deed_type} declared consideration (Rs. {consideration:,}) is below 90% of the PRC guidance value (Rs. {gv_value:,}) — a difference of Rs. {gv_value - consideration:,} ({pct_below:.1f}% below guidance value). Under the Karnataka Stamp Act, 1957, stamp duty is payable on the higher of the declared consideration or the guidance value. If the consideration is significantly below guidance value, the Sub-Registrar may refer the matter for undervaluation proceedings under Section 47A, potentially attracting a penalty of up to 2x the deficit stamp duty.",
                                 "suggestion": "Verify that the consideration correctly reflects the actual sale price. If it is undervalued, consult a legal professional about the risks under Section 47A of the Karnataka Stamp Act. Additional stamp duty and penalty may be payable."})
            elif consideration < gv_value:
                pct_below = ((gv_value - consideration) / gv_value) * 100
                findings.append({"type": "GUIDANCE_VALUE_ISSUE", "severity": "low",
                                 "doc_ids": [deed_type, "PROPERTY_REGISTER_CARD"],
                                 "summary": f"RED FLAGS: {deed_type} declared consideration (Rs. {consideration:,}) is below the PRC guidance value (Rs. {gv_value:,}) but within 90% — a difference of {pct_below:.1f}%. While not severely undervalued, stamp duty will be computed on the higher of the two amounts under the Karnataka Stamp Act.",
                                 "suggestion": "Confirm the guidance value is correctly applied. The stamp duty assessment will use the higher of consideration or guidance value."})

    return findings
