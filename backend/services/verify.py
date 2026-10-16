"""Legacy verification normalization helpers retained for regression tests."""

from __future__ import annotations

from backend.shared.measurements import (
    boundaries_similar,
    compare_areas,
)

VERIFICATION_STATUSES = {"VERIFIED", "FLAG", "NEEDS_REVIEW", "N/A"}

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
