"""The due diligence report as a PDF, laid out like an advocate's Report of
Investigation of Title: particulars, documents scrutinised, details of each
document, history of title, certificate, the documents still required, and a
signature block for the reviewing advocate. Drawn with reportlab (no system
libraries needed).
"""

from __future__ import annotations

import unicodedata
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from backend.schemas.due_diligence import DueDiligenceReport

LOGO = Path(__file__).resolve().parents[2] / "assets" / "clearTitle.png"
TITLE = "Report of Investigation of Title in respect of Immovable Property"
COPY_TYPE = "Scanned copy"
OPINION_WORDS = {
    "CLEAR": "Title clear",
    "CLEAR_SUBJECT_TO": "Title clear, subject to conditions",
    "NOT_CLEAR": "Not safe to proceed",
}

_BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=11.5, leading=17)
STYLES = {
    "title": ParagraphStyle(
        "title", parent=_BODY, fontName="Times-Bold", fontSize=17, leading=22,
        alignment=TA_CENTER, spaceAfter=14,
    ),
    "heading": ParagraphStyle(
        "heading", parent=_BODY, fontName="Times-Bold", fontSize=12, spaceBefore=12, spaceAfter=6,
    ),
    "para": ParagraphStyle(
        "para", parent=_BODY, alignment=TA_JUSTIFY, firstLineIndent=1.2 * cm, spaceAfter=8,
    ),
    "cell": ParagraphStyle("cell", parent=_BODY, fontSize=10.5, leading=14),
    "cell_bold": ParagraphStyle("cell_bold", parent=_BODY, fontName="Times-Bold", fontSize=10.5, leading=14),
    "small": ParagraphStyle("small", parent=_BODY, fontSize=10, leading=14),
}  # fmt: skip
_GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
)


def printable(text: str) -> str:
    """Text the built-in Times font can draw: compatibility forms unfolded ("Ⅲ" -> "III"),
    and any character it has no glyph for (e.g. Kannada) shown as "?" instead of a box."""
    folded = unicodedata.normalize("NFKC", text or "").replace("\u20b9", "Rs. ")
    return folded.encode("cp1252", errors="replace").decode("cp1252")


def _p(text: str, style: str = "para") -> Paragraph:
    return Paragraph(escape(printable(text)), STYLES[style])


MARGIN, BOTTOM = 2 * cm, 2.2 * cm
FIRST_TOP, LATER_TOP = 2.9 * cm, 2 * cm  # the first page leaves room for the letterhead


def _footer(canvas, doc) -> None:
    """A rule and the page number at the foot of every page."""
    width, _ = A4
    canvas.saveState()
    canvas.setFont("Times-Roman", 9)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, 1.6 * cm, width - MARGIN, 1.6 * cm)
    canvas.drawRightString(width - MARGIN, 1.1 * cm, f"{doc.page} | Page")
    canvas.restoreState()


def _letterhead(canvas, doc) -> None:
    """The ClearTitle letterhead, on the first page only, and the footer."""
    width, height = A4
    canvas.saveState()
    if LOGO.exists():
        canvas.drawImage(
            ImageReader(str(LOGO)), MARGIN, height - 2.1 * cm, width=3.3 * cm, height=1.1 * cm,
            mask="auto", preserveAspectRatio=True,
        )  # fmt: skip
    canvas.setFont("Times-Roman", 9)
    canvas.drawRightString(width - MARGIN, height - 1.55 * cm, "Title verification report")
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, height - 2.3 * cm, width - MARGIN, height - 2.3 * cm)
    canvas.restoreState()
    _footer(canvas, doc)


def _document(buffer: BytesIO) -> BaseDocTemplate:
    """A4 pages: the first with the letterhead, the rest with only the page number."""
    width, height = A4
    doc = BaseDocTemplate(buffer, pagesize=A4, title=TITLE, author="ClearTitle")

    def frame(top: float, name: str) -> Frame:
        return Frame(MARGIN, BOTTOM, width - 2 * MARGIN, height - top - BOTTOM, id=name)

    doc.addPageTemplates(
        [
            PageTemplate("first", [frame(FIRST_TOP, "first")], onPage=_letterhead),
            PageTemplate("later", [frame(LATER_TOP, "later")], onPage=_footer),
        ]
    )
    return doc


