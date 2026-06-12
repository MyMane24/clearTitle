"""
Deterministic Encumbrance Certificate parser.

EC documents have a predictable header and a repeated 9-column transaction
table. We parse that directly instead of sending EC text to Groq.
"""

from __future__ import annotations

import re
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
from typing import Iterable


EC_DOC_TYPE = "ENCUMBRANCE_CERTIFICATE"

EC_COLUMNS = [
    "transaction_number",
    "property_details",
    "execution_date",
    "document_details",
    "seller_or_executant",
    "buyer_or_claimant",
    "volume",
    "page",
    "document_reference",
]


class _TableHTMLParser(HTMLParser):
    """Collect table rows as plain cell text from Sarvam HTML table output."""

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


def normalize_ec_document(merged_ocr: dict, source_filename: str | None = None) -> dict:
    """Return final structured JSON for an EC document."""
    full_text = merged_ocr.get("full_text", "")
    pages = merged_ocr.get("pages", [])
    transactions = _dedupe_transactions(_extract_transactions(pages))
    metadata = _extract_metadata(full_text)
    _fill_metadata_from_transactions(metadata, transactions)

    structured = {
        "document_type": EC_DOC_TYPE,
        "source_filename": source_filename,
        "document_metadata": metadata,
        "transactions": transactions,
    }
    return structured


def _extract_metadata(text: str) -> dict:
    search_dates = _extract_search_dates(text)
    return {
        "application_number": _match_value(text, r"ಅರ್ಜಿ\s+ಸಂಖ್ಯೆ\s*:\s*([^\n]+)"),
        "certificate_number": _match_value(text, r"ಪ್ರಮಾಣಪತ್ರದ\s+ಸಂಖ್ಯೆ\s*:\s*([^\n]+)"),
        "search_start_date": search_dates[0],
        "search_end_date": search_dates[1],
        "village": _match_value(text, r"Village\s*:\s*([^\n]+)"),
        "hobli": _match_value(text, r"Hobli\s*:\s*([^\n]+)"),
        "cts_number": _match_value(text, r"C\.?\s*T\.?\s*S\.?\s*No\s*:\s*([^,\n]+)"),
        "converted_survey_number": _match_value(text, r"Converted\s+Survey\s+No\s*:\s*([^,\n]+)"),
        "survey_number": _match_value(text, r"Survey\s+No\s*:\s*([^,\n]+)"),
        "plot_number": _match_value(text, r"Plot\s+No\s*:\s*([^,\n]+)"),
    }


def _extract_search_dates(text: str) -> tuple[str | None, str | None]:
    matches = re.findall(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})\b", text)
    if len(matches) < 2:
        return None, None
    return _format_date(matches[0]), _format_date(matches[1])


def _format_date(parts: tuple[str, str, str]) -> str:
    day, month, year = parts
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _match_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    value = _clean_cell_text(match.group(1))
    return value or None


def _extract_transactions(pages: Iterable[dict]) -> list[dict]:
    transactions: list[dict] = []

    for page in pages:
        page_number = page.get("absolute_page_number") or page.get("page_number")
        for row in _iter_table_rows(page.get("content", "")):
            cells = _normalize_row(row)
            if not _is_transaction_row(cells):
                continue

            sl_no = cells[0].strip()
            if sl_no:
                transactions.append(_new_transaction(cells, page_number))
            elif _starts_transaction_without_number(cells):
                existing = _find_latest_transaction_by_date(
                    transactions,
                    _date_key(cells[2]),
                )
                if existing:
                    _merge_continuation(existing, cells, page_number)
                else:
                    transactions.append(
                        _new_transaction(
                            cells,
                            page_number,
                            fallback_transaction_number=str(len(transactions) + 1),
                        )
                    )
            elif transactions:
                _merge_continuation(transactions[-1], cells, page_number)

    return transactions


def _iter_table_rows(html_text: str) -> Iterable[list[str]]:
    parser = _TableHTMLParser()
    parser.feed(html_text or "")
    for table in parser.tables:
        for row in table:
            yield row


def _normalize_row(row: list[str]) -> list[str]:
    if _is_legacy_ec_row(row):
        return _normalize_legacy_ec_row(row)

    cells = row[:len(EC_COLUMNS)]
    if len(cells) < len(EC_COLUMNS):
        cells.extend([""] * (len(EC_COLUMNS) - len(cells)))
    return cells


def _is_legacy_ec_row(row: list[str]) -> bool:
    if len(row) != 7:
        return False
    compact = [cell.strip() for cell in row]
    return (
        not compact[0]
        and bool(compact[1])
        and _looks_like_date(compact[2])
        and any(compact[3:])
    )


def _normalize_legacy_ec_row(row: list[str]) -> list[str]:
    volume, page, document_reference = _split_legacy_reference_cell(row[6])
    return [
        "",
        row[1],
        row[2],
        row[3],
        row[4],
        row[5],
        volume,
        page,
        document_reference,
    ]


