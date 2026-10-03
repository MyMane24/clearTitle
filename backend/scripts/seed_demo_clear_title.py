"""Seed a single demo case that verifies as CLEAR_TITLE.

The demo property mirrors a real Belagavi parcel (CTS 1360B/9, R.S. 699A/15,
Rani Chennamma Nagar 2nd Stage, Parvati Nagar) with a clean registered chain:
allotment 1993 -> family transfer 2005 -> bank mortgage 2015 (released 2019)
-> final sale to the current owners in July 2019. Nothing after that date.

Idempotent: only rows belonging to DEMO-CLEAR-TITLE are ever touched, so it can
be re-run without affecting any other case.

Usage:  venv\\Scripts\\python.exe backend\\scripts\\seed_demo_clear_title.py
"""

from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("MYSQL_PORT", "3307")

from backend.database.connection import _get_conn  # noqa: E402
from backend.database.repositories.case_repo import (  # noqa: E402
    init_case,
    set_case_status,
    set_case_verification_status,
    update_case_status,
)
from backend.database.repositories.document_repo import (  # noqa: E402
    init_document,
    update_document_status,
)
from backend.database.repositories.title_chain_repo import save_title_chain  # noqa: E402
from backend.database.repositories.verification_results_repo import save_verification_results  # noqa: E402

CASE_ID = "DEMO-CLEAR-TITLE"

BOUNDARIES = {
    "north": "CTS No. 1360B/7",
    "east": "CTS No. 1360B/8",
    "west": "6 M Road",
    "south": "CTS No. 1360B/10",
}
LOCATION = "Rani Chennamma Nagar 2nd Stage, Parvati Nagar, Belagavi 590008"
VISITORS_OLD = "Shantakumar Hiremath"
ANUSUYA = "Anusuya Hiremath"
OWNERS_NEW = ["Prakash Gudage", "Rakshita Gudage"]


def _bundle_cleanup() -> None:
    with _get_conn() as conn:
        cursor = conn.cursor()
        for table in ("title_chains", "verification_results", "documents"):
            cursor.execute(f"DELETE FROM {table} WHERE case_id = '{CASE_ID}'")
        cursor.execute(f"DELETE FROM cases WHERE id = '{CASE_ID}'")
        conn.commit()


def _sd_structured() -> dict:
    return {
        "document_type": "SALE_DEED",
        "file_metadata": {
            "registration_number": "BLG-5-515-2019",
            "execution_date": "2019-07-15",
            "registration_date": "2019-07-15",
            "language": "English",
        },
        "financial_summary": {
            "declared_consideration_amount": "1650000",
            "stamp_duty_paid_amount": "135300",
            "total_registration_fees": "22600",
        },
        "parties": {
            "vendors": [
                {"entity_name": VISITORS_OLD, "represented_by": "Self", "address": "Parvati Nagar, Belagavi"},
                {"entity_name": ANUSUYA, "represented_by": VISITORS_OLD, "address": "Parvati Nagar, Belagavi"},
            ],
            "purchasers": [
                {"entity_name": OWNERS_NEW[0], "represented_by": "Self",
                 "address": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}"},
                {"entity_name": OWNERS_NEW[1], "represented_by": OWNERS_NEW[0],
                 "address": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}"},
            ],
        },
        "property_schedule": {
            "cts_number": "1360B/9",
            "survey_number": "699A/15",
            "plot_or_site_number": "09",
            "project_name": "Rani Chennamma Nagar 2nd Stage",
            "full_schedule_description": f"Plot No. 09, CTS No. 1360B/9, R.S. No. 699A/15, {LOCATION}",
            "measurements": {
                "dimensions_text": "9.14 X 12.19",
                "super_built_up_area_sqft": "1200 sq ft",
                "undivided_share_land_sqft": "1200 sq ft",
                "total_land_area_sqmtr": "111.48",
            },
            "boundaries": dict(BOUNDARIES),
            "intended_usage": "Residential",
        },
    }


