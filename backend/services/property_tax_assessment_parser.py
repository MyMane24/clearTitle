"""
Deterministic parser for Belagavi property tax assessment forms.

These documents are mostly key/value tables. We preserve the original row
labels from OCR and also map the important row numbers into stable fields.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Iterable


PROPERTY_TAX_ASSESSMENT_DOC_TYPE = "PROPERTY_TAX_ASSESSMENT"


class _TableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
        elif self._in_cell and tag == "br":
            self._cell_parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self._in_cell and tag in {"td", "th"}:
            self._current_row.append(_clean_cell_text("".join(self._cell_parts)))
            self._in_cell = False
            self._cell_parts = []
        elif self._in_row and tag == "tr":
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
            self._current_row = []
        elif self._in_table and tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False
            self._current_table = []

    def handle_data(self, data: str):
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_entityref(self, name: str):
        if self._in_cell:
            self._cell_parts.append(unescape(f"&{name};"))

    def handle_charref(self, name: str):
        if self._in_cell:
            self._cell_parts.append(unescape(f"&#{name};"))


ROW_FIELD_MAP = {
    "1": "owner_name",
    "2": "occupier_name",
    "3": "owner_address",
    "4": "assessment_year",
    "5": "ward_number",
    "6": "street_or_area_name",
    "7": "property_number",
    "8": "site_total_area_sqft",
    "9": "building_covered_land_area_sqft",
    "10": "total_constructed_area_sqft",
    "11": "plinth_factor",
    "12": "vacant_land_area_sqft",
    "13": "exempt_vacant_land_area",
    "14": "taxable_vacant_land_area",
    "16(A)": "land_market_value",
    "16(B)": "land_market_value_50_percent",
    "19": "vacant_land_property_tax",
    "20": "building_covered_land_area_sqft_row_20",
    "21": "land_base_value",
    "22": "building_type",
    "23(A)": "construction_cost_per_sqft",
    "23(B)": "construction_cost_per_sqft_50_percent",
    "24": "building_plinth_area_sqft",
    "25": "building_construction_cost",
    "26": "building_age",
    "27": "depreciation_rate",
    "28": "building_depreciation",
    "29": "building_taxable_value",
    "30": "usage",
    "31": "building_tax_rate",
    "32": "building_property_tax",
    "33": "self_occupied_rebate_value",
    "34": "property_tax_before_rebate",
    "35": "rebate_amount",
    "36": "property_tax_payable",
    "37": "cess_total",
    "38": "vehicle_cess",
    "39": "swm_cess",
    "40": "ugd_cess",
    "41": "penalty",
    "42": "kmc_act_penalty",
    "43": "total_payable",
    "44": "payment_mode",
}


def normalize_property_tax_assessment(
    merged_ocr: dict,
    source_filename: str | None = None,
) -> dict:
    full_text = merged_ocr.get("full_text") or ""
    tables = _extract_tables(merged_ocr)
    raw_rows = _extract_assessment_rows(tables)
    mapped_fields = _map_assessment_rows(raw_rows)
    metadata = _extract_metadata(full_text, mapped_fields)
    property_owner = _extract_property_owner(metadata, mapped_fields)
    property_details = _extract_property_details(mapped_fields)
    challan_copies = _extract_challan_copies(tables, mapped_fields, metadata)

    return {
        "document_type": PROPERTY_TAX_ASSESSMENT_DOC_TYPE,
        "source_filename": source_filename,
        "document_metadata": metadata,
        "property_owner": property_owner,
        "property_details": property_details,
        "assessment_table": {
            "raw_rows": raw_rows,
            "mapped_fields": mapped_fields,
        },
        "challan_copies": challan_copies,
        "validity": {
            "valid_for_month": _match_value(full_text, r"valid\s+for\s+the\s+month\s+of\s+([A-Za-z]+)"),
            "issued_by": _match_value(full_text, r"Form2\s+issued\s+by\s*:\s*([^\n]+)"),
        },
    }


def _extract_tables(merged_ocr: dict) -> list[list[list[str]]]:
    parser = _TableHTMLParser()
    pages = merged_ocr.get("pages") or []
    if pages:
        for page in pages:
            parser.feed(page.get("content") or "")
    else:
        parser.feed(merged_ocr.get("full_text") or "")
    return parser.tables


def _extract_assessment_rows(tables: list[list[list[str]]]) -> list[dict]:
    rows: list[dict] = []
    in_assessment = False

    for table in tables:
        flat = _clean_output_text(" ".join(" ".join(row) for row in table))
        if _is_challan_table(flat):
            continue

        table_has_numbered_rows = any(
            _normalize_row_number(row[0] if row else "")
            for row in table
        )
        if not table_has_numbered_rows:
            continue

        in_assessment = True
        for row in table:
            row_number, label, value = _normalize_assessment_row(row)
            if not row_number and not label and not value:
                continue
            if not row_number and not in_assessment:
                continue
            rows.append(
                {
                    "row_number": row_number,
                    "label": label,
                    "value": value,
                }
            )

    return rows


def _normalize_assessment_row(row: list[str]) -> tuple[str, str, str]:
    cells = [_clean_output_text(cell) for cell in row]
    while len(cells) < 3:
        cells.append("")

    row_number = _normalize_row_number(cells[0])
    label = cells[1]
    value = _clean_output_text(" ".join(cells[2:]))

    if not row_number and len(cells) == 3 and _looks_like_row_number(cells[0]):
        row_number = _normalize_row_number(cells[0])
    return row_number, label, value


def _map_assessment_rows(raw_rows: list[dict]) -> dict:
    mapped = {field: None for field in ROW_FIELD_MAP.values()}
    row_46_values: list[str] = []

    for row in raw_rows:
        row_number = row.get("row_number") or ""
        value = row.get("value") or ""
        if not value:
            continue

        field = ROW_FIELD_MAP.get(row_number)
        if field and mapped.get(field) is None:
            mapped[field] = value
        elif row_number == "46":
            row_46_values.append(value)

    mapped["amount_and_date"] = row_46_values[0] if row_46_values else None
    mapped["challan_number"] = row_46_values[1] if len(row_46_values) > 1 else None
    mapped["swm_service_charges"] = _match_value(
        mapped.get("swm_cess") or "",
        r"SWM\s+Service\s+Charges\s*:?\s*([0-9.]+)",
    )
    mapped["cess_details"] = _extract_cess_details(raw_rows)
    return mapped


def _extract_cess_details(raw_rows: list[dict]) -> dict:
    combined = " ".join(
        row.get("label", "") for row in raw_rows if "Cess" in row.get("label", "")
    )
    return {
        "health_cess": _match_value(combined, r"Health\s+Cess\s*\(15%\)\s*:\s*([0-9.]+)"),
        "library_cess": _match_value(combined, r"Library\s+Cess\s*\(6%\)\s*:\s*([0-9.]+)"),
        "beggary_cess": _match_value(combined, r"Beggary\s+Cess\s*\(3%\)\s*:\s*([0-9.]+)"),
        "urban_transport_cess": _match_value(combined, r"Urban\s+Transport\s+Cess\s*\(2%\)\s*:\s*([0-9.]+)"),
    }


def _extract_metadata(text: str, mapped_fields: dict) -> dict:
    document_date = _match_value(
        text,
        r"\bDate\s*:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}(?:\s+[0-9:]+\s*[AP]M)?)",
    )
    return {
        "issuing_authority": _extract_issuing_authority(text),
        "form_number": _match_value(text, r"ನಮೂನೆ\s*[-–]?\s*([0-9]+)") or "1",
        "pid": _match_value(text, r"\bPID\s*:\s*([0-9]+)"),
        "old_assessment_number": _match_value(text, r"Old\s+Assessment\s+No\s*:?\s*([^\n]+)"),
        "new_assessment_number": _match_value(text, r"New\s+Assessment\s+No\s*:\s*([^\n]+)"),
        "date": _format_date(document_date),
        "document_datetime_raw": document_date,
        "assessment_year": mapped_fields.get("assessment_year"),
        "property_type": _extract_property_type(text),
    }


def _extract_property_owner(metadata: dict, mapped_fields: dict) -> dict:
    return {
        "owner_name": mapped_fields.get("owner_name"),
        "occupier_name": mapped_fields.get("occupier_name"),
        "pid": metadata.get("pid"),
        "old_assessment_number": metadata.get("old_assessment_number"),
        "new_assessment_number": metadata.get("new_assessment_number"),
        "ward_number": mapped_fields.get("ward_number"),
    }


def _extract_property_details(mapped_fields: dict) -> dict:
    address = mapped_fields.get("owner_address")
    return {
        "property_address": address,
        "street_or_area_name": mapped_fields.get("street_or_area_name"),
        "cts_number": _match_value(address or "", r"\bCTS\s*([0-9A-Za-z/-]+)"),
        "property_number": mapped_fields.get("property_number"),
        "usage": mapped_fields.get("usage"),
        "site_total_area_sqft": mapped_fields.get("site_total_area_sqft"),
        "building_covered_land_area_sqft": mapped_fields.get("building_covered_land_area_sqft"),
        "total_constructed_area_sqft": mapped_fields.get("total_constructed_area_sqft"),
        "building_plinth_area_sqft": mapped_fields.get("building_plinth_area_sqft"),
    }


def _extract_challan_copies(
    tables: list[list[list[str]]],
    mapped_fields: dict,
    metadata: dict,
) -> list[dict]:
    copies: list[dict] = []
    for table in tables:
        flat = _clean_output_text(" ".join(" ".join(row) for row in table))
        if not _is_challan_table(flat):
            continue

        copy_type = _extract_challan_copy_type(flat)
        challan_pid = _match_value(flat, r"\bPID\s*:?\s*([0-9]+)") or metadata.get("pid")
        tax_paid_raw = _extract_amount_after(flat, "ಆಸ್ತಿ ತೆರಿಗೆ")
        if tax_paid_raw and challan_pid and tax_paid_raw.strip() == str(challan_pid).strip():
            tax_paid_raw = None
        copies.append(
            {
                "copy_index": len(copies) + 1,
                "copy_type": copy_type,
                "copy_type_raw": copy_type,
                "pid": challan_pid,
                "assessment_number": _match_value(flat, r"Assess(?:ment)?\s+No\s*:?\s*([0-9/]+)"),
                "payment_mode": _match_value(flat, r"\b(HDFC\s+ONLINE\s+PAYMENT)\b") or mapped_fields.get("payment_mode"),
                "ward_number": _match_value(flat, r"ವಾರ್ಡ\S*\s+ನಂ\s*:?\s*([0-9]+)") or mapped_fields.get("ward_number"),
                "assessment_year": _match_value(flat, r"\b(20[0-9]{2}\s*-\s*[0-9]{2})\b") or mapped_fields.get("assessment_year"),
                "owner_name": mapped_fields.get("owner_name"),
                "property_address": mapped_fields.get("owner_address"),
                "occupier_name": mapped_fields.get("occupier_name"),
                "property_tax_paid": tax_paid_raw or mapped_fields.get("property_tax_payable"),
                "cess_paid": _extract_amount_after(flat, "ಸಸ್ಸು") or _extract_amount_after(flat, "ಸೆಸ್ಸು") or mapped_fields.get("cess_total"),
                "swm_cess": _extract_amount_after(flat, "swm") or mapped_fields.get("swm_cess"),
                "swm_service_charges": _match_value(flat, r"SWM\s+Service\s+Charges\s*:?\s*([0-9.]+)") or mapped_fields.get("swm_service_charges"),
                "penalty": _extract_amount_after(flat, "ದಂಡ") or mapped_fields.get("penalty"),
                "service_charge": _extract_amount_after(flat, "ಸೇವಾ ಶುಲ್ಕ"),
                "total_amount": _extract_amount_after(flat, "ಒಟ್ಟು ಮೊತ್ತ") or mapped_fields.get("total_payable"),
                "amount_in_words": _match_value(flat, r"(Rupees\s+.+?\s+only)"),
                "payment_date": _match_value(flat, r"ಸಂದಾಯ ಮಾಡಿದ\s+ದಿನಾಂಕ\s*:?\s*([0-9/_ -]+)"),
                "bank_account_or_challan_number": _match_value(flat, r"ಬ್ಯಾಂಕ್?\s+ಖಾತೆ\s+ಸಂಖ್ಯೆ\s*([0-9]+)") or _match_value(flat, r"\b([0-9]{4})\b"),
            }
        )

    return copies


def _extract_challan_copy_type(flat_text: str) -> str | None:
    patterns = [
        r"(ಬ್ಯಾಂಕಿನಿಂದ.+?ಕಳುಹಿಸುವ ಪ್ರತಿ)",
        r"(ಬ್ಯಾಂಕಿನ ಪ್ರತಿ)",
        r"(ವಿವರ ಪಟ್ಟಿಗೆ ಲಗತ್ತಿಸುವ ಪ್ರತಿ)",
        r"(ವಿವರ ಪಟ್ಟಿಗೆ.+?ಪ್ರತಿ)",
    ]
    for pattern in patterns:
        value = _match_value(flat_text, pattern)
        if value:
            return value
    return None


def _is_challan_table(flat_text: str) -> bool:
    lower = flat_text.lower()
    return "ಚಲನ್" in flat_text or "hdfc online payment" in lower and "rupees" in lower


def _extract_amount_after(text: str, keyword: str) -> str | None:
    match = re.search(
        rf"{re.escape(keyword)}[^0-9-]*([0-9][0-9.,]*(?:\([^)]*\))?)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_output_text(match.group(1)) if match else None


def _extract_issuing_authority(text: str) -> str | None:
    match = re.search(r"(ಬೆಳಗಾವಿ\s+ಮಹಾನಗರ\s+ಪಾಲಿಕೆ\s*,?\s*ಬೆಳಗಾವಿ)", text)
    if match:
        return _clean_output_text(match.group(1))
    return "Belagavi Mahanagara Palike, Belagavi" if "Belagavi" in text or "ಬೆಳಗಾವಿ" in text else None


def _extract_property_type(text: str) -> str | None:
    match = re.search(r"Property\s+Type\s*:\s*([A-Za-z]+)(?:\s*\(([^)]+)\))?", text)
    if not match:
        return None
    value = match.group(1)
    if match.group(2):
        value = f"{value} ({match.group(2)})"
    return _clean_output_text(value)


def _format_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", value)
    if not match:
        return value
    day, month, year = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _normalize_row_number(value: str) -> str:
    value = _clean_output_text(value)
    value = re.sub(r"\s+", "", value)
    match = re.fullmatch(r"([0-9]{1,2})(?:\(?([A-Za-z])\)?)?", value)
    if not match:
        return ""
    base, suffix = match.groups()
    return f"{base}({suffix.upper()})" if suffix else base


def _looks_like_row_number(value: str) -> bool:
    return bool(_normalize_row_number(value))


def _match_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text or "", flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    value = _clean_output_text(match.group(1))
    return value or None


def _clean_cell_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _clean_output_text(text: str) -> str:
    text = _clean_cell_text(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()