def _split_legacy_reference_cell(value: str) -> tuple[str, str, str]:
    parts = [_clean_output_text(part) for part in value.split("\n") if part.strip()]
    document_reference = ""
    page = ""
    volume = ""

    for part in parts:
        if re.fullmatch(r"[A-Z]{2,}D\d+", part, flags=re.IGNORECASE):
            page = _join_text(page, part)
        elif "-" in part and re.search(r"\b[A-Z]{2,}", part, flags=re.IGNORECASE):
            document_reference = _join_text(document_reference, part)
        elif re.fullmatch(r"\d+", part):
            volume = part
        else:
            page = _join_text(page, part)

    return volume, page, document_reference


def _is_transaction_row(cells: list[str]) -> bool:
    if len(cells) < len(EC_COLUMNS):
        return False
    compact = [cell.strip() for cell in cells]
    if compact == [str(i) for i in range(1, 10)]:
        return False
    if any("<" in cell or ">" in cell for cell in compact):
        return False
    first = compact[0]
    if first and not re.fullmatch(r"\d+", first):
        return False
    return any(compact[1:])


def _starts_transaction_without_number(cells: list[str]) -> bool:
    compact = [cell.strip() for cell in cells]
    return not compact[0] and bool(compact[1]) and _looks_like_date(compact[2])


def _looks_like_date(value: str) -> bool:
    return bool(re.search(r"\b\d{1,2}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{4}\b", value or ""))


def _date_key(value: str) -> str | None:
    match = re.search(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})\b", value or "")
    if not match:
        return None
    return _format_date(match.groups())


def _find_latest_transaction_by_date(transactions: list[dict], date_key: str | None) -> dict | None:
    if not date_key:
        return None
    for tx in reversed(transactions):
        if _date_key(tx.get("execution_date", "")) == date_key:
            return tx
    return None


def _new_transaction(
    cells: list[str],
    page_number: int | None,
    fallback_transaction_number: str | None = None,
) -> dict:
    tx = {
        key: _clean_output_text(cells[index])
        for index, key in enumerate(EC_COLUMNS)
    }
    if not tx["transaction_number"] and fallback_transaction_number:
        tx["transaction_number"] = fallback_transaction_number
    tx["sl_no"] = tx["transaction_number"]
    tx["source_pages"] = [page_number] if page_number is not None else []
    return tx


def _merge_continuation(tx: dict, cells: list[str], page_number: int | None) -> None:
    for index, key in enumerate(EC_COLUMNS):
        value = cells[index].strip()
        if not value or key == "transaction_number":
            continue
        tx[key] = _join_text(tx.get(key, ""), _clean_output_text(value))

    if page_number is not None and page_number not in tx["source_pages"]:
        tx["source_pages"].append(page_number)


def _dedupe_transactions(transactions: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: dict[tuple[str, str, str], dict] = {}

    for tx in transactions:
        key = (
            tx.get("transaction_number", ""),
            _date_key(tx.get("execution_date", "")) or tx.get("execution_date", ""),
            tx.get("document_reference", ""),
        )
        if key in seen:
            existing = seen[key]
            for page_number in tx.get("source_pages", []):
                if page_number not in existing["source_pages"]:
                    existing["source_pages"].append(page_number)
            continue
        seen[key] = tx
        unique.append(tx)

    return unique


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left} {right}".strip()


def _clean_cell_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _clean_output_text(text: str) -> str:
    """Make OCR table cell text readable in JSON and MySQL."""
    text = _clean_cell_text(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _fill_metadata_from_transactions(metadata: dict, transactions: list[dict]) -> None:
    combined_property = " ".join(tx.get("property_details", "") for tx in transactions)
    if not metadata.get("village"):
        metadata["village"] = _match_value(
            combined_property,
            r"Village\s+Name\s*:\s*(.*?)(?:\s+Property\s+Schedule\s+Description|,|\n|$)",
        )
    if not metadata.get("cts_number"):
        metadata["cts_number"] = _match_value(combined_property, r"C\.?\s*T\.?\s*S\.?\s*No\.?\s*[:.]?\s*([A-Za-z0-9/-]+)")
    if not metadata.get("plot_number"):
        metadata["plot_number"] = _match_value(combined_property, r"Plot\s+No\.?\s*[:.]?\s*([A-Za-z0-9/-]+)")
    if not metadata.get("survey_number"):
        metadata["survey_number"] = _match_value(combined_property, r"(?:R\.?\s*S\.?|Survey)\s+No\.?\s*[:.]?\s*([A-Za-z0-9/-]+)")


def with_document_type_name(structured: dict, doc_type: str) -> dict:
    """Return a copy with document_type set for consistent saved JSON."""
    output = deepcopy(structured)
    output["document_type"] = output.get("document_type") or doc_type
    return output
