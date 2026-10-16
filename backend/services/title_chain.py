"""Legacy title-chain matching helpers retained for regression tests."""

from __future__ import annotations

from datetime import datetime

ENCUMBRANCE_KEYWORDS = ("mortgage", "lease", "agreement", "cancellation", "dtd", "charge", "deposit")

def _parse_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return value
    return str(value)

def _sd_identity(sd_data: dict) -> dict:
    """Deterministic projection of what the Sale Deed conveys."""
    fm = sd_data.get("file_metadata") or {}
    ps = sd_data.get("property_schedule") or {}
    return {
        "registration_reference": fm.get("registration_number"),
        "execution_date": fm.get("execution_date"),
        "survey_number": ps.get("survey_number"),
        "cts_number": ps.get("cts_number"),
        "plot_or_site_number": ps.get("apartment_or_shop_number"),
        "conveyed_interest": ps.get("full_schedule_description"),
    }

def _is_sale_deed_entry(entry: dict, sd_identity: dict) -> bool:
    reg = (entry.get("registration_reference") or "").strip().lower()
    sd_reg = (sd_identity.get("registration_reference") or "").strip().lower()
    if reg and sd_reg and reg == sd_reg:
        return True
    e_date = _parse_date(entry.get("execution_date"))
    sd_date = _parse_date(sd_identity.get("execution_date")) if sd_identity.get("execution_date") else None
    return bool(e_date and sd_date and e_date == sd_date)

def _is_encumbrance_type(transaction_type) -> bool:
    ttype = (transaction_type or "").lower()
    return any(k in ttype for k in ENCUMBRANCE_KEYWORDS)

def _fallback_role(entry: dict, sd_identity: dict) -> str:
    """Deterministic role when the LLM did not classify an entry."""
    if _is_sale_deed_entry(entry, sd_identity):
        return "THE_SD"
    if _is_encumbrance_type(entry.get("transaction_type")):
        return "ENCUMBRANCE"
    e_date = _parse_date(entry.get("execution_date"))
    sd_date = _parse_date(sd_identity.get("execution_date")) if sd_identity.get("execution_date") else None
    if e_date and sd_date and e_date > sd_date:
        return "SUBSEQUENT_TRANSFER"
    return "PREDECESSOR_TITLE"
