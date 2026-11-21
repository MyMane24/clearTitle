"""Page access and quote matching over a document's merged OCR text.

``documents.merged_ocr_text`` separates pages with ``--- Page N ---`` lines, so
a citation can name a page and the quote can be checked against that page.
"""

from __future__ import annotations

import re
import unicodedata

_PAGE_MARKER = re.compile(r"(?m)^[ \t]*---[ \t]*Page[ \t]+(\d+)[ \t]*---[ \t]*$")
_ELLIPSIS = re.compile(r"\.{3,}|…")


def split_pages(text: str) -> dict[int, str]:
    """Pages by number. Text without markers is page 1."""
    markers = list(_PAGE_MARKER.finditer(text))
    if not markers:
        return {1: text.strip()} if text.strip() else {}
    pages: dict[int, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        number = int(marker.group(1))
        body = text[marker.end() : end].strip()
        pages[number] = f"{pages[number]}\n{body}".strip() if number in pages else body
    return pages


_MARKUP = re.compile(r"<[^>]{1,200}>|[*_#|`>~]+")


def normalize(text: str) -> str:
    """Text for matching: HTML tags and markdown symbols removed, Unicode-normalised,
    case-folded, whitespace collapsed (Kannada-safe).

    OCR text carries table HTML and markdown that a quoted passage does not.
    """
    plain = _MARKUP.sub(" ", unicodedata.normalize("NFC", text))
    return " ".join(plain.casefold().split())


def locate_quote(quote: str, pages: dict[int, str], cited_page: int) -> int | None:
    """The page the quote is on: the cited page if it is there, else the first page
    that has it, else None (the quote is not in the document)."""
    if cited_page in pages and quote_on_page(quote, pages[cited_page]):
        return cited_page
    return next((number for number, text in pages.items() if quote_on_page(quote, text)), None)


def quote_on_page(quote: str, page_text: str) -> bool:
    """True when every fragment of the quote appears on the page, in order.

    Fragments are separated by an ellipsis, so a quote may skip words with
    ``...``. Whitespace, case and Unicode composition differences are ignored.
    """
    haystack = normalize(page_text)
    position = 0
    fragments = [normalize(part) for part in _ELLIPSIS.split(quote)]
    fragments = [part for part in fragments if part]
    if not fragments:
        return False
    for fragment in fragments:
        found = haystack.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True
