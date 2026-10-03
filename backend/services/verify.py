"""Cross-document verification (SD source of truth vs EC ledger).

One LLM verification pass returns field checks plus a case-level verdict.
Code validates the enums and persists the same verdict to both case tables.
"""

from __future__ import annotations

import json

from backend.database.repositories.case_repo import set_case_verification_status
from backend.database.repositories.document_repo import get_case_bundle
from backend.database.repositories.verification_results_repo import save_verification_results
from backend.integrations.llm.analysis_executor import run_analysis
from backend.logger import get_logger
from backend.prompts.loader import load_prompt, load_schema
from backend.shared.constants import (
    ENCUMBRANCE_CERTIFICATE,
    KHATA,
    SALE_DEED,
)
from backend.shared.measurements import (
    boundaries_similar,
    compare_areas,
)

logger = get_logger(__name__)

VERIFICATION_STATUSES = {"VERIFIED", "FLAG", "NEEDS_REVIEW", "N/A"}
VERDICTS = {"CLEAR_TITLE", "ATTENTION_REQUIRED"}

VERIFY_RESPONSE_SCHEMA = load_schema("verification_schema")
_VERIFY_PROMPT_TEMPLATE = load_prompt("verification")


def _normalize_llm_verdict(value) -> str | None:
    normalized = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    return normalized if normalized in VERDICTS else None


def _is_ec(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == ENCUMBRANCE_CERTIFICATE


def _is_khata(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == KHATA


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
    return {
        "counts": counts,
        "total": total,
        "verified_share": round(verified_share, 2),
    }


def _normalize_items(raw_items) -> list[dict]:
    items = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "N/A")).upper()
        if status not in VERIFICATION_STATUSES:
            status = "N/A"
        items.append({
            "field": raw.get("field"),
            "sd_value": raw.get("sd_value"),
            "ec_value": raw.get("ec_value"),
            "khata_value": raw.get("khata_value"),
            "status": status,
            "notes": raw.get("notes"),
        })
    return items


def _measurement_items(sd_data: dict, ec_data: dict, khata_data: dict | None) -> list[dict]:
    """Deterministic area + boundary checks, unit-aware (m, ft, gunta, etc.).

    The LLM is instructed not to emit area/boundary items; these are computed
    here so mixed units can never split a matching plot.
    """
    items = []

    def meas(doc: dict) -> dict:
        return (doc.get("property_schedule") or {}).get("measurements") or {}

    def first_meas(pd: dict | None) -> str:
        for v in ((pd or {}).get("measurements") or {}).values():
            if isinstance(v, str) and v.strip():
                return v
        return ""

    def bnd(pd: dict) -> dict:
        return (pd or {}).get("boundaries") or {}

    def has_text(d: dict) -> bool:
        return any(str(v or "").strip() for v in d.values())

    def area_item(field: str, a: str, b: str, a_label: str, b_label: str):
        if not a and not b:
            return
        status = compare_areas(a, b) if (a and b) else "N/A"
        items.append({
            "field": field,
            "sd_value": a,
            "ec_value": b if b_label.endswith("EC") else None,
            "khata_value": b if b_label.endswith("Khata") else None,
            "status": status,
            "notes": f"{a_label} '{a or '— missing —'}' vs {b_label} '{b or '— missing —'}'",
        })

    def bnd_item(field: str, a: dict, b: dict, b_label: str):
        if not has_text(a) and not has_text(b):
            return
        status = boundaries_similar(a, b) if (a and b and has_text(a) and has_text(b)) else "N/A"
        items.append({
            "field": field,
            "sd_value": ", ".join(str(v) for v in a.values() if str(v or "").strip()),
            "ec_value": ", ".join(str(v) for v in b.values() if str(v or "").strip()) if b_label.endswith("EC") else None,
            "khata_value": ", ".join(str(v) for v in b.values() if str(v or "").strip()) if b_label.endswith("Khata") else None,
            "status": status,
            "notes": f"SD {b_label} boundaries compared",
        })

    sd_meas = meas(sd_data)
    sd_area = sd_meas.get("total_land_area_sqmtr") or sd_meas.get("super_built_up_area_sqft") or ""
    sd_dims = sd_meas.get("dimensions_text") or ""
    sd_bnd = bnd(sd_data.get("property_schedule") or {})

    ec_pd = next(
        (t.get("property_details") or {} for t in (ec_data.get("historical_ledger") or [])
         if ((t or {}).get("property_details") or {}).get("measurements")),
        {},
    )
    ec_area = first_meas(ec_pd)
    ec_bnd = bnd(ec_pd)

    kh_pd = (khata_data or {}).get("property_details") or {}
    kh_area = kh_pd.get("area_sq_meters") or kh_pd.get("built_up_area_sq_meters") or ""
    kh_bnd = bnd(kh_pd)

    if sd_dims and sd_dims != sd_area:
        area_item("Land area (dimensions vs declared)", sd_dims, sd_area,
                  "SD dimensions", "SD declared")
    area_item("Land area (SD vs EC)", sd_area, ec_area, "SD", "EC")
    if khata_data:
        area_item("Land area (SD vs Khata)", sd_area, kh_area, "SD", "Khata")
    bnd_item("Boundaries (SD vs EC)", sd_bnd, ec_bnd, "vs EC")
    if khata_data:
        bnd_item("Boundaries (SD vs Khata)", sd_bnd, kh_bnd, "vs Khata")

    return items