def _ec_structured() -> dict:
    def pd():
        return {
            "plot_no": "09",
            "cts_no": "1360B/9",
            "pid_no": "P01000324",
            "description": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}",
            "measurements": {"measurements_text": "9.14 X 12.19"},
            "boundaries": dict(BOUNDARIES),
            "location": LOCATION,
        }

    def parties(vendors, purchasers):
        return {
            "vendors": [{"entity_name": n} for n in vendors],
            "purchasers": [{"entity_name": n} for n in purchasers],
        }

    return {
        "document_type": "ENCUMBRANCE_CERTIFICATE",
        "file_metadata": {
            "certificate_number": "CER-2026-88041",
            "reference_number": "BEL/EC/2026/07712",
            "search_start_date": "1991-01-01",
            "search_end_date": "2026-08-31",
            "search_period_years": "35",
            "digital_signature_by": "Sub-Registrar, Belagavi",
            "issuing_office": "District Registrar, Belagavi",
        },
        "search_criteria": {
            "target_village": "Belagavi City",
            "target_hobli": "Belagavi",
            "target_district": "Belagavi",
            "target_identifiers": {
                "cts_number": "1360B/9",
                "survey_number": "699A/15",
                "converted_survey_number": None,
                "plot_number": "09",
            },
        },
        "historical_ledger": [
            {
                "transaction_index": 1,
                "execution_date": "1993-05-12",
                "registration_reference": "KV-1-34-93",
                "transaction_type": "sale",
                "share_fraction": "Full",
                "is_agreement_to_sell": False,
                "minor_or_legal_heir_party": False,
                "financials": {"consideration_amount": "150000", "market_value": "150000"},
                "parties": parties(["K.U.D.C. Belagavi"], ["Basavaraj Hiremath"]),
                "property_details": pd(),
            },
            {
                "transaction_index": 2,
                "execution_date": "2005-11-21",
                "registration_reference": "BLG-2-394-2005",
                "transaction_type": "sale",
                "share_fraction": "Full",
                "is_agreement_to_sell": False,
                "minor_or_legal_heir_party": False,
                "financials": {"consideration_amount": "400000", "market_value": "400000"},
                "parties": parties(["Basavaraj Hiremath"], [VISITORS_OLD, ANUSUYA]),
                "property_details": pd(),
            },
            {
                "transaction_index": 3,
                "execution_date": "2015-03-11",
                "registration_reference": "DTD-1-88-2015",
                "transaction_type": "deposit of title deeds (mortgage)",
                "share_fraction": "Full",
                "is_agreement_to_sell": False,
                "minor_or_legal_heir_party": False,
                "financials": {"consideration_amount": "1200000", "market_value": "1200000"},
                "parties": parties([VISITORS_OLD, ANUSUYA], ["Karnataka Bank Ltd."]),
                "property_details": pd(),
            },
            {
                "transaction_index": 4,
                "execution_date": "2019-04-30",
                "registration_reference": "BLG-4-221-2019",
                "transaction_type": "release of mortgage (satisfaction)",
                "share_fraction": "Full",
                "is_agreement_to_sell": False,
                "minor_or_legal_heir_party": False,
                "financials": {},
                "parties": parties(["Karnataka Bank Ltd."], [VISITORS_OLD, ANUSUYA]),
                "property_details": pd(),
            },
            {
                "transaction_index": 5,
                "execution_date": "2019-07-15",
                "registration_reference": "BLG-5-515-2019",
                "transaction_type": "sale",
                "share_fraction": "Full",
                "is_agreement_to_sell": False,
                "minor_or_legal_heir_party": False,
                "financials": {"consideration_amount": "1650000", "market_value": "1650000"},
                "parties": parties([VISITORS_OLD, ANUSUYA], OWNERS_NEW),
                "property_details": pd(),
            },
        ],
    }


