"""
Evaluation runner for verification system improvements.
Compares system output against hand-labeled ground-truth findings.
Run: python -m backend.services.eval_runner
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.logger import get_logger
from backend.services.risk_scorer import compute_risk_score
from backend.services.cross_doc_verifier import (
    _check_chain_of_title_years,
    _check_authority_to_sign,
    _check_inheritance_succession,
    _check_valuation_consistency,
    _check_rera_applicability,
    _check_document_recency,
    _check_expected_missing_docs,
    _detect_property_type,
)

logger = get_logger(__name__)

# ── Ground-truth test cases ─────────────────────────────────────────────
# Each test case has: documents, expected findings (type + severity + count)

GROUND_TRUTH_CASES = [
    {
        "id": "case_01_clean_sale",
        "description": "Clean Sale Deed + EC with no issues",
        "documents": [
            {
                "document_type": "SALE_DEED",
                "structured_json": {
                    "file_metadata": {
                        "registration_number": "KRM-1-123-2023",
                        "execution_date": "2023-01-15",
                        "registration_date": "2023-01-20",
                        "issuing_office": "Koramangala SRO",
                    },
                    "financial_summary": {
                        "declared_consideration_amount": 5000000,
                        "stamp_duty_paid_amount": 350000,
                    },
                    "parties": {
                        "vendors": [{"entity_name": "Rajesh Kumar", "represented_by": None, "address": "Bangalore"}],
                        "purchasers": [{"entity_name": "Priya Sharma", "represented_by": None, "address": "Bangalore"}],
                    },
                    "property_schedule": {
                        "cts_number": "CTS-1234",
                        "survey_number": "SN-567",
                        "full_schedule_description": "Residential property",
                        "measurements": {"total_land_area_sqmtr": 500},
                        "intended_usage": "Residential",
                    },
                    "statutory_valuation_endorsement": {
                        "estimated_market_value": 4800000,
                        "prevention_of_undervaluation_referred": False,
                    },
                },
                "verification_notes": [],
            },
            {
                "document_type": "ENCUMBRANCE_CERTIFICATE",
                "structured_json": {
                    "file_metadata": {
                        "search_start_date": "2000-01-01",
                        "search_end_date": "2023-01-15",
                        "search_period_years": 23,
                    },
                    "historical_ledger": [
                        {
                            "transaction_index": 1,
                            "execution_date": "2015-06-10",
                            "registration_reference": "KRM-1-456-2015",
                            "transaction_type": "SALE",
                            "financials": {"consideration_amount": 3000000, "market_value": 3100000},
                            "parties": {"vendors": ["Anil Gupta"], "purchasers": ["Rajesh Kumar"]},
                        },
                        {
                            "transaction_index": 2,
                            "execution_date": "2023-01-15",
                            "registration_reference": "KRM-1-123-2023",
                            "transaction_type": "SALE",
                            "financials": {"consideration_amount": 5000000, "market_value": 4800000},
                            "parties": {"vendors": ["Rajesh Kumar"], "purchasers": ["Priya Sharma"]},
                        },
                    ],
                },
                "verification_notes": [],
            },
            {
                "document_type": "PROPERTY_REGISTER_CARD",
                "structured_json": {
                    "guidance_value": {"value": 4800000, "order_number": "GV/2023/456", "order_date": "2023-06-01"},
                    "holders": [{"name": "Priya Sharma", "share": "1/1"}],
                },
                "verification_notes": [],
            },
        ],
        "expected_findings": [
            {"type": "EC_GAP", "severity": "low", "min_count": 1},  # chain of title < 30 years
            {"type": "MISSING_EXPECTED_DOCUMENT", "severity": "medium", "min_count": 1},  # missing khata etc
        ],
        "max_unexpected_findings": 2,
    },
    {
        "id": "case_02_sale_with_mortgage",
        "description": "Sale Deed + EC with pending mortgage",
        "documents": [
            {
                "document_type": "SALE_DEED",
                "structured_json": {
                    "file_metadata": {
                        "registration_number": "KRM-2-789-2024",
                        "execution_date": "2024-03-01",
                        "registration_date": "2024-03-05",
                        "issuing_office": "Koramangala SRO",
                    },
                    "financial_summary": {
                        "declared_consideration_amount": 8000000,
                        "stamp_duty_paid_amount": 560000,
                    },
                    "parties": {
                        "vendors": [{"entity_name": "ABC Developers Pvt Ltd", "represented_by": None, "address": "Bangalore"}],
                        "purchasers": [{"entity_name": "Suresh Reddy", "represented_by": None, "address": "Bangalore"}],
                    },
                    "property_schedule": {
                        "cts_number": "CTS-5678",
                        "survey_number": "SN-890",
                        "full_schedule_description": "Apartment in Green Valley Project",
                        "project_name": "Green Valley",
                        "intended_usage": "Apartment",
                    },
                },
                "verification_notes": [],
            },
            {
                "document_type": "ENCUMBRANCE_CERTIFICATE",
                "structured_json": {
                    "file_metadata": {
                        "search_start_date": "2010-01-01",
                        "search_end_date": "2024-03-01",
                        "search_period_years": 14,
                    },
                    "historical_ledger": [
                        {
                            "transaction_index": 1,
                            "execution_date": "2019-08-15",
                            "registration_reference": "KRM-1-901-2019",
                            "transaction_type": "MORTGAGE",
                            "financials": {"consideration_amount": 5000000},
                            "parties": {"vendors": ["ABC Developers Pvt Ltd"], "purchasers": ["HDFC Bank"]},
                            "property_details": {"description": "Green Valley Project"},
                        },
                        {
                            "transaction_index": 2,
                            "execution_date": "2024-03-01",
                            "registration_reference": "KRM-2-789-2024",
                            "transaction_type": "SALE",
                            "financials": {"consideration_amount": 8000000, "market_value": 9000000},
                            "parties": {"vendors": ["ABC Developers Pvt Ltd"], "purchasers": ["Suresh Reddy"]},
                            "property_details": {"description": "Unit in Green Valley"},
                        },
                    ],
                },
                "verification_notes": [],
            },
        ],
        "expected_findings": [
            {"type": "EC_GAP", "severity": "low", "min_count": 1},
            {"type": "MISSING_EXPECTED_DOCUMENT", "severity": "medium", "min_count": 1},
            {"type": "RERA_REGISTRATION_UNVERIFIED", "severity": "medium", "min_count": 1},
            {"type": "UNDERVALUATION", "severity": "medium", "min_count": 1},
            {"type": "UNVERIFIED_SIGNATORY_AUTHORITY", "severity": "high", "min_count": 1},  # corporate seller without authority
        ],
        "max_unexpected_findings": 3,
    },
    {
        "id": "case_03_inheritance_gap",
        "description": "EC shows inheritance transfer without succession document",
        "documents": [
            {
                "document_type": "SALE_DEED",
                "structured_json": {
                    "file_metadata": {
                        "registration_number": "KRM-3-456-2024",
                        "execution_date": "2024-06-01",
                        "registration_date": "2024-06-10",
                    },
                    "financial_summary": {"declared_consideration_amount": 3000000, "stamp_duty_paid_amount": 210000},
                    "parties": {
                        "vendors": [{"entity_name": "Meena Devi"}],
                        "purchasers": [{"entity_name": "Arun Patel"}],
                    },
                    "property_schedule": {
                        "cts_number": "CTS-9012",
                        "survey_number": "SN-345",
                        "intended_usage": "Residential",
                    },
                },
                "verification_notes": [],
            },
            {
                "document_type": "ENCUMBRANCE_CERTIFICATE",
                "structured_json": {
                    "file_metadata": {
                        "search_start_date": "1995-01-01",
                        "search_end_date": "2024-06-01",
                        "search_period_years": 29,
                    },
                    "historical_ledger": [
                        {
                            "transaction_index": 1,
                            "execution_date": "1998-03-20",
                            "transaction_type": "SALE",
                            "parties": {"vendors": ["Original Owner"], "purchasers": ["Krishna Devi"]},
                        },
                        {
                            "transaction_index": 2,
                            "execution_date": "2023-11-15",
                            "transaction_type": "INHERITANCE — BY DEATH",
                            "parties": {"vendors": ["Krishna Devi (Deceased)"], "purchasers": ["Meena Devi (Legal Heir)"]},
                        },
                        {
                            "transaction_index": 3,
                            "execution_date": "2024-06-01",
                            "transaction_type": "SALE",
                            "parties": {"vendors": ["Meena Devi"], "purchasers": ["Arun Patel"]},
                        },
                    ],
                },
                "verification_notes": [],
            },
            {
                "document_type": "PROPERTY_REGISTER_CARD",
                "structured_json": {
                    "guidance_value": {"value": 2800000, "order_number": "GV/2023/789", "order_date": "2023-06-01"},
                    "holders": [{"name": "Arun Patel", "share": "1/1"}],
                },
                "verification_notes": [],
            },
        ],
        "expected_findings": [
            {"type": "MISSING_SUCCESSION_DOCUMENT", "severity": "high", "min_count": 1},
            {"type": "MISSING_EXPECTED_DOCUMENT", "severity": "medium", "min_count": 1},
        ],
        "max_unexpected_findings": 3,
    },
    {
        "id": "case_04_undervaluation_red_flag",
        "description": "Sale Deed with declared consideration far below guidance value",
        "documents": [
            {
                "document_type": "SALE_DEED",
                "structured_json": {
                    "file_metadata": {
                        "registration_number": "KRM-4-111-2024",
                        "execution_date": "2024-02-01",
                        "registration_date": "2024-02-10",
                    },
                    "financial_summary": {"declared_consideration_amount": 1000000, "stamp_duty_paid_amount": 70000},
                    "parties": {
                        "vendors": [{"entity_name": "Ramesh Hegde"}],
                        "purchasers": [{"entity_name": "Kavita Nair"}],
                    },
                    "property_schedule": {"cts_number": "CTS-3456", "survey_number": "SN-789", "intended_usage": "Residential"},
                    "statutory_valuation_endorsement": {"estimated_market_value": 5000000, "prevention_of_undervaluation_referred": True},
                },
                "verification_notes": [],
            },
            {
                "document_type": "ENCUMBRANCE_CERTIFICATE",
                "structured_json": {
                    "file_metadata": {
                        "search_start_date": "2010-01-01",
                        "search_end_date": "2024-02-01",
                        "search_period_years": 14,
                    },
                    "historical_ledger": [],
                },
                "verification_notes": [],
            },
            {
                "document_type": "PROPERTY_REGISTER_CARD",
                "structured_json": {
                    "guidance_value": {"value": 4500000, "order_number": "GV/2023/101", "order_date": "2023-01-01"},
                    "holders": [{"name": "Ramesh Hegde", "share": "1/1"}],
                },
                "verification_notes": [],
            },
        ],
        "expected_findings": [
            {"type": "UNDERVALUATION", "severity": "high", "min_count": 1},
            {"type": "MISSING_EXPECTED_DOCUMENT", "severity": "medium", "min_count": 1},
        ],
        "max_unexpected_findings": 3,
    },
    {
        "id": "case_05_stale_ec",
        "description": "EC search end date > 1 year old",
        "documents": [
            {
                "document_type": "SALE_DEED",
                "structured_json": {
                    "file_metadata": {
                        "registration_number": "KRM-5-222-2024",
                        "execution_date": "2024-08-01",
                        "registration_date": "2024-08-05",
                    },
                    "financial_summary": {"declared_consideration_amount": 6000000, "stamp_duty_paid_amount": 420000},
                    "parties": {
                        "vendors": [{"entity_name": "Vishal Jain"}],
                        "purchasers": [{"entity_name": "Ananya Rao"}],
                    },
                    "property_schedule": {"cts_number": "CTS-7777", "survey_number": "SN-888", "intended_usage": "Residential"},
                },
                "verification_notes": [],
            },
            {
                "document_type": "ENCUMBRANCE_CERTIFICATE",
                "structured_json": {
                    "file_metadata": {
                        "search_start_date": "2020-01-01",
                        "search_end_date": "2023-01-15",
                        "search_period_years": 3,
                    },
                    "historical_ledger": [],
                },
                "verification_notes": [],
            },
        ],
        "expected_findings": [
            {"type": "DOCUMENT_EXPIRY", "severity": "medium", "min_count": 1},
            {"type": "EC_GAP", "severity": "medium", "min_count": 1},  # search period < 13 years
            {"type": "MISSING_EXPECTED_DOCUMENT", "severity": "medium", "min_count": 1},  # no PRC
        ],
        "max_unexpected_findings": 3,
    },
]


def run_eval() -> dict:
    """
    Run all test cases against deterministic checks and report precision/recall.
    Returns summary metrics.
    """
    results = []
    all_expected = defaultdict(int)
    all_found = defaultdict(int)
    all_true_positives = defaultdict(int)
    total_findings_expected = 0
    total_findings_found = 0

    for case in GROUND_TRUTH_CASES:
        case_id = case["id"]
        docs = case["documents"]
        expected = case["expected_findings"]
        property_type = _detect_property_type(docs)

        # Run deterministic checks
        findings = []
        findings.extend(_check_chain_of_title_years(docs))
        findings.extend(_check_authority_to_sign(docs))
        findings.extend(_check_inheritance_succession(docs))
        findings.extend(_check_valuation_consistency(docs))
        findings.extend(_check_rera_applicability(docs, property_type))
        findings.extend(_check_document_recency(docs))
        findings.extend(_check_expected_missing_docs(docs, property_type))

        # Evaluate
        case_metrics = {"id": case_id, "description": case["description"], "metrics": {}}

        # Compare expected vs actual
        expected_by_type = defaultdict(int)
        for exp in expected:
            expected_by_type[(exp["type"], exp["severity"])] += exp.get("min_count", 1)

        found_by_type = defaultdict(int)
        for f in findings:
            found_by_type[(f["type"], f["severity"])] += 1
            all_found[f["type"]] += 1
            total_findings_found += 1

        case_true_positives = 0
        case_false_positives = 0
        case_false_negatives = 0

        for (ftype, fsev), exp_count in expected_by_type.items():
            found_count = found_by_type.get((ftype, fsev), 0)
            tp = min(found_count, exp_count)
            fn = max(0, exp_count - found_count)
            case_true_positives += tp
            case_false_negatives += fn
            all_true_positives[ftype] += tp
            all_expected[ftype] += exp_count

        for (ftype, fsev), found_count in found_by_type.items():
            exp_count = expected_by_type.get((ftype, fsev), 0)
            fp = max(0, found_count - exp_count)
            case_false_positives += fp

        case_precision = case_true_positives / (case_true_positives + case_false_positives) if (case_true_positives + case_false_positives) > 0 else 0
        case_recall = case_true_positives / (case_true_positives + case_false_negatives) if (case_true_positives + case_false_negatives) > 0 else 0
        case_f1 = 2 * (case_precision * case_recall) / (case_precision + case_recall) if (case_precision + case_recall) > 0 else 0

        case_metrics["metrics"] = {
            "true_positives": case_true_positives,
            "false_positives": case_false_positives,
            "false_negatives": case_false_negatives,
            "precision": round(case_precision, 3),
            "recall": round(case_recall, 3),
            "f1_score": round(case_f1, 3),
            "total_findings": len(findings),
            "max_unexpected": case.get("max_unexpected_findings", 99),
            "unexpected_ok": case_false_positives <= case.get("max_unexpected_findings", 99),
        }
        results.append(case_metrics)

        total_findings_expected += sum(e.get("min_count", 1) for e in expected)

    # Aggregate metrics
    total_tp = sum(r["metrics"]["true_positives"] for r in results)
    total_fp = sum(r["metrics"]["false_positives"] for r in results)
    total_fn = sum(r["metrics"]["false_negatives"] for r in results)

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    overall_f1 = 2 * (overall_precision * overall_recall) / (overall_precision + overall_recall) if (overall_precision + overall_recall) > 0 else 0

    # Per-finding-type breakdown
    type_metrics = {}
    for ftype, expected_count in all_expected.items():
        found_count = all_found.get(ftype, 0)
        tp = all_true_positives.get(ftype, 0)
        precision = tp / (tp + max(0, found_count - tp)) if found_count > 0 else 0
        recall = tp / expected_count if expected_count > 0 else 0
        type_metrics[ftype] = {
            "expected": expected_count,
            "found": found_count,
            "true_positives": tp,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
        }

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_cases": len(GROUND_TRUTH_CASES),
        "total_expected_findings": total_findings_expected,
        "total_found_findings": total_findings_found,
        "overall_precision": round(overall_precision, 3),
        "overall_recall": round(overall_recall, 3),
        "overall_f1_score": round(overall_f1, 3),
        "per_finding_type": type_metrics,
        "case_results": results,
        "passed": all(r["metrics"]["unexpected_ok"] for r in results),
    }

    return summary


def print_summary(summary: dict):
    """Print eval summary to stdout."""
    print("=" * 70)
    print(f"VERIFICATION SYSTEM EVALUATION — {summary['timestamp']}")
    print("=" * 70)
    print(f"Total Test Cases: {summary['total_cases']}")
    print(f"Total Expected Findings: {summary['total_expected_findings']}")
    print(f"Total Found Findings: {summary['total_found_findings']}")
    print(f"")
    print(f"Overall Precision: {summary['overall_precision']:.3f}")
    print(f"Overall Recall:    {summary['overall_recall']:.3f}")
    print(f"Overall F1 Score:  {summary['overall_f1_score']:.3f}")
    print(f"Status: {'PASS' if summary['passed'] else 'FAIL'}")
    print("")
    print("Per-Finding-Type Metrics:")
    print("-" * 70)
    print(f"{'Type':<30} {'Exp':<6} {'Found':<6} {'TP':<6} {'Prec':<8} {'Recall':<8}")
    print("-" * 70)
    for ftype, metrics in sorted(summary["per_finding_type"].items()):
        print(f"{ftype:<30} {metrics['expected']:<6} {metrics['found']:<6} "
              f"{metrics['true_positives']:<6} {metrics['precision']:<8} {metrics['recall']:<8}")
    print("")
    print("Per-Case Results:")
    print("-" * 70)
    for case in summary["case_results"]:
        m = case["metrics"]
        status = "+" if m["unexpected_ok"] else "-"
        print(f"{status} {case['id']:<25} P={m['precision']:.3f} R={m['recall']:.3f} "
              f"F1={m['f1_score']:.3f} TP={m['true_positives']} FP={m['false_positives']} "
              f"FN={m['false_negatives']} max_unexp={m['max_unexpected']}")
    print("=" * 70)


if __name__ == "__main__":
    summary = run_eval()
    print_summary(summary)
