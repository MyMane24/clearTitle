"""Generate a PDF Title Verification Report for a completed case.

Pure-code assembly (no LLM call): formats the already-extracted document
data, title chain and verification results into a professional legal-style
report, then renders it to PDF with ReportLab.
"""

from __future__ import annotations

import io
from html import escape
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


def _party_name(p) -> str:
    """Party entries arrive as plain strings or as dicts with entity_name."""
    if isinstance(p, dict):
        return str(p.get("entity_name") or "").strip()
    return str(p or "").strip()


def _build_subject(sd: dict) -> str:
    survey = _get(sd, "property_schedule.survey_number", "property_schedule.cts_number")
    buyers = []
    for p in (sd.get("parties", {}).get("purchasers") or []):
        name = _party_name(p)
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
        meta = p if isinstance(p, dict) else {}
        blocks.append({
            "label": "Current Owner" if i == 0 else f"Co-Owner {i + 1}",
            "name": (_party_name(p) or "—")
            + (f" (Rep. by {meta['represented_by']})" if meta.get("represented_by") else ""),
            "address": meta.get("address") or "",
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
        remarks = "Certified Copy"
        rows.append([str(i), partic, _fmt_date(date), remarks])
    return rows


# EC ledger transaction type keyword -> document(s) needed to verify it.
_AREA_REQUIRED_DOCS = [
    ("sale", "Sale Deed"),
    ("gift", "Gift Deed"),
    ("partition", "Partition Deed"),
    ("exchange", "Exchange Deed"),
    ("lease", "Lease Deed"),
    ("mortgage", "Mortgage Deed / Loan Agreement"),
    ("loan", "Loan Agreement"),
    ("borrow", "Loan Agreement / Mortgage Deed"),
    ("charge", "Charge / Mortgage Deed"),
    ("release", "Release Deed"),
    ("satisfaction", "Release / Satisfaction Deed"),
    ("discharge", "Discharge / Release Deed"),
    ("relinquish", "Relinquishment Deed"),
    ("will", "Will / Probate"),
    ("bequest", "Will / Probate"),
    ("agreement", "Agreement of Sale"),
    ("attachment", "Court Attachment Order"),
    ("award", "Award / Court Decree"),
    ("succession", "Succession Certificate"),
    ("heir", "Legal Heir Certificate"),
]
















# EC ledger transaction type keyword -> document(s) needed to verify it.
_AREA_REQUIRED_DOCS = [
    ("sale", "Sale Deed"),
    ("gift", "Gift Deed"),
    ("partition", "Partition Deed"),
    ("exchange", "Exchange Deed"),
    ("lease", "Lease Deed"),
    ("mortgage", "Mortgage Deed / Loan Agreement"),
    ("loan", "Loan Agreement"),
    ("borrow", "Loan Agreement / Mortgage Deed"),
    ("charge", "Charge / Mortgage Deed"),
    ("release", "Release Deed"),
    ("satisfaction", "Release / Satisfaction Deed"),
    ("discharge", "Discharge / Release Deed"),
    ("relinquish", "Relinquishment Deed"),
    ("will", "Will / Probate"),
    ("bequest", "Will / Probate"),
    ("agreement", "Agreement of Sale"),
    ("attachment", "Court Attachment Order"),
    ("award", "Award / Court Decree"),
    ("succession", "Succession Certificate"),
    ("heir", "Legal Heir Certificate"),
]


def _docs_required_for_transaction(tx: dict) -> str:
    ttype = str(tx.get("transaction_type") or "").lower()
    docs = [doc for keyword, doc in _AREA_REQUIRED_DOCS if keyword in ttype]
    if not docs:
        docs = ["Registered document evidencing the transaction"]
    return "; ".join(dict.fromkeys(docs))


def _parties_effect(tx: dict) -> str:
    parties = tx.get("parties") or {}
    names = []
    for role in ("vendors", "purchasers"):
        for party in parties.get(role) or []:
            name = _party_name(party)
            if name and name not in names:
                names.append(name)
    return " → ".join(names)


def _required_docs_rows(documents: list) -> list:
    rows = []
    for document in documents:
        if document.get("document_type") != "ENCUMBRANCE_CERTIFICATE":
            continue
        ledger = (document.get("structured") or {}).get("historical_ledger") or []
        for index, transaction in enumerate(ledger, 1):
            transaction_type = str(transaction.get("transaction_type") or "").strip()
            instrument = transaction_type.title() if transaction_type else "EC ledger transaction"
            registration = str(transaction.get("registration_reference") or "").strip()
            if registration:
                instrument += f" (Ref. {registration})"
            rows.append([
                str(index),
                _fmt_date(transaction.get("execution_date") or ""),
                instrument,
                _parties_effect(transaction) or "—",
                _docs_required_for_transaction(transaction),
            ])
    return rows


# ── ClearTitle agent report sections ─────────────────────────────────────────
def _agent_required_docs_rows(agent: dict) -> list:
    """Transactions whose verification needs more evidence (missing documents)."""
    rows = []
    for t in agent.get("transactions") or []:
        missing = t.get("required_documents") or []
        if not missing:
            continue
        req = "; ".join(
            str(m.get("document_type") or "Document")
            for m in missing if isinstance(m, dict)
        )
        metadata = t.get("transaction_metadata") or {}
        vendors = ", ".join(str(value) for value in metadata.get("vendors") or [])
        purchasers = ", ".join(str(value) for value in metadata.get("purchasers") or [])
        parties = f"{vendors} → {purchasers}" if vendors or purchasers else "—"
        rows.append([
            _fmt_date(metadata.get("executed_date") or metadata.get("registration_date") or ""),
            str(metadata.get("transaction_type") or metadata.get("document_type") or "Transaction"),
            parties,
            req or "—",
        ])
    return rows


def _agent_title_text(agent: dict) -> str:
    story = str(((agent.get("title_chain") or {}).get("title_story")) or "").strip()
    if story:
        return story
    parts = []
    for t in agent.get("transactions") or []:
        date = _fmt_date(t.get("date") or "")
        desc = t.get("explanation") or t.get("type") or ""
        if desc:
            parts.append(f"{date}: {desc}".strip(": "))
    return " ".join(parts) or "Title chain records are not yet available for this case."


def _agent_conclusion(agent: dict) -> str:
    parts = [agent.get("headline"), agent.get("report")]
    text = "\n\n".join(str(p).strip() for p in parts if p and str(p).strip())
    if text:
        return text
    status = str(agent.get("overall_status") or "").strip()
    if status:
        return f"Overall verification status: {status}."
    return ("The verification report is not yet available. Please refer to the "
            "findings above.")


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


def _logo_flowable(w_mm: float) -> Image | None:
    """Logo tight-cropped to its artwork, so the subtitle sits flush under it."""
    path = _logo_path()
    if not path:
        return None
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

_PROPERTY_FOOTER_TEXT = "Property Title Verification Report"


def _property_footer_text(sd: dict) -> str:
    ps = sd.get("property_schedule") or {}
    plot = _get(ps, "apartment_or_shop_number", "plot_or_site_number")
    cts = _get(ps, "cts_number", "survey_number")
    text = "Property Title Verification Report"
    if plot:
        text += f" - Plot No. {plot}"
    if cts:
        text += f", CTS {cts}"
    return text


def _count_page(canvas, doc_obj):
    doc_obj._ct_count = getattr(doc_obj, "_ct_count", 0) + 1


def _page_footer(canvas, doc_obj):
    canvas.saveState()
    w, h = doc_obj.pagesize
    y = 14 * mm
    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(0.75)
    canvas.line(18 * mm, y, w - 18 * mm, y)
    canvas.setFont("Times-Italic", 10)
    canvas.setFillColor(colors.black)
    total = getattr(doc_obj, "_ct_total_pages", None)
    if total and canvas.getPageNumber() == total:
        canvas.drawCentredString(w / 2, y - 12, _FOOTER_TEXT)
    else:
        text = getattr(doc_obj, "_ct_footer_text", None) or _PROPERTY_FOOTER_TEXT
        canvas.drawString(18 * mm, y - 12, text)
    canvas.restoreState()


def render_report_pdf(case_id: str) -> bytes:
    data = build_case_results(case_id)
    agent = data.get("agent") or {}

    transactions = agent.get("transactions") or []

    if agent.get("status") == "error" or not transactions:
        raise ValueError(
            f"Verification not complete for case {case_id}; cannot generate report"
        )

    st = _styles()
    sd = _extract_sd(data.get("documents", []))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Title Verification Report — Case {case_id}",
        author="clearTitle - AI Property Title Verification System",
    )
    doc._ct_footer_text = _property_footer_text(sd)
    count_buf = io.BytesIO()
    count_doc = SimpleDocTemplate(
        count_buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )
    count_doc.build(_report_story(data, st),
                    onFirstPage=_count_page, onLaterPages=_count_page)
    doc._ct_total_pages = getattr(count_doc, "_ct_count", 1)
    doc.build(_report_story(data, st),
              onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buf.getvalue()


def _required_document_entries(agent: dict) -> list[dict]:
    entries = []
    for transaction in agent.get("transactions") or []:
        metadata = transaction.get("transaction_metadata") or {}
        for requirement in transaction.get("required_documents") or []:
            if not isinstance(requirement, dict):
                continue
            document_type = str(requirement.get("document_type") or "").strip()
            if not document_type:
                continue
            entries.append({
                "sequence": transaction.get("sequence") or "—",
                "transaction": str(metadata.get("transaction_type") or metadata.get("document_type") or "Transaction"),
                "status": str(transaction.get("status") or "PENDING"),
                "document_type": document_type,
                "reason": str(requirement.get("reason") or "").strip(),
            })
    return entries


def _property_identity_lines(agent: dict) -> list[str]:
    chain = agent.get("title_chain")
    identity = (
        chain.get("property_identity")
        if isinstance(chain, dict) else None
    ) or agent.get("property_identity") or {}
    details = identity.get("details") if isinstance(identity, dict) else None
    if isinstance(details, list):
        lines = []
        for item in details:
            if isinstance(item, dict):
                label = str(item.get("label") or "Property").strip()
                value = str(item.get("value") or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            elif str(item).strip():
                lines.append(str(item).strip())
        return lines
    if isinstance(identity, dict):
        return [f"{key.replace('_', ' ').title()}: {value}" for key, value in identity.items() if value and not isinstance(value, (dict, list))]
    return []


def _required_document_status_label(status: str) -> str:
    normalized = str(status or "PENDING").upper()
    if normalized in {"PENDING", "PENDING_NOT_VERIFIED"}:
        return "Pending"
    return normalized.replace("_", " ").title()


def render_required_documents_pdf(case_id: str) -> bytes:
    """Render a checklist from exact per-transaction saved requirements only."""
    data = build_case_results(case_id)
    agent = data.get("agent") or {}
    entries = _required_document_entries(agent)
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Required Documents Checklist",
        author="ClearTitle",
    )
    story = [
        Paragraph("REQUIRED DOCUMENTS CHECKLIST", styles["section"]),
        Paragraph("PROPERTY IDENTITY", styles["body"]),
    ]
    identity_lines = _property_identity_lines(agent)
    if identity_lines:
        story.extend(Paragraph(escape(line), styles["body"]) for line in identity_lines)
    else:
        story.append(Paragraph("Property identity is not available in the saved title-chain result.", styles["body"]))
    story.extend([
        Paragraph(f"Generated: {datetime.now().strftime('%d.%m.%Y, %I:%M %p')}", styles["body"]),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#334155"), spaceBefore=8, spaceAfter=12),
    ])
    if not entries:
        story.append(Paragraph("No outstanding transaction-specific document requests are recorded.", styles["body"]))
    else:
        cell = styles["cell"]
        table_rows = [[
            Paragraph("Transaction", cell), Paragraph("Status", cell),
            Paragraph("Required document / reason", cell),
        ]]
        for entry in entries:
            tx_label = f"Transaction {escape(str(entry['sequence']))} — {escape(entry['transaction'])}"
            status = escape(_required_document_status_label(entry["status"]))
            requirement = f"<b>{escape(entry['document_type'])}</b>"
            if entry["reason"]:
                requirement += f"<br/>{escape(entry['reason'])}"
            table_rows.append([
                Paragraph(tx_label, cell), Paragraph(status, cell), Paragraph(requirement, cell),
            ])
        table = Table(table_rows, colWidths=[55 * mm, 34 * mm, 85 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
    document.build(story)
    return buffer.getvalue()


def _report_story(data: dict, st: dict) -> list:
    documents = data.get("documents", [])
    agent = data.get("agent") or {}

    sd = _extract_sd(documents)
    owner_blocks = _owner_blocks(sd)
    sched_lines, boundaries, usage = _schedule_lines(sd)
    doc_rows = _doc_rows(documents)
    subject = _build_subject(sd)

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

    story.append(Paragraph(
        "The verification carried out in this report is limited to the documents produced "
        "for perusal above (the Sale Deed and Encumbrance Certificate uploaded by the "
        "applicant). It does not certify the underlying registered transactions contained "
        "in the Encumbrance Certificate ledger.", st["body"]))

    # 4. Documents required for complete verification
    story.append(Paragraph("4. DOCUMENTS REQUIRED FOR COMPLETE VERIFICATION", st["section"]))
    req_rows = _agent_required_docs_rows(agent) or _required_docs_rows(documents)
    if req_rows:
        head = [Paragraph("<b>Date</b>", st["cell"]),
                Paragraph("<b>Instrument / Event</b>", st["cell"]),
                Paragraph("<b>Parties / Effect</b>", st["cell"]),
                Paragraph("<b>Required Documents</b>", st["cell"])]
        data_rows = [[Paragraph(b, st["cell"]), Paragraph(c, st["cell"]),
                      Paragraph(d, st["cell"]), Paragraph(e, st["cell"])]
                     for a, b, c, d, e in req_rows]
        t = Table([head, *data_rows],
                  colWidths=[34 * mm, 44 * mm, 44 * mm, 52 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.95, 0.95, 0.95)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (0, -1), 3),
            ("RIGHTPADDING", (0, 0), (0, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph(
            "No additional documents are indicated as required for verification.",
            st["body"]))

    # 5. Title Chain Audit
    story.append(Paragraph("5. TITLE CHAIN AUDIT", st["section"]))
    tc_text = _agent_title_text(agent)
    for p in tc_text.split("\n\n"):
        p_clean = p.strip()
        if p_clean:
            story.append(Paragraph(p_clean, st["body"]))

    # 6. Conclusion
    story.append(Paragraph("6. FINAL CONCLUSION / CERTIFICATE", st["section"]))
    conc_text = _agent_conclusion(agent)
    for p in conc_text.split("\n\n"):
        p_clean = p.strip()
        if p_clean:
            story.append(Paragraph(p_clean, st["body"]))

    return story