def verify_case(case_id: str) -> dict:
    """Run the verification pass and persist results."""
    bundle = get_case_bundle(case_id)
    sale_deed = next((d for d in bundle if _is_sale_deed(d)), None)
    ec = next((d for d in bundle if _is_ec(d)), None)
    khata = next((d for d in bundle if _is_khata(d)), None)

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
    khata_data = khata.get("structured_json") if khata else None
    ledger = ec_data.get("historical_ledger") or []

    prompt = (
        _VERIFY_PROMPT_TEMPLATE + "\n\n"
        "--- SALE DEED ---\n"
        f"{json.dumps(sd_data, ensure_ascii=False, default=str)}\n\n"
        "--- EC HISTORICAL LEDGER ---\n"
        f"{json.dumps(ledger, ensure_ascii=False, default=str)}"
    )
    if khata_data:
        prompt += (
            "\n\n--- KHATA EXTRACT ---\n"
            f"{json.dumps(khata_data, ensure_ascii=False, default=str)}"
        )

    try:
        response = run_analysis(prompt, task="verification", response_schema=VERIFY_RESPONSE_SCHEMA)
    except Exception as e:
        logger.error("Verification LLM call failed for case %s: %s", case_id, e)
        save_verification_results(
            case_id=case_id, status="error", verdict="N/A",
            summary={"error": str(e)}, items=[],
        )
        set_case_verification_status(case_id=case_id, verification_status="error", verdict="N/A")
        return {"case_id": case_id, "status": "error", "verdict": "N/A", "error": str(e)}

    result = response.get("result", {})
    items = _normalize_items(result.get("items"))
    items.extend(_measurement_items(sd_data, ec_data, khata_data))

    verdict = _normalize_llm_verdict(result.get("verdict"))
    if verdict is None:
        msg = "Verification response did not contain a valid case-level verdict"
        logger.error("Verification for case %s: %s", case_id, msg)
        save_verification_results(case_id=case_id, status="error", verdict="N/A", summary={"error": msg}, items=items)
        set_case_verification_status(case_id=case_id, verification_status="error", verdict="N/A")
        return {"case_id": case_id, "status": "error", "verdict": "N/A", "error": msg}
    summary = _summarize(items)
    summary["verdict"] = verdict
    summary["status_line"] = result.get("status_line")
    summary["overall_comment"] = result.get("overall_comment")
    summary["headline"] = result.get("headline")
    summary["summary_text"] = result.get("summary")
    save_verification_results(
        case_id=case_id, status="complete", verdict=verdict,
        summary=summary, items=items,
    )

    set_case_verification_status(case_id=case_id, verification_status="complete", verdict=verdict)

    logger.info("Verification complete for case %s: verdict=%s (%d items)",
                case_id, verdict, len(items))
    return {"case_id": case_id, "status": "complete", "verdict": verdict, "items": items, "summary": summary}
