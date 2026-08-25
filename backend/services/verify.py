"""Cross-document verification (SD source of truth vs EC ledger).

One LLM field-verification pass returns VERIFIED / NOT_VERIFIED / N/A items.
Code validates the enums, summarizes, and persists.
"""

from __future__ import annotations

import json

from backend.config import GEMINI_MODEL
from backend.database.repositories.case_repo import set_case_verification_status
from backend.database.repositories.document_repo import get_case_bundle
from backend.database.repositories.verification_results_repo import save_verification_results
from backend.integrations.llm.analysis_executor import run_analysis
from backend.logger import get_logger
from backend.shared.constants import ENCUMBRANCE_CERTIFICATE, SALE_DEED

logger = get_logger(__name__)

VERIFICATION_STATUSES = {"VERIFIED", "NOT_VERIFIED", "N/A"}

VERIFY_RESPONSE_SCHEMA = {
    "headline": "2-3 line plain-language conclusion about the verification result — the main finding the user should know",
    "summary": "Detailed verification report paragraph explaining what was checked, what matched, what did not, any gaps in the title chain, and what the user should do next",
    "items": [
        {
            "field": "Property survey/CTS number",
            "sd_value": "value from Sale Deed",
            "ec_value": "value from EC ledger",
            "status": "VERIFIED | NOT_VERIFIED | N/A",
            "notes": "explanation",
        }
    ],
    "overall_comment": "free text summary of title exposure",
}


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
            summary={"note": msg}, items=[], model_used="deterministic",
        )
        return {"case_id": case_id, "status": "skipped", "verdict": "N/A"}

    sd_data = sale_deed.get("structured_json") or {}
    ec_data = ec.get("structured_json") or {}
    ledger = ec_data.get("historical_ledger") or []

    prompt = (
        "Verify the Karnataka Sale Deed (SD) against the Encumbrance Certificate "
        "(EC) historical ledger for the same property. The SD is the source of "
        "truth for what was conveyed; the EC ledger must be consistent with it.\n\n"
        "OUTPUT — You must return exactly these fields:\n\n"
        "1. \"headline\": A 2-3 line plain-language conclusion the user can read "
        "in 5 seconds. Write it like a newspaper headline or case-study finding. "
        "State the single most important finding (e.g. 'The EC belongs to a "
        "different property — none of the material fields could be verified' or "
        "'All key fields match; however the EC shows 2 subsequent transactions "
        "that need investigation'). Do NOT just say 'VERIFIED' or 'NOT VERIFIED' — "
        "explain WHY in plain English.\n\n"
        "2. \"summary\": A detailed verification report paragraph (5-10 sentences) "
        "explaining: what was checked, what matched and what did not, any gaps in "
        "the chain of title, whether subsequent encumbrances exist, and what the "
        "user should do next. Write for a non-legal audience. If the EC does not "
        "belong to the SD property, state that clearly and explain the mismatch.\n\n"
        "3. \"items\": For each material field, produce one item with:\n"
        "- field: the field name (e.g. 'Property survey/CTS number')\n"
        "- sd_value: value extracted from the Sale Deed\n"
        "- ec_value: value from the EC ledger (or 'Not found in EC')\n"
        "- status: VERIFIED | NOT_VERIFIED | N/A\n"
        "- notes: brief explanation of why this status\n\n"
        "Compare these fields: property identifiers (CTS/survey/plot numbers, "
        "locality), execution/registration date, parties (vendors/purchasers), "
        "consideration amount. Also check whether the EC shows any later "
        "encumbrance (mortgage, sale, agreement) on the property AFTER the SD "
        "date.\n\n"
        "RULES:\n"
        "- If the EC property does not match the SD property at all, mark ALL "
        "items as NOT_VERIFIED and explain in headline + summary.\n"
        "- Do NOT guess or hallucinate values. Use 'Not found in EC' if a value "
        "is absent.\n"
        "- overall_comment: same as summary, kept for backwards compatibility.\n\n"
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
            summary={"error": str(e)}, items=[], model_used=GEMINI_MODEL,
        )
        return {"case_id": case_id, "status": "error", "verdict": "N/A", "error": str(e)}

    result = response.get("result", {})
    analytics = response.get("analytics", {})

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
        input_tokens=analytics.get("input_tokens", 0),
        output_tokens=analytics.get("output_tokens", 0),
        latency_ms=analytics.get("latency_ms", 0),
        cost_usd=analytics.get("cost_usd", 0),
        model_used=analytics.get("model", GEMINI_MODEL),
    )

    set_case_verification_status(case_id=case_id, verification_status="complete", verdict=verdict)

    logger.info("Verification complete for case %s: verdict=%s (%d items)",
                case_id, verdict, len(items))
    return {"case_id": case_id, "status": "complete", "verdict": verdict, "items": items, "summary": summary}
