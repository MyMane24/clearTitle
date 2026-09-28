"""EC historical-ledger cleanup.

The EC's tall records often span a page break. The OCR emits the continuation
row (empty serial number, empty date, empty registration reference) as a
separate <tr>, so the extractor turns one registration into two ledger entries.
A genuine EC record always carries both an execution date and a registration
reference, so a row lacking both is reliably a page-split continuation.
"""

from __future__ import annotations

_EMPTY_MARKERS = ("", "-", "--", "null", "none", "nil", "n/a")


def _filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return str(value).strip().lower() not in _EMPTY_MARKERS


def _merge_property(base: dict, extra: dict) -> None:
    for key, value in (extra or {}).items():
        if not _filled(value):
            continue
        if key == "boundaries":
            bnd = base.setdefault("boundaries", {})
            for dkey, dval in (value or {}).items():
                if _filled(dval) and not _filled(bnd.get(dkey)):
                    bnd[dkey] = dval
        elif isinstance(value, dict):
            base[key] = {**(base.get(key) or {}), **value}
        elif not _filled(base.get(key)) or len(str(value)) > len(str(base.get(key))):
            base[key] = value


def merge_split_ledger(ledger: list) -> list:
    merged: list = []
    for entry in ledger or []:
        continuation = (
            merged
            and not _filled(entry.get("execution_date"))
            and not _filled(entry.get("registration_reference"))
        )
        if not continuation:
            merged.append(dict(entry))
            continue
        prev = merged[-1]
        prev_parties = prev.setdefault("parties", {})
        for role in ("vendors", "purchasers"):
            names = [n for n in (prev_parties.get(role) or []) if _filled(n)]
            for name in ((entry.get("parties") or {}).get(role) or []):
                if _filled(name) and name not in names:
                    names.append(name)
            if names:
                prev_parties[role] = names
        prev_fin = prev.setdefault("financials", {})
        for key, value in ((entry.get("financials") or {}).items()):
            if _filled(value) and not _filled(prev_fin.get(key)):
                prev_fin[key] = value
        prev_prop = prev.setdefault("property_details", {})
        _merge_property(prev_prop, entry.get("property_details") or {})
        _ = entry.pop("transaction_index", None)
        for key, value in entry.items():
            if key in ("parties", "financials", "property_details", "transaction_type"):
                continue
            if _filled(value) and not _filled(prev.get(key)):
                prev[key] = value
    for index, entry in enumerate(merged, start=1):
        entry["transaction_index"] = index
    return merged


def normalize_ec_structured(structured: dict) -> dict:
    """Return an EC-typed structured dict with split ledger rows recombined."""
    if not isinstance(structured, dict):
        return structured
    if structured.get("document_type") != "ENCUMBRANCE_CERTIFICATE":
        return structured
    ledger = structured.get("historical_ledger")
    if isinstance(ledger, list) and ledger:
        return {**structured, "historical_ledger": merge_split_ledger(ledger)}
    return structured
