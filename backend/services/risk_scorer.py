"""
Composite risk scoring model for verification findings.
Assigns numeric weights by severity and finding type, computes aggregate score,
and maps score ranges to verdict bands.
"""

from __future__ import annotations

from backend.logger import get_logger

logger = get_logger(__name__)

SEVERITY_WEIGHTS = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

FINDING_WEIGHTS = {
    "OWNERSHIP_GAP": 4,
    "OWNERSHIP_MISMATCH": 4,
    "PENDING_MORTGAGE": 4,
    "UNVERIFIED_SIGNATORY_AUTHORITY": 3,
    "MISSING_SUCCESSION_DOCUMENT": 3,
    "PROPERTY_MISMATCH": 3,
    "RERA_REGISTRATION_UNVERIFIED": 2,
    "DATE_INCONSISTENCY": 2,
    "FINANCIAL_MISMATCH": 2,
    "UNDERVALUATION": 3,
    "EC_GAP": 2,
    "MUTATION_PENDING": 2,
    "CONVERSION_MISSING": 2,
    "TAX_DEFAULT": 2,
    "DOCUMENT_EXPIRY": 1,
    "GUIDANCE_VALUE_ISSUE": 1,
    "MISSING_DOCUMENT": 3,
    "SUSPICIOUS_PATTERN": 2,
    "MISSING_EXPECTED_DOCUMENT": 1,
}

VERDICT_BANDS = [
    (0, 0, "PASS", "No material issues detected."),
    (1, 3, "MANUAL_REVIEW", "Minor or informational findings — review recommended for completeness."),
    (4, 7, "MANUAL_REVIEW", "Moderate risk — several medium-severity issues requiring attention."),
    (8, 12, "FLAGGED", "High risk — at least one critical or multiple high-severity issues requiring action."),
    (13, float("inf"), "FLAGGED", "Very high risk — multiple critical issues. Title likely unmarketable."),
]


def compute_risk_score(findings: list[dict]) -> dict:
    """
    Given a list of findings (each with severity, type, confidence),
    compute a weighted aggregate risk score.

    Returns {
        "risk_score": float,
        "max_possible_score": float,
        "verdict": str,
        "verdict_reason": str,
        "score_breakdown": [
            {"type": str, "severity": str, "weight": int, "score": float, "confidence": float}
        ],
    }
    """
    if not findings:
        return {
            "risk_score": 0,
            "max_possible_score": 0,
            "verdict": "PASS",
            "verdict_reason": "No findings — clean verification.",
            "score_breakdown": [],
        }

    breakdown = []
    total_score = 0.0
    max_possible = 0.0

    for finding in findings:
        severity = (finding.get("severity") or "low").lower()
        ftype = finding.get("type", "UNKNOWN")
        confidence = finding.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)):
            confidence = 0.5

        sev_weight = SEVERITY_WEIGHTS.get(severity, 1)
        find_weight = FINDING_WEIGHTS.get(ftype, 1)

        weighted = sev_weight * find_weight * confidence
        max_weighted = sev_weight * find_weight

        total_score += weighted
        max_possible += max_weighted

        breakdown.append({
            "type": ftype,
            "severity": severity,
            "finding_weight": find_weight,
            "severity_weight": sev_weight,
            "raw_score": round(weighted, 2),
            "max_score": round(max_weighted, 2),
            "confidence": round(confidence, 2),
        })

    # Find matching verdict band
    verdict = "PASS"
    verdict_reason = "No material issues detected."
    for lo, hi, v, reason in VERDICT_BANDS:
        if lo <= total_score <= hi:
            verdict = v
            verdict_reason = reason
            break

    return {
        "risk_score": round(total_score, 2),
        "max_possible_score": round(max_possible, 2),
        "normalized_risk_pct": round((total_score / max_possible * 100) if max_possible > 0 else 0, 1),
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "score_breakdown": breakdown,
        "finding_count": len(findings),
    }
