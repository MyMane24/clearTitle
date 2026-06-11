"""
OCR Merger Service
Takes a list of ChunkResult objects (from Sarvam OCR)
and merges them into a single unified document dict:
  {
    "total_pages": N,
    "full_text":   "--- Page 1 ---\n...\n--- Page N ---\n...",
    "pages":       [{page_number, content, tables, absolute_page_number}],
    "tables":      [merged table objects],
  }
Handles:
  - Overlap deduplication (1-page overlap between chunks)
  - Split table detection and merging across chunk boundaries
  - Base64 image blob stripping
"""

import re
from typing import List
from backend.services.sarvam_ocr import ChunkResult


def merge_chunked_outputs(chunks: List[ChunkResult]) -> dict:
    """
    Main merge entry point.
    Returns a unified document dict.
    """
    complete = [c for c in chunks if c.status == "complete"]
    if not complete:
        raise ValueError("No completed chunks to merge")

    # Single chunk — trivial case
    if len(complete) == 1:
        c = complete[0]
        pages = _extract_pages(c)
        return _build_output(pages)

    # Multi-chunk — deduplicate overlapping pages
    all_pages = _deduplicate_pages(sorted(complete, key=lambda c: c.chunk_index))
    all_pages = _detect_merge_split_tables(all_pages)
    return _build_output(all_pages)


def _extract_pages(chunk: ChunkResult) -> List[dict]:
    """Extract page list from a ChunkResult, normalising to absolute page numbers."""
    json_pages = chunk.json_data.get("pages", [])

    if json_pages:
        for pg in json_pages:
            local  = pg.get("page_number", 1)
            pg["absolute_page_number"] = chunk.page_start + local - 1
            # Clean base64 blobs from content
            pg["content"] = _clean_content(pg.get("content", ""))
        return sorted(json_pages, key=lambda p: p["absolute_page_number"])

    # Fallback: Sarvam returned no page objects — build synthetic from MD
    return [{
        "page_number":          1,
        "absolute_page_number": chunk.page_start,
        "content":              _clean_content(chunk.md_text),
        "tables":               [],
    }]


def _deduplicate_pages(sorted_chunks: List[ChunkResult]) -> List[dict]:
    """
    Merge pages from all chunks, keeping only first occurrence of each page number.
    Overlap pages (appearing in two adjacent chunks) are taken from the earlier chunk.
    """
    seen:       set       = set()
    all_pages:  List[dict] = []

    for chunk in sorted_chunks:
        pages = _extract_pages(chunk)
        for pg in pages:
            abs_p = pg["absolute_page_number"]
            if abs_p not in seen:
                seen.add(abs_p)
                all_pages.append(pg)

    return sorted(all_pages, key=lambda p: p["absolute_page_number"])


def _detect_merge_split_tables(pages: List[dict]) -> List[dict]:
    """
    If page N ends with an open markdown table AND page N+1 starts with
    table continuation rows (no header separator), merge them.
    """
    for i in range(len(pages) - 1):
        curr_content = pages[i].get("content", "")
        next_content = pages[i + 1].get("content", "")

        if _ends_with_open_table(curr_content) and _starts_with_continuation(next_content):
            pages[i]["content"] = curr_content.rstrip() + "\n" + next_content.lstrip()
            pages[i + 1]["content"] = ""
            pages[i + 1]["_merged_into"] = pages[i]["absolute_page_number"]

    return pages


def _ends_with_open_table(text: str) -> bool:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return bool(lines) and _is_table_row(lines[-1])


def _starts_with_continuation(text: str) -> bool:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines or not _is_table_row(lines[0]):
        return False
    # A new table always has a separator on line 2 (|---|---|)
    return not (len(lines) > 1 and re.match(r"^\|[-:\s|]+\|$", lines[1].strip()))


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|") and line.strip().endswith("|")


def _clean_content(text: str) -> str:
    """
    Strip base64-encoded image blobs Sarvam embeds for stamps/seals.
    Replace with a readable placeholder.
    """
    # Inline markdown images with data URI
    text = re.sub(
        r"!\[[^\]]*\]\(data:image/[^)]+\)",
        "[OFFICIAL STAMP / SEAL]",
        text,
    )
    # Bare data URI blobs
    text = re.sub(
        r"data:image/[a-zA-Z+]+;base64,[A-Za-z0-9+/=\n]{20,}",
        "[IMAGE REMOVED]",
        text,
    )
    # Collapse excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _build_output(pages: List[dict]) -> dict:
    """Assemble final unified document dict."""
    # Build full markdown with page markers
    parts = []
    for pg in pages:
        content = pg.get("content", "").strip()
        if content:
            parts.append(f"\n\n--- Page {pg['absolute_page_number']} ---\n{content}")

    full_text = "\n".join(parts).strip()

    # Collect all table objects
    tables = []
    for pg in pages:
        for tbl in pg.get("tables", []):
            tbl["source_page"] = pg["absolute_page_number"]
            tables.append(tbl)

    return {
        "total_pages": max((p["absolute_page_number"] for p in pages), default=0),
        "full_text":   full_text,
        "pages":       pages,
        "tables":      tables,
    }