def _khata_structured() -> dict:
    return {
        "document_type": "KHATA",
        "file_metadata": {
            "form_number": "Nomune 2",
            "khata_number": "KH-724000-009",
            "khata_type": "A",
            "issuing_authority": "Belagavi Mahanagara Palike",
            "issue_date": "2026-08-10",
            "ward_or_zone": "13",
            "pid": "P01000324",
        },
        "property_details": {
            "pid": "P01000324",
            "property_number": "724000-009",
            "old_assessment_number": "10015",
            "survey_number": "699A/15",
            "cts_number": "1360B/9",
            "plot_or_site_number": "09",
            "locality": LOCATION,
            "property_type": "Residential",
            "area_sq_meters": 111.48,
            "built_up_area_sq_meters": 111.48,
            "boundaries": dict(BOUNDARIES),
        },
        "khata_holders": [
            {"name": OWNERS_NEW[0], "father_or_husband_name": "Suresh Gudage", "share": "1/2",
             "address": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}"},
            {"name": OWNERS_NEW[1], "father_or_husband_name": "Prakash Gudage", "share": "1/2",
             "address": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}"},
        ],
        "property_tax": {
            "assessment_year": "2026-27",
            "annual_tax_amount": "4155",
            "tax_paid_up_to": "31-03-2026",
            "dues_or_arrears": None,
        },
        "certification": {
            "signed_by": "Assistant Revenue Officer",
            "designation": "Assistant Revenue Officer, Ward 13",
            "issue_date": "2026-08-10",
            "office": "Belagavi Mahanagara Palike",
        },
    }


def _title_chain() -> tuple[list, dict]:
    def entry(idx, role, date, ref, ttype, vendors, purchasers, graph_from, consider=None,
              edge="CONVEYANCE", **extra):
        e = {
            "transaction_index": idx,
            "execution_date": date,
            "registration_reference": ref,
            "transaction_type": ttype,
            "share_fraction": "Full",
            "is_agreement_to_sell": False,
            "minor_or_legal_heir_party": False,
            "financials": {"consideration_amount": consider} if consider else {},
            "parties": {
                "vendors": [{"entity_name": n} for n in vendors],
                "purchasers": [{"entity_name": n} for n in purchasers],
            },
            "property_details": {
                "plot_no": "09",
                "cts_no": "1360B/9",
                "description": f"Plot No. 09, CTS No. 1360B/9, {LOCATION}",
                "measurements": {"measurements_text": "9.14 X 12.19"},
                "boundaries": dict(BOUNDARIES),
                "location": LOCATION,
            },
            "chain_role": role,
            "is_sale_deed_entry": role == "THE_SD",
            "is_title_transfer": role != "ENCUMBRANCE",
            "portion": "Full",
            "property_identity": "CTS 1360B/9",
            "edge_type": edge,
            "graph_from": graph_from,
        }
        e.update(extra)
        return e

    chain = [
        entry(1, "PREDECESSOR_TITLE", "1993-05-12", "KV-1-34-93", "sale",
              ["K.U.D.C. Belagavi"], ["Basavaraj Hiremath"], None, "150000",
              explanation="Allotment by the urban authority to the original grantee."),
        entry(2, "PREDECESSOR_TITLE", "2005-11-21", "BLG-2-394-2005", "sale",
              ["Basavaraj Hiremath"], [VISITORS_OLD, ANUSUYA], 1, "400000",
              explanation="Registered transfer of the full plot to the 2019 vendors."),
        entry(3, "ENCUMBRANCE", "2015-03-11", "DTD-1-88-2015", "deposit of title deeds (mortgage)",
              [VISITORS_OLD, ANUSUYA], ["Karnataka Bank Ltd."], 2, "1200000", edge="SECURITY",
              explanation="Bank mortgage by deposit of title deeds; fully released before the sale."),
        entry(4, "ENCUMBRANCE", "2019-04-30", "BLG-4-221-2019", "release of mortgage (satisfaction)",
              ["Karnataka Bank Ltd."], [VISITORS_OLD, ANUSUYA], 3, edge="RELEASE",
              explanation="Satisfaction of the 2015 mortgage — no charge remains on the property."),
        entry(5, "THE_SD", "2019-07-15", "BLG-5-515-2019", "sale",
              [VISITORS_OLD, ANUSUYA], OWNERS_NEW, 2, "1650000",
              explanation="The Sale Deed: transfers the cleared property to the current owners."),
    ]
    source = {
        "sale_deed_doc_id": "DEMO-SD",
        "ec_doc_id": "DEMO-EC",
        "sd_property": {"cts_number": "1360B/9", "survey_number": "699A/15", "plot_number": "09"},
        "title_story": (
            "The registered history for CTS 1360B/9 is clean: allotment in 1993, a single "
            "family transfer in 2005, a Karnataka Bank mortgage in 2015 that was fully released "
            "in 2019, and the final sale to Prakash and Rakshita Gudage in July 2019. No "
            "transaction after the Sale Deed date. The title is clear and marketable."
        ),
        "required_documents": [],
        "input_fingerprint": "demo-seed-fingerprint",
    }
    return chain, source


