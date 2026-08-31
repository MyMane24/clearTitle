"""Cross-document verification (SD source of truth vs EC ledger).

One LLM field-verification pass returns VERIFIED / NOT_VERIFIED / N/A items.
Code validates the enums, summarizes, and persists.
"""

from __future__ import annotations

import json

from backend.database.repositories.case_repo import set_case_verification_status
from backend.database.repositories.document_repo import get_case_bundle
from backend.database.repositories.verification_results_repo import save_verification_results
from backend.integrations.llm.analysis_executor import run_analysis
from backend.logger import get_logger
from backend.prompts.loader import load_prompt, load_schema
from backend.shared.constants import ENCUMBRANCE_CERTIFICATE, SALE_DEED

logger = get_logger(__name__)

VERIFICATION_STATUSES = {"VERIFIED", "NOT_VERIFIED", "N/A"}

VERIFY_RESPONSE_SCHEMA = load_schema("verification_schema")
_VERIFY_PROMPT_TEMPLATE = load_prompt("verification")


def _is_ec(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == ENCUMBRANCE_CERTIFICATE


def _is_sale_deed(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == SALE_DEED


def _summarize(items: list[dict]) -> dict:
    counts = {s: 0 for s in VERIFICATION_STATUSES}
    for item in items:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    total = sum(counts.values())
    verified_share = counts["VERIFIED"] / total if total else 0.0
    verdict = "VERIFIED" if counts["NOT_VERIFIED"] == 0 and counts["VERIFIED"] > 0 else "NOT_VERIFIED"
    if counts["VERIFIED"] == 0:
        verdict = "NOT_VERIFIED" if counts["NOT_VERIFIED"] > 0 else "N/A"
    return {
        "counts": counts,
        "total": total,
        "verified_share": round(verified_share, 2),
        "verdict": verdict,
    }


def verify_case(case_id: str) -> dict:
    """Run the verification pass and persist results."""
    bundle = get_case_bundle(case_id)
    sale_deed = next((d for d in bundle if _is_sale_deed(d)), None)
    ec = next((d for d in bundle if _is_ec(d)), None)

    if not sale_deed or not ec:
        msg = "Verification skipped: need both SALE_DEED and ENCUMBRANCE_CERTIFICATE"
        logger.warning("Verification for case %s: %s", case_id, msg)
        save_verification_results(
            case_id=case_id, status="skipped", verdict="N/A",
            summary={"note": msg}, items=[],
        )
        return {"case_id": case_id, "status": "skipped", "verdict": "N/A"}

    sd_data = sale_deed.get("structured_json") or {}
    ec_data = ec.get("structured_json") or {}
    ledger = ec_data.get("historical_ledger") or []

    prompt = (
        _VERIFY_PROMPT_TEMPLATE + "\n\n"
        "--- SALE DEED ---\n"
        f"{json.dumps(sd_data, ensure_ascii=False, default=str)}\n\n"
        "--- EC HISTORICAL LEDGER ---\n"
        f"{json.dumps(ledger, ensure_ascii=False, default=str)}"
    )

    try:
        response = run_analysis(prompt, task="verification", response_schema=VERIFY_RESPONSE_SCHEMA)
    except Exception as e:
        logger.error("Verification LLM call failed for case %s: %s", case_id, e)
        save_verification_results(
            case_id=case_id, status="error", verdict="N/A",
            summary={"error": str(e)}, items=[],
        )
        return {"case_id": case_id, "status": "error", "verdict": "N/A", "error": str(e)}

    result = response.get("result", {})

    items = []
    for raw in result.get("items") or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "N/A")).upper()
        if status not in VERIFICATION_STATUSES:
            status = "N/A"
        items.append({
            "field": raw.get("field"),
            "sd_value": raw.get("sd_value"),
            "ec_value": raw.get("ec_value"),
            "status": status,
            "notes": raw.get("notes"),
        })

    summary = _summarize(items)
    summary["overall_comment"] = result.get("overall_comment")
    summary["headline"] = result.get("headline")
    summary["summary_text"] = result.get("summary")
    verdict = summary["verdict"]

    save_verification_results(
        case_id=case_id, status="complete", verdict=verdict,
        summary=summary, items=items,
    )

    set_case_verification_status(case_id=case_id, verification_status="complete", verdict=verdict)

    logger.info("Verification complete for case %s: verdict=%s (%d items)",
                case_id, verdict, len(items))
    return {"case_id": case_id, "status": "complete", "verdict": verdict, "items": items, "summary": summary}