def _particulars(report: DueDiligenceReport) -> Table:
    description = [_p(report.property_description or "Not stated.", "cell")]
    bounds = report.boundaries.model_dump()
    lines = [
        f"<b>{side.title()}</b> : {escape(printable(value))}"
        for side, value in bounds.items()
        if value
    ]
    if lines:
        description.append(Spacer(1, 6))
        description.append(Paragraph("<br/>".join(lines), STYLES["cell"]))
    description += [
        Spacer(1, 6),
        _p("(Hereinafter referred to as the Property Under Opinion)", "cell"),
    ]
    rows = [
        [_p("A.", "cell"), _p("Name of the person holding title to the immovable property:", "cell"),
         _p(", ".join(report.title_holders) or "Not stated.", "cell")],
        [_p("B.", "cell"), _p("Complete description of the immovable property:", "cell"), description],
    ]  # fmt: skip
    table = Table(rows, colWidths=[1 * cm, 6 * cm, 10 * cm])
    table.setStyle(_GRID)
    return table


def _documents(report: DueDiligenceReport) -> Table:
    header = [
        _p("Sl. No.", "cell_bold"),
        _p("Date of Document", "cell_bold"),
        _p("Nature of Document", "cell_bold"),
        _p("Original / Certified / Copy", "cell_bold"),
    ]
    rows = [
        [_p(f"{n}.", "cell"), _p(row.date, "cell"), _p(row.nature, "cell"), _p(COPY_TYPE, "cell")]
        for n, row in enumerate(report.documents, start=1)
    ]  # fmt: skip
    table = Table([header, *rows], colWidths=[1.3 * cm, 2.9 * cm, 9.6 * cm, 3.2 * cm], repeatRows=1)
    table.setStyle(_GRID)
    return table


def _signature(report: DueDiligenceReport) -> KeepTogether:
    prepared = report.prepared_on.strftime("%d/%m/%Y") if report.prepared_on else ""
    left = [_p(f"Date: {prepared}", "small")]
    right = [
        _p("To be reviewed and signed by an advocate.", "small"),
        Spacer(1, 26),
        _p("Advocate's signature: ________________________", "small"),
        Spacer(1, 8),
        _p("Name and enrolment no.: ______________________", "small"),
    ]
    table = Table([[left, right]], colWidths=[7 * cm, 10 * cm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return KeepTogether([Spacer(1, 18), table])


def render_pdf(report: DueDiligenceReport) -> bytes:
    """The report as PDF bytes."""
    buffer = BytesIO()
    doc = _document(buffer)
    story = [NextPageTemplate("later"), Paragraph(f"<u>{escape(TITLE)}</u>", STYLES["title"])]
    if not report.documents:  # saved before the advocate-style report existed
        story += [
            _p(f"Opinion: {OPINION_WORDS[report.opinion]}.", "heading"),
            *(_p(reason) for reason in report.reasons),
            _p(
                "This report was written in an older format. Run verification again for the full report."
            ),
        ]
        doc.build(story)
        return buffer.getvalue()
    story += [
        _p("I. Particulars of the title holder and the immovable property in respect of which "
           "this opinion is given:", "heading"),
        _particulars(report),
        _p("II. Particulars of the documents scrutinised, in respect of the aforesaid immovable "
           "property, serially and chronologically:", "heading"),
        _documents(report),
        _p("III. DETAILS OF DOCUMENTS SCRUTINISED:", "heading"),
        *(_p(detail.text) for detail in report.document_details),
        _p("IV. HISTORY OF TITLE:", "heading"),
        *(_p(paragraph) for paragraph in report.history),
        _p("V. CERTIFICATE:", "heading"),
        _p(report.certificate or ""),
        _p("ANNEXURE: DOCUMENTS STILL REQUIRED", "heading"),
    ]  # fmt: skip
    if report.documents_required:
        story += [
            _p(f"{n}. {item.document}: {item.reason}", "small")
            for n, item in enumerate(report.documents_required, start=1)
        ]
    else:
        story.append(_p("None.", "small"))
    story.append(_signature(report))
    doc.build(story)
    return buffer.getvalue()