def _verification() -> tuple[dict, list]:
    def v(field, sd, ec, khata, status="VERIFIED", notes="Values agree and no problem is described in the notes."):
        return {"field": field, "sd_value": sd, "ec_value": ec, "khata_value": khata,
                "status": status, "notes": notes}

    items = [
        v("Property survey/CTS number",
          "CTS 1360B/9, R.S. 699A/15", "CTS 1360B/9", "CTS 1360B/9, R.S. 699A/15",
          notes="Identifier matches across all three documents."),
        v("Property locality",
          LOCATION, LOCATION, LOCATION,
          notes="Locality matches on every document."),
        v("Execution/registration date",
          "15/07/2019 (BLG-5-515-2019)", "15/07/2019 (BLG-5-515-2019)", "Not found in Khata",
          notes="The Sale Deed execution is recorded at ledger transaction 5."),
        v("Vendors (prior chain)",
          "Shantakumar Hiremath & Anusuya Hiremath", "Same owners since 2005", None,
          notes="The vendors were the registered purchasers of the 2005 sale — chain is complete."),
        v("Purchasers (current owners)",
          "Prakash Gudage & Rakshita Gudage", "Prakash Gudage & Rakshita Gudage (tx 5)",
          "Prakash Gudage & Rakshita Gudage",
          notes="The SD purchasers hold the khata — mutation is recorded."),
        v("Consideration amount",
          "₹ 16,50,000", "₹ 16,50,000", "Not found in Khata",
          notes="Consideration matches the EC ledger."),
        v("Subsequent encumbrance after SD date",
          "None", "No transaction after 15/07/2019", None,
          notes="EC search runs to 31/08/2026 and shows nothing after the sale."),
        v("Khata holder / mutation",
          "Prakash Gudage & Rakshita Gudage", None, "Prakash Gudage & Rakshita Gudage (A-Khata)",
          notes="Khata stands in the purchasers' names — the sale is mutated."),
        v("Khata type & tax dues",
          None, None, "A-Khata (Nomune 2), tax paid to 31-03-2026, no arrears",
          notes="Authorised A-Khata; no pending municipal dues."),
        v("Land area (dimensions vs declared)",
          "9.14 X 12.19 m", None, None,
          notes="Dimensions product 111.42 sq m matches declared 111.48 sq m (within 5%)."),
        v("Land area (SD vs EC)",
          "111.48 sq m (1200 sq ft)", "1200 sq ft", None,
          notes="SD and EC agree — 1200 sq ft = 111.48 sq m."),
        v("Land area (SD vs Khata)",
          "111.48 sq m", None, "111.48 sq m",
          notes="SD and Khata agree in square metres."),
        v("Boundaries (SD vs EC)",
          "N: 1360B/7, E: 1360B/8, W: 6 M Road, S: 1360B/10", "N: 1360B/7, E: 1360B/8, W: 6 M Road, S: 1360B/10", None,
          notes="All four sides agree."),
        v("Boundaries (SD vs Khata)",
          "N: 1360B/7, E: 1360B/8, W: 6 M Road, S: 1360B/10", None, "N: 1360B/7, E: 1360B/8, W: 6 M Road, S: 1360B/10",
          notes="All four sides agree."),
    ]
    summary = {
        "counts": {"VERIFIED": len(items), "FLAG": 0, "NEEDS_REVIEW": 0, "N/A": 0},
        "total": len(items),
        "verified_share": 1.0,
        "verdict": "CLEAR_TITLE",
        "status_line": "VERIFICATION COMPLETED, TITLE IS CLEAR",
        "headline": (
            "TITLE IS CLEAR — Plot 09, CTS 1360B/9, Parvati Nagar matches the EC "
            "history and the A-Khata in the purchasers' names. The last registered "
            "transaction is the 15 Jul 2019 sale; nothing follows it."
        ),
        "summary_text": (
            "The Sale Deed was checked against the 35-year EC ledger and the Belagavi "
            "A-Khata. All identifiers — survey, CTS, plot number and locality — agree, "
            "as do the purchasers, who hold the khata, and the consideration of "
            "₹ 16,50,000. The bank mortgage of 2015 (Deposit of Title Deeds) was fully "
            "released on 30 Apr 2019, before the sale closed.\n\n"
            "The area is consistent across all documents: dimensions 9.14 x 12.19 m "
            "equate to 111.42 sq m ≈ 1200 sq ft, matching the declared 111.48 sq m, and "
            "all four boundary descriptions agree. The EC search runs to 31 Aug 2026 and "
            "records no transaction after 15 Jul 2019.\n\n"
            "No discrepancy, gap, or liability remains for the buyer. The title is "
            "clear and marketable as it stands."
        ),
        "overall_comment": (
            "The title to Plot No. 09, CTS No. 1360B/9, R.S. No. 699A/15, Rani Chennamma "
            "Nagar 2nd Stage, Parvati Nagar, Belagavi is clear and marketable. The chain is "
            "complete from the 1993 allotment through the 2019 sale; the 2015 mortgage stands "
            "released. All field checks — identifiers, parties, area, boundaries and khata — "
            "are VERIFIED. No further action is required."
        ),
    }
    return summary, items


