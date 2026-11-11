"""Generate a PDF Title Verification Report for a completed case.

Pure-code assembly (no LLM call): formats the already-extracted document
data, title chain and verification results into a professional legal-style
report, then renders it to PDF with ReportLab.
"""

from __future__ import annotations

import io
from html import escape
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from backend.logger import get_logger
from backend.services.results import build_case_results

logger = get_logger(__name__)

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
