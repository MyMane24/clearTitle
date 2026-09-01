"""Generate a PDF Title Verification Report for a completed case.

Pure-code assembly (no LLM call): formats the already-extracted document
data, title chain and verification results into a professional legal-style
report, then renders it to PDF with ReportLab.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from backend.logger import get_logger
from backend.services.results import build_case_results

logger = get_logger(__name__)

# Document-type -> suggested "Remarks" for the perusal table.
_DOC_REMARKS = {
    "SALE_DEED": "Original verified",
    "ENCUMBRANCE_CERTIFICATE": "Certified Copy",
    "RECORD_OF_RIGHTS": "Certified Copy",
    "PROPERTY_REGISTER_CARD": "Certified Copy",
    "GIFT_DEED": "Original verified",
    "NA_ORDER": "Certified Copy",
    "AFFIDAVIT": "Original verified",
}


def _get(obj, *keys, default=""):
    """Safely walk a nested dict/list structure, returning the first found value."""
    for key in keys:
        cur = obj
        ok = True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur and cur[part] is not None:
                cur = cur[part]
            elif isinstance(cur, list) and cur:
                cur = cur[0]
            else:
                ok = False
                break
        if ok:
            val = cur
            if isinstance(val, list):
                val = val[0] if val else ""
            return val if val not in (None, "") else default
    return default


def _fmt_date(raw: str) -> str:
    if raw is None:
        return "—"
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    if not raw:
        return "—"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return raw


# ── Section extraction helpers ──────────────────────────────────────────────
def _extract_sd(documents: list) -> dict:
    for d in documents:
        if d.get("document_type") == "SALE_DEED" and d.get("structured"):
            return d["structured"]
    for d in documents:  # fallback: any doc with a property_schedule
        if d.get("structured", {}).get("property_schedule"):
            return d["structured"]
    return {}


def _build_subject(sd: dict) -> str:
    survey = _get(sd, "property_schedule.survey_number", "property_schedule.cts_number")
    buyers = []
    for p in (sd.get("parties", {}).get("purchasers") or []):
        name = p.get("entity_name") if isinstance(p, dict) else p
        if name and name not in buyers:
            buyers.append(name)
    holders = ", ".join(buyers) if buyers else "the party"
    if survey:
        return f"Legal opinion in respect of {survey} held by {holders}."
    return f"Legal opinion in respect of the subject property held by {holders}."


def _owner_blocks(sd: dict) -> list[dict]:
    purchasers = sd.get("parties", {}).get("purchasers") or []
    if not purchasers:
        return [{"label": "Current Owner", "name": "—", "address": ""}]
    blocks = []
    for i, p in enumerate(purchasers):
        name = p.get("entity_name") or "—"
        rep = p.get("represented_by") or ""
        blocks.append({
            "label": "Current Owner" if i == 0 else f"Co-Owner {i + 1}",
            "name": name + (f" (Rep. by {rep})" if rep else ""),
            "address": p.get("address") or "",
        })
    return blocks


def _schedule_lines(sd: dict) -> tuple[list, list, str]:
    ps = sd.get("property_schedule", {}) or {}
    b = ps.get("boundaries", {}) or {}
    lines = [
        ("Survey / CTS No.", _get(ps, "survey_number", "cts_number", default="—")),
        ("Project / Location", _get(ps, "project_name", "floor_location", default="—")),
        ("Description", _get(ps, "full_schedule_description", default="—")),
    ]
    boundaries = [(d, b[attr]) for d, attr in
                  (("East", "east"), ("West", "west"), ("North", "north"), ("South", "south"))
                  if b.get(attr)]
    usage = _get(ps, "intended_usage", default="—")
    return lines, boundaries, usage


def _doc_rows(documents: list) -> list:
    rows = []
    for i, d in enumerate(documents, 1):
        doc_type = (d.get("document_type") or "DOCUMENT").replace("_", " ").title()
        s = d.get("structured") or {}
        date = _get(
            s, "file_metadata.execution_date", "file_metadata.registration_date",
            "file_metadata.search_end_date", "document_metadata.date",
            default="—",
        )
        partic = doc_type
        reg = _get(
            s, "file_metadata.registration_number",
            "file_metadata.certificate_number",
            "file_metadata.reference_number", default="",
        )
        if reg:
            partic += f" (Ref. {reg})"
        remarks = _DOC_REMARKS.get(d.get("document_type"), "Xerox Copy")
        rows.append([str(i), partic, _fmt_date(date), remarks])
    return rows


def _title_chain_text(title_chain: dict) -> str:
    story = None
    if title_chain:
        source = title_chain.get("source") if isinstance(title_chain.get("source"), dict) else {}
        story = title_chain.get("title_story") or source.get("title_story")
    if story:
        return str(story).strip()
    chain = (title_chain or {}).get("chain") or []
    if chain:
        parts = []
        for item in chain:
            date = _fmt_date(item.get("date") or item.get("execution_date") or "")
            desc = item.get("summary") or item.get("description") or item.get("transaction") or ""
            if desc:
                parts.append(f"{date}: {desc}".strip(": "))
        if parts:
            return " ".join(parts)
    return "Title chain records are not yet available for this case."


def _issues_list(verification: dict, documents: list) -> list:
    issues = []
    items = verification.get("items") or []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and str(it.get("status", "")).upper() == "NOT_VERIFIED":
                label = it.get("field") or it.get("title") or "Item"
                issues.append(f"{label}: {it.get('notes') or 'could not be verified against records.'}")
    for d in documents:
        if d.get("status") in ("failed", "classification_failed"):
            issues.append(f"{d.get('filename')} could not be read/classified: {d.get('error') or 'unknown error'}.")
    if not issues:
        summary = (verification or {}).get("summary") or {}
        overall = summary.get("overall_comment") or summary.get("headline") or ""
        if overall and "no discrepancies" not in str(overall).lower():
            issues.append(str(overall).strip())
    return issues or ["No discrepancies were identified requiring further action."]


def _conclusion(verification: dict) -> str:
    summary = (verification or {}).get("summary") or {}
    overall = summary.get("overall_comment") or summary.get("headline") or ""
    if overall:
        return str(overall).strip()
    return (
        "The verification compared the provided Sale Deed with the "
        "Encumbrance Certificate historical ledger. Please refer to the "
        "field-level verification items above for detailed findings."
    )


# ── PDF rendering ──────────────────────────────────────────────────────────
def _logo_path() -> Path | None:
    """Locate the brand logo (repo root / frontend assets or built dist)."""
    root = Path(__file__).resolve().parents[2]
    for cand in (
        root / "frontend/src/assets/clearTitle.png",
        root / "frontend/dist/assets/clearTitle.png",
    ):
        if cand.is_file():
            return cand
    assets_dir = root / "frontend/dist/assets"
    if assets_dir.is_dir():
        for f in assets_dir.iterdir():
            if "clearTitle" in f.name.lower():
                return f
    return None


def _logo_flowable(w_mm: float) -> Image:
    """Logo tight-cropped to its artwork, so the subtitle sits flush under it."""
    path = _logo_path()
    try:
        from PIL import Image as PILImage
        im = PILImage.open(path)
        bbox = im.getbbox()
        if bbox:
            im = im.crop(bbox)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return Image(buf, width=w_mm * mm, height=w_mm * mm * (im.height / im.width))
    except Exception as e:  # pragma: no cover - image issues are non-fatal
        logger.warning("Could not embed logo: %s", e)
        return None


def _styles():
    return {
        "hdrsub": ParagraphStyle("hdrsub", fontName="Helvetica-Bold", fontSize=8.5,
                                 leading=9, textColor=colors.HexColor("#999999")),
        "hdr_r": ParagraphStyle("hdr_r", fontName="Helvetica", fontSize=11, leading=15,
                                alignment=TA_RIGHT, textColor=colors.black),
        "recip": ParagraphStyle("recip", fontName="Times-Roman", fontSize=12, leading=16,
                                textColor=colors.black, spaceAfter=6),
        "subject": ParagraphStyle("subject", fontName="Times-Bold", fontSize=12, leading=16,
                                  textColor=colors.black, spaceBefore=10, spaceAfter=18),
        "section": ParagraphStyle("section", fontName="Times-Bold", fontSize=12,
                                  leading=15, spaceBefore=20, spaceAfter=8,
                                  textColor=colors.black),
        "body": ParagraphStyle("body", fontName="Times-Roman", fontSize=12, leading=19,
                               alignment=TA_JUSTIFY, textColor=colors.black, spaceAfter=10),
        "lbl": ParagraphStyle("lbl", fontName="Times-Bold", fontSize=12, leading=18,
                              alignment=TA_LEFT, textColor=colors.black),
        "val": ParagraphStyle("val", fontName="Times-Roman", fontSize=12, leading=18,
                              alignment=TA_LEFT, textColor=colors.black),
        "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=11, leading=14,
                               textColor=colors.black),
        "footer": ParagraphStyle("footer", fontName="Times-Italic", fontSize=10, leading=13,
                                 alignment=TA_CENTER, textColor=colors.black),
    }


_FOOTER_TEXT = ("This report is generated by clearTitle AI on the basis of the "
                "documents produced for verification.")


def _page_footer(canvas, doc_obj):
    canvas.saveState()
    w, h = doc_obj.pagesize
    y = 14 * mm
    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(0.75)
    canvas.line(18 * mm, y, w - 18 * mm, y)
    canvas.setFont("Times-Italic", 10)
    canvas.setFillColor(colors.black)
    canvas.drawCentredString(w / 2, y - 12, _FOOTER_TEXT)
    canvas.restoreState()


def render_report_pdf(case_id: str) -> bytes:
    data = build_case_results(case_id)
    documents = data.get("documents", [])
    title_chain = data.get("title_chain")
    verification = data.get("verification")

    ver_items = verification.get("items") or []
    ver_status = verification.get("status")
    if ver_status == "error" or not ver_items:
        raise ValueError(
            f"Verification not complete for case {case_id}; cannot generate report"
        )

    sd = _extract_sd(documents)
    owner_blocks = _owner_blocks(sd)
    sched_lines, boundaries, usage = _schedule_lines(sd)
    doc_rows = _doc_rows(documents)
    subject = _build_subject(sd)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Title Verification Report — Case {case_id}",
        author="clearTitle - AI Property Title Verification System",
    )
    st = _styles()
    story: list = []

    # Letterhead: logo + system subtitle left, Date right, black rule below
    logo = _logo_flowable(w_mm=52)
    hdr_left = []
    if logo:
        hdr_left.append(logo)
    hdr_left.append(Paragraph("AI PROPERTY TITLE VERIFICATION SYSTEM", st["hdrsub"]))
    hdr_right = Paragraph(
        f"<b>Date:</b> {datetime.now().strftime('%d.%m.%Y, %I:%M %p')}", st["hdr_r"])
    header = Table([[hdr_left, hdr_right]], colWidths=[124 * mm, 50 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(HRFlowable(width="100%", thickness=1.5,
                            color=colors.black, spaceBefore=8, spaceAfter=18))

    # Recipient + underlined uppercase subject
    story.append(Paragraph("To,<br/><b>WHOM SO EVER IT MAY CONCERN</b>", st["recip"]))
    story.append(Paragraph(f"<u>{(f'Sub:- {subject}').upper()}</u>", st["subject"]))

    def kv_table(pairs: list) -> None:
        """Label/value grid — bold label column, all values start at the same x."""
        rows = [["", Paragraph(f"<b>{lbl} :</b>", st["lbl"]) if lbl else "",
                Paragraph(val, st["val"])]
                for lbl, val in pairs]
        t = Table(rows, colWidths=[6 * mm, 38 * mm, 130 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(t)

    # 1. Current Owner
    story.append(Paragraph("1. CURRENT OWNER DETAILS (AS PER SALE DEED)", st["section"]))
    owner_pairs = []
    for blk in owner_blocks:
        owner_pairs.append((blk["label"], blk["name"]))
        if blk["address"]:
            owner_pairs.append(("Address", blk["address"]))
    kv_table(owner_pairs)

    # 2. Property Schedule
    story.append(Paragraph("2. PROPERTY SCHEDULE (AS PER SALE DEED)", st["section"]))
    if boundaries:
        sched_pairs = [(lbl, val) for lbl, val in sched_lines]
        sched_pairs.append(("Boundaries", ""))
        for d, value in boundaries:
            sched_pairs.append(("", f"To {d} : {value}"))
        sched_pairs.append(("Intended Usage", usage))
        kv_table(sched_pairs)
    else:
        kv_table([*sched_lines, ("Intended Usage", usage)])

    # 3. Documents table
    story.append(Paragraph("3. LIST OF DOCUMENTS PRODUCED FOR PERUSAL", st["section"]))
    if doc_rows:
        head = [Paragraph("<b>Sl.No.</b>", st["cell"]),
                Paragraph("<b>Particulars</b>", st["cell"]),
                Paragraph("<b>Date</b>", st["cell"]),
                Paragraph("<b>Remarks</b>", st["cell"])]
        data_rows = [[Paragraph(a, st["cell"]), Paragraph(b, st["cell"]),
                      Paragraph(c, st["cell"]), Paragraph(d, st["cell"])]
                     for a, b, c, d in doc_rows]
        t = Table([head, *data_rows],
                  colWidths=[14 * mm, 90 * mm, 35 * mm, 35 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No documents were produced for perusal.", st["body"]))

    # 4. Title Chain Audit
    story.append(Paragraph("4. TITLE CHAIN AUDIT", st["section"]))
    story.append(Paragraph(_title_chain_text(title_chain), st["body"]))

    # 5. Conclusion
    story.append(Paragraph("5. FINAL CONCLUSION / CERTIFICATE", st["section"]))
    story.append(Paragraph(_conclusion(verification), st["body"]))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buf.getvalue()
