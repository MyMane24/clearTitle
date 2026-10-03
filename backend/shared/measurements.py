"""Deterministic area/boundary comparison for verification.

Extracts must be compared in a common unit — a deed may quote "9.14 X 12.19",
"1200 sq ft", "1 gunta" or bare "111.48" while the Khata says "111.48 sq m".
These helpers canonicalize to metres / square metres and compare with a
tolerance so one transaction is never split by a unit mismatch.
"""

from __future__ import annotations

import re

# -- unit tables (canonical: metres, square metres) ---------------------------
_FT_PER_M = 0.3048  # metres per foot
_AREA_FACTOR = {  # multiplier to square metres
    "sqm": 1.0, "sq.m": 1.0, "sq.mtr": 1.0, "sq.mt": 1.0, "sqmt": 1.0,
    "m2": 1.0, "m²": 1.0, "sq m": 1.0, "sq.m.": 1.0, "metres": 1.0,
    "sq ft": 0.09290304, "sqft": 0.09290304, "sq.ft": 0.09290304,
    "square feet": 0.09290304, "sq feet": 0.09290304, "ft2": 0.09290304,
    "sq yd": 0.83612736, "sq.yards": 0.83612736, "square yard": 0.83612736,
    "sqyards": 0.83612736,
    "acre": 4046.8564224, "acres": 4046.8564224,
    "cent": 40.468564224, "cents": 40.468564224,
    "gunta": 101.17141056, "guntas": 101.17141056,
    "are": 100.0, "ares": 100.0,
    "hectare": 10000.0, "hectares": 10000.0, "ha": 10000.0,
}
_LEN_FACTOR = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "ft": _FT_PER_M, "feet": _FT_PER_M, "foot": _FT_PER_M,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "cm": 0.01, "centimetre": 0.01, "centimetres": 0.01,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def parse_area(value) -> float | None:
    """Parse an area string into square metres, or None when unparseable."""
    if value in (None, ""):
        return None
    v = _norm(value)
    if not v or not re.search(r"\d", v):
        return None

    # bare number → assume square metres (most extracts quote sq m without units)
    m = re.match(r"^(\d+(?:[.,]\d+)?)$", v)
    if m:
        return float(m.group(1).replace(",", "."))

    # "<number> <unit>" — match unit by longest prefix
    for unit in sorted(_AREA_FACTOR, key=len, reverse=True):
        m = re.match(r"^(\d+(?:[.,]\d+)?)\s*" + re.escape(unit) + r"$", v)
        if m:
            return float(m.group(1).replace(",", ".")) * _AREA_FACTOR[unit]

    # dimension product already computed as "<value> sq m" style — handled above;
    # fall back to a plain embedded number only if nothing else matched (risky)
    pieces = re.findall(r"(\d+(?:[.,]\d+)?)", v)
    if len(pieces) == 1:
        return float(pieces[0].replace(",", "."))
    return None


def parse_dimensions(value) -> list[float] | None:
    """Parse a dimensions string like "9.14 X 12.19" (or LxW, ft/cm) → metres."""
    if value in (None, ""):
        return None
    v = _norm(value)
    if not v or not re.search(r"\d", v):
        return None
    sides = re.split(r"\s*[x\u00d7*]\s*", v)
    if len(sides) < 2:
        return None
    out = []
    for side in sides:
        m = re.match(r"^(\d+(?:[.,]\d+)?)\s*([a-z]+)?$", side)
        if not m:
            return None
        num = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "m").rstrip("s")
        factor = _LEN_FACTOR.get(unit)
        if factor is None:
            factor = _LEN_FACTOR.get(m.group(2) or "m")
        if factor is None:
            return None
        out.append(num * factor)
    return out


def dims_to_sqm(value) -> float | None:
    """Area implied by a dimensions string, in square metres."""
    sides = parse_dimensions(value)
    if sides is None:
        return None
    prod = 1.0
    for s in sides:
        prod *= s
    return prod


def area_sqm(value) -> float | None:
    """Best-effort area from a raw/extracted value (handles dims/product too)."""
    if value in (None, ""):
        return None
    if parse_dimensions(value) is not None:
        return dims_to_sqm(value)
    return parse_area(value)


# -- comparison -----------------------------------------------------------------
AREA_TOLERANCE = 0.05  # relative


def compare_areas(a, b) -> str:
    """Compare two area sources → 'VERIFIED' | 'FLAG' | 'N/A'.

    VERIFIED: both parse and agree within AREA_TOLERANCE (relative).
    FLAG:      both parse but disagree beyond tolerance (a unit/OCR mismatch,
               or genuinely different plot areas worth surfacing).
    N/A:       at least one side could not be parsed.
    """
    av, bv = area_sqm(a), area_sqm(b)
    if av is None or bv is None:
        return "N/A"
    if av == 0 and bv == 0:
        return "VERIFIED"
    if abs(av - bv) / max(av, bv) <= AREA_TOLERANCE:
        return "VERIFIED"
    return "FLAG"


def boundaries_similar(sd_bnd: dict | None, other_bnd: dict | None) -> str:
    """Compare N/E/W/S boundary descriptions between two docs.

    Deterministic: every side that BOTH docs state must match after
    normalizing whitespace/punctuation. A side one doc omits is not a
    contradiction (deeds routinely skip a side the EC states). Absence of
    both → N/A; any genuinely conflicting side → NEEDS_REVIEW.
    """
    if not sd_bnd or not other_bnd:
        return "N/A"
    key_words = re.compile(r"[^a-z0-9/.\-]+")
    matched = 0
    for side in ("north", "east", "west", "south"):
        sv = _norm((sd_bnd or {}).get(side) or "")
        ov = _norm((other_bnd or {}).get(side) or "")
        if not sv or not ov:
            continue
        matched += 1
        if key_words.sub(" ", sv) != key_words.sub(" ", ov):
            return "NEEDS_REVIEW"
    return "VERIFIED" if matched else "N/A"
