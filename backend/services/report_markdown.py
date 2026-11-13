"""Markdown to ReportLab flowables for the customer-facing verification report.

The report narrative is written as markdown so its layout can follow the
findings. The dashboard renders that markdown directly; this module renders the
same subset into the PDF: ``##``/``###`` headings, paragraphs, bullet and
numbered lists, GFM tables, block quotes, and **bold**, *italic* and `code`.
"""

from __future__ import annotations

import re
from html import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

_BULLET = re.compile(r"^[-*•]\s+")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
_SUBHEADING = re.compile(r"^#{3,6}\s+")
_SECTION = re.compile(r"^#{1,2}\s+")
_TABLE_DIVIDER = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")

_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")
_ITALIC_STAR = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_ITALIC_UNDERSCORE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")


def inline_markup(text: str) -> str:
    """Escape text, then turn markdown emphasis into ReportLab paragraph markup."""
    out = escape(str(text or ""), quote=False)
    out = _CODE.sub(r'<font face="Courier">\1</font>', out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC_STAR.sub(r"<i>\1</i>", out)
    out = _ITALIC_UNDERSCORE.sub(r"<i>\1</i>", out)
    return out


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().removeprefix("|").removesuffix("|").split("|")]


def parse_blocks(markdown: str) -> list[dict]:
    """Parse markdown into blocks: section, subheading, paragraph, bullets, numbered, quote, table."""
    lines = [line.strip() for line in str(markdown or "").splitlines()]

    def starts_block(i: int) -> bool:
        line = lines[i]
        return (
            not line or bool(_BULLET.match(line)) or bool(_NUMBERED.match(line)) or line.startswith(">")
            or bool(_SUBHEADING.match(line)) or bool(_SECTION.match(line))
            or (line.startswith("|") and i + 1 < len(lines) and bool(_TABLE_DIVIDER.match(lines[i + 1])))
        )

    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
        elif _SUBHEADING.match(line):
            blocks.append({"kind": "subheading", "text": _SUBHEADING.sub("", line)})
            i += 1
        elif _SECTION.match(line):
            blocks.append({"kind": "section", "text": _SECTION.sub("", line)})
            i += 1
        elif line.startswith("|") and i + 1 < len(lines) and _TABLE_DIVIDER.match(lines[i + 1]):
            header, rows = _cells(line), []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
        elif _BULLET.match(line) or _NUMBERED.match(line):
            marker = _NUMBERED if _NUMBERED.match(line) else _BULLET
            items: list[str] = []
            while i < len(lines) and lines[i] and marker.match(lines[i]):
                items.append(marker.sub("", lines[i]))
                i += 1
                while i < len(lines) and not starts_block(i):
                    items[-1] += " " + lines[i]
                    i += 1
            blocks.append({"kind": "numbered" if marker is _NUMBERED else "bullets", "items": items})
        elif line.startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            blocks.append({"kind": "quote", "text": " ".join(quoted)})
        else:
            paragraph = [line]
            i += 1
            while i < len(lines) and not starts_block(i):
                paragraph.append(lines[i])
                i += 1
            blocks.append({"kind": "paragraph", "text": " ".join(paragraph)})
    return blocks


def markdown_styles(base: dict) -> dict:
    """Paragraph styles for markdown content, derived from the report's own palette."""
    return {
        "p": base["body_left"],
        "bullet": base["md_bullet"],
        "subheading": base["subheading"],
        "quote": base["quote"],
        "cell": base["cell"],
        "cell_head": base["cell_head"],
        "section": base["section"],
    }


def _table(block: dict, styles: dict, width: float, border: str, head_bg: str):
    header = block["header"]
    columns = len(header)
    rows = [[Paragraph(inline_markup(cell), styles["cell_head"]) for cell in header]]
    for row in block["rows"]:
        padded = (row + [""] * columns)[:columns]
        rows.append([Paragraph(inline_markup(cell), styles["cell"]) for cell in padded])
    # Column widths follow the longest cell, bounded so no column collapses.
    weights = []
    for index in range(columns):
        longest = max([len(header[index])] + [len((row + [""] * columns)[index]) for row in block["rows"]])
        weights.append(min(max(longest, 6), 60))
    total = sum(weights)
    table = Table(rows, colWidths=[width * weight / total for weight in weights], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(border)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(head_bg)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def markdown_to_flowables(markdown: str, styles: dict, width: float, *, border: str, head_bg: str) -> list:
    """Render markdown into flowables. ``styles`` comes from :func:`markdown_styles`."""
    flowables: list = []
    pending_heading: list | None = None  # keep a heading with the block that follows it
    for block in parse_blocks(markdown):
        kind = block["kind"]
        if kind in ("section", "subheading"):
            paragraph = Paragraph(inline_markup(block["text"]), styles["section" if kind == "section" else "subheading"])
            parts = [paragraph]
            if kind == "section":
                parts.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(border), spaceAfter=6))
            pending_heading = parts
            continue
        if kind == "paragraph":
            body = [Paragraph(inline_markup(block["text"]), styles["p"])]
        elif kind == "bullets":
            body = [Paragraph(inline_markup(item), styles["bullet"], bulletText="•") for item in block["items"]]
        elif kind == "numbered":
            body = [Paragraph(inline_markup(item), styles["bullet"], bulletText=f"{n}.")
                    for n, item in enumerate(block["items"], start=1)]
        elif kind == "quote":
            body = [Paragraph(inline_markup(block["text"]), styles["quote"])]
        else:
            body = [_table(block, styles, width, border, head_bg), Spacer(1, 2 * mm)]
        if pending_heading:
            flowables.append(KeepTogether([*pending_heading, body[0]]))
            flowables.extend(body[1:])
            pending_heading = None
        else:
            flowables.extend(body)
    if pending_heading:
        flowables.extend(pending_heading)
    return flowables