def main() -> None:
    _bundle_cleanup()

    init_case(case_id=CASE_ID, total_docs=3, user_id=None)
    for doc_id, idx, filename, doc_type, sd in (
        ("DEMO-SD", 0, "DEMO_SaleDeed_2019-07-15.pdf", "SALE_DEED", _sd_structured()),
        ("DEMO-EC", 1, "DEMO_EC_1991-2026.pdf", "ENCUMBRANCE_CERTIFICATE", _ec_structured()),
        ("DEMO-KHATA", 2, "DEMO_Khata_2026-08-10.pdf", "KHATA", _khata_structured()),
    ):
        init_document(case_id=CASE_ID, doc_id=doc_id, doc_index=idx,
                      filename=filename, expected_type=doc_type)
        update_document_status(
            case_id=CASE_ID, doc_id=doc_id, status="structured",
            document_type=doc_type, structured_data=sd,
            page_count=5, input_tokens=8400, output_tokens=2100,
            latency_ms=63000, cost_usd=0.0321, model_used="gemini-2.0-flash",
        )

    update_case_status(case_id=CASE_ID)
    set_case_status(case_id=CASE_ID, status="complete")

    chain, source = _title_chain()
    save_title_chain(case_id=CASE_ID, status="complete", chain=chain, source=source)

    summary, items = _verification()
    save_verification_results(
        case_id=CASE_ID, status="complete", verdict="CLEAR_TITLE",
        summary=summary, items=items,
    )
    set_case_verification_status(case_id=CASE_ID, verification_status="complete", verdict="CLEAR_TITLE")

    print(f"Seeded {CASE_ID}: case complete, {len(items)}/{len(items)} checks CLEAR_TITLE")


if __name__ == "__main__":
    main()