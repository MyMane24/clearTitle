/**
 * pdf_report.js
 * Generates a downloadable PDF Verification Report using jsPDF + jsPDF-AutoTable.
 * Called via window.downloadVerificationPDF(data, caseId)
 */

window.downloadVerificationPDF = function (data, caseId) {
  if (!window.jspdf || !window.jspdf.jsPDF) {
    alert("PDF library not loaded. Please refresh the page and try again.");
    return;
  }

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });

  // ── Palette ────────────────────────────────────────────────────────────────
  const NAVY   = [15, 40, 80];
  const BLUE   = [37, 99, 235];
  const GREEN  = [22, 163, 74];
  const RED    = [220, 38, 38];
  const AMBER  = [217, 119, 6];
  const LGRAY  = [248, 250, 252];
  const MGRAY  = [226, 232, 240];
  const DGRAY  = [100, 116, 139];
  const BLACK  = [17, 24, 39];
  const WHITE  = [255, 255, 255];

  const PW = 210; // A4 page width mm
  const PH = 297; // A4 page height mm
  const ML = 14;  // left margin
  const MR = 14;  // right margin
  const CW = PW - ML - MR; // content width
  let y = 0;     // current Y cursor

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function safe(v) { return (v === null || v === undefined) ? "" : String(v); }

  function sevColor(sev) {
    const s = safe(sev).toLowerCase();
    if (s === "critical") return RED;
    if (s === "high")     return RED;
    if (s === "medium")   return AMBER;
    return [34, 197, 94]; // low → green
  }

  function sevBadge(sev) {
    const s = safe(sev).toLowerCase();
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : "—";
  }

  function newPageIfNeeded(needed = 20) {
    if (y + needed > PH - 16) {
      doc.addPage();
      drawPageFooter();
      y = 20;
    }
  }

  function drawHRule(color = MGRAY, thickness = 0.3) {
    doc.setDrawColor(...color);
    doc.setLineWidth(thickness);
    doc.line(ML, y, PW - MR, y);
    y += 3;
  }

  function drawPageFooter() {
    const pg = doc.internal.getCurrentPageInfo().pageNumber;
    const total = "—";
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(...DGRAY);
    doc.text(
      `Property Verification Engine  ·  Case ${caseId}  ·  Generated ${new Date().toLocaleDateString("en-IN", {day:"2-digit",month:"short",year:"numeric"})}`,
      ML, PH - 8
    );
    doc.text(`Page ${pg}`, PW - MR, PH - 8, { align: "right" });
    doc.setDrawColor(...MGRAY);
    doc.setLineWidth(0.3);
    doc.line(ML, PH - 12, PW - MR, PH - 12);
  }

  // Section header
  function sectionHeader(title, iconText = "") {
    newPageIfNeeded(18);
    doc.setFillColor(...NAVY);
    doc.roundedRect(ML, y, CW, 9, 1, 1, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(10);
    doc.setTextColor(...WHITE);
    doc.text(`${iconText}  ${title}`, ML + 4, y + 6);
    y += 13;
  }

  function subHeader(title) {
    newPageIfNeeded(12);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(...NAVY);
    doc.text(title, ML, y + 4);
    y += 7;
    doc.setDrawColor(...BLUE);
    doc.setLineWidth(0.4);
    doc.line(ML, y, ML + doc.getTextWidth(title) + 2, y);
    y += 4;
  }

  function labelValue(label, value, labelW = 55) {
    newPageIfNeeded(8);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(8.5);
    doc.setTextColor(...DGRAY);
    doc.text(safe(label), ML, y);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...BLACK);
    const valLines = doc.splitTextToSize(safe(value) || "—", CW - labelW - 2);
    doc.text(valLines, ML + labelW, y);
    y += Math.max(5, valLines.length * 4.5);
  }

  function bodyText(text, color = BLACK, size = 9) {
    newPageIfNeeded(8);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(size);
    doc.setTextColor(...color);
    const lines = doc.splitTextToSize(safe(text), CW);
    doc.text(lines, ML, y);
    y += lines.length * 4.5 + 2;
  }

  function bulletList(items, color = BLACK) {
    (items || []).forEach(item => {
      newPageIfNeeded(7);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(8.5);
      doc.setTextColor(...DGRAY);
      doc.text("•", ML + 1, y);
      doc.setTextColor(...color);
      const lines = doc.splitTextToSize(safe(item), CW - 8);
      doc.text(lines, ML + 5, y);
      y += lines.length * 4.5 + 1;
    });
  }

  function verdictBox(text, isPass) {
    newPageIfNeeded(20);
    const boxColor = isPass ? [220, 252, 231] : [254, 226, 226];
    const textColor = isPass ? GREEN : RED;
    const borderColor = isPass ? GREEN : RED;
    doc.setFillColor(...boxColor);
    doc.setDrawColor(...borderColor);
    doc.setLineWidth(0.8);
    doc.roundedRect(ML, y, CW, 14, 2, 2, "FD");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    doc.setTextColor(...textColor);
    doc.text(isPass ? "✔  SAFE TO PROCEED" : "✘  DO NOT PROCEED — FLAGGED", ML + 5, y + 5.5);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8.5);
    doc.setTextColor(...BLACK);
    const reasonLines = doc.splitTextToSize(safe(text), CW - 10);
    doc.text(reasonLines, ML + 5, y + 10);
    y += 14 + reasonLines.length * 4 + 4;
  }

  // ── Page 1: Cover ──────────────────────────────────────────────────────────
  // Navy top bar
  doc.setFillColor(...NAVY);
  doc.rect(0, 0, PW, 48, "F");

  // Logo placeholder (white box, replace with actual logo if available)
  try {
    const logoImg = document.querySelector(".header-logo");
    if (logoImg && logoImg.complete && logoImg.naturalWidth > 0) {
      const canvas = document.createElement("canvas");
      canvas.width = logoImg.naturalWidth;
      canvas.height = logoImg.naturalHeight;
      canvas.getContext("2d").drawImage(logoImg, 0, 0);
      const imgData = canvas.toDataURL("image/png");
      const aspect = logoImg.naturalWidth / logoImg.naturalHeight;
      const logoH = 12;
      const logoW = logoH * aspect;
      doc.addImage(imgData, "PNG", ML, 8, logoW, logoH);
    }
  } catch (_) {}

  doc.setFont("helvetica", "bold");
  doc.setFontSize(20);
  doc.setTextColor(...WHITE);
  doc.text("Property Verification Report", ML, 34);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(180, 200, 230);
  doc.text("Karnataka Property Document Intelligence System", ML, 40);

  // Case info box
  doc.setFillColor(...LGRAY);
  doc.setDrawColor(...MGRAY);
  doc.setLineWidth(0.4);
  doc.roundedRect(ML, 54, CW, 36, 2, 2, "FD");

  const db = data.dashboard || {};
  const opinion = data.final_opinion || {};
  const isFlagged = db.overall_status !== "PASS";
  const riskScore = db.risk_score || 0;
  const statusColor = isFlagged ? RED : GREEN;
  const statusText = isFlagged ? "FLAGGED — DO NOT PROCEED" : "PASS — SAFE TO PROCEED";

  doc.setFont("helvetica", "bold");
  doc.setFontSize(8);
  doc.setTextColor(...DGRAY);
  doc.text("CASE ID", ML + 5, 62);
  doc.text("VERIFICATION DATE", ML + 65, 62);
  doc.text("OVERALL STATUS", ML + 125, 62);

  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  doc.setTextColor(...BLACK);
  doc.text(safe(caseId), ML + 5, 70);

  doc.setFontSize(10);
  doc.text(new Date().toLocaleDateString("en-IN", {day:"2-digit",month:"long",year:"numeric"}), ML + 65, 70);

  doc.setTextColor(...statusColor);
  doc.setFontSize(9);
  doc.text(statusText, ML + 125, 70);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.setTextColor(...DGRAY);
  doc.text("RISK SCORE", ML + 5, 80);
  doc.text("DOCUMENTS PROCESSED", ML + 65, 80);
  doc.text("CRITICAL / HIGH FINDINGS", ML + 125, 80);

  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.setTextColor(...BLACK);
  doc.text(`${riskScore} / 100  (${safe(db.risk_label || "Low Risk")})`, ML + 5, 86);
  doc.text(`${db.documents_processed || 0}`, ML + 65, 86);
  doc.setTextColor(...RED);
  doc.text(`${db.critical_findings || 0}`, ML + 125, 86);

  y = 100;
  drawHRule(MGRAY);

  // Executive summary
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9);
  doc.setTextColor(...NAVY);
  doc.text("Executive Summary", ML, y);
  y += 6;
  bodyText(opinion.executive_summary || db.recommended_action || "See full report below.", DGRAY, 8.5);

  y += 4;
  drawHRule(MGRAY);

  // Quick stats row
  const statItems = [
    { label: "Total Findings", val: opinion.total_findings || 0, color: BLACK },
    { label: "Critical",        val: opinion.critical || 0,       color: RED },
    { label: "High",            val: (db.critical_findings || 0) - (opinion.critical || 0), color: RED },
    { label: "Medium",          val: opinion.medium || 0,         color: AMBER },
    { label: "Low",             val: opinion.low || 0,            color: GREEN },
    { label: "Missing Docs",    val: db.missing_documents_count || 0, color: AMBER },
  ];

  const boxW = CW / statItems.length;
  statItems.forEach((s, i) => {
    const bx = ML + i * boxW;
    doc.setFillColor(...WHITE);
    doc.setDrawColor(...MGRAY);
    doc.setLineWidth(0.3);
    doc.roundedRect(bx, y, boxW - 2, 18, 1, 1, "FD");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(...s.color);
    doc.text(String(s.val), bx + boxW / 2 - 1, y + 9, { align: "center" });
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.setTextColor(...DGRAY);
    doc.text(s.label, bx + boxW / 2 - 1, y + 14.5, { align: "center" });
  });
  y += 22;

  drawPageFooter();

  // ── Section 1: Cross-Document Inconsistencies ──────────────────────────────
  const crossFindings = data.cross_doc_findings || [];
  if (crossFindings.length > 0) {
    doc.addPage();
    drawPageFooter();
    y = 20;
    sectionHeader("Cross-Document Inconsistencies", "1");

    const crossRows = crossFindings.map((f, i) => [
      i + 1,
      safe(f.title),
      sevBadge(f.severity),
      safe(f.what_was_found || f.what_was_detected || "").substring(0, 120),
    ]);

    doc.autoTable({
      startY: y,
      head: [["#", "Finding Title", "Severity", "What Was Found"]],
      body: crossRows,
      margin: { left: ML, right: MR },
      styles: { fontSize: 8, cellPadding: 3, lineColor: MGRAY, lineWidth: 0.2 },
      headStyles: { fillColor: NAVY, textColor: WHITE, fontStyle: "bold", fontSize: 8.5 },
      alternateRowStyles: { fillColor: LGRAY },
      columnStyles: {
        0: { cellWidth: 8, halign: "center" },
        1: { cellWidth: 55 },
        2: { cellWidth: 22, halign: "center" },
        3: { cellWidth: CW - 8 - 55 - 22 },
      },
      didParseCell: function(hookData) {
        if (hookData.section === "body" && hookData.column.index === 2) {
          const sev = hookData.cell.raw.toLowerCase();
          if (sev === "critical" || sev === "high") hookData.cell.styles.textColor = RED;
          else if (sev === "medium") hookData.cell.styles.textColor = AMBER;
          else hookData.cell.styles.textColor = GREEN;
          hookData.cell.styles.fontStyle = "bold";
        }
      },
      didDrawPage: function() { drawPageFooter(); y = doc.lastAutoTable.finalY + 6; }
    });
    y = doc.lastAutoTable.finalY + 10;

    // Detail cards for critical/high findings
    const critical = crossFindings.filter(f => ["critical","high"].includes(safe(f.severity).toLowerCase()));
    if (critical.length > 0) {
      subHeader("Critical & High Severity Details");
      critical.forEach((f, i) => {
        newPageIfNeeded(40);
        doc.setFillColor(254, 242, 242);
        doc.setDrawColor(...RED);
        doc.setLineWidth(0.5);
        doc.roundedRect(ML, y, CW, 5, 1, 1, "FD");
        doc.setFont("helvetica", "bold");
        doc.setFontSize(9);
        doc.setTextColor(...RED);
        doc.text(`  ${i + 1}. ${safe(f.title)}`, ML + 2, y + 3.5);
        y += 7;

        const evidenceText = (f.evidence || []).map(e => `${safe(e.source)}: ${safe(e.detail)}`).join("  |  ");
        labelValue("Severity:", sevBadge(f.severity));
        labelValue("Detected:", f.what_was_found || f.what_was_detected || "—");
        labelValue("Evidence:", evidenceText || "—");
        labelValue("Impact:", f.impact || "—");
        labelValue("Why Flagged:", f.why_flagged || f.reason || "—");
        if ((f.legal_references || []).length > 0) {
          labelValue("Legal Ref:", f.legal_references.join(", "));
        }
        y += 3;
        doc.setDrawColor(...MGRAY);
        doc.setLineWidth(0.2);
        doc.line(ML, y, PW - MR, y);
        y += 5;
      });
    }
  }

  // ── Section 2: Per-Document Findings ──────────────────────────────────────
  const perDocFindings = data.per_doc_findings || {};
  const perDocKeys = Object.keys(perDocFindings);

  if (perDocKeys.length > 0) {
    doc.addPage();
    drawPageFooter();
    y = 20;
    sectionHeader("Per-Document Verification Findings", "2");

    perDocKeys.forEach(docType => {
      const findings = perDocFindings[docType] || [];
      if (!findings.length) return;

      newPageIfNeeded(16);
      subHeader(docType.replace(/_/g, " "));

      const rows = findings.map((f, i) => [
        i + 1,
        safe(f.title),
        sevBadge(f.severity),
        safe(f.what_was_found || f.what_was_detected || "").substring(0, 100),
      ]);

      doc.autoTable({
        startY: y,
        head: [["#", "Check", "Severity", "Finding"]],
        body: rows,
        margin: { left: ML, right: MR },
        styles: { fontSize: 8, cellPadding: 3, lineColor: MGRAY, lineWidth: 0.2 },
        headStyles: { fillColor: [30, 58, 138], textColor: WHITE, fontStyle: "bold", fontSize: 8 },
        alternateRowStyles: { fillColor: LGRAY },
        columnStyles: {
          0: { cellWidth: 8, halign: "center" },
          1: { cellWidth: 50 },
          2: { cellWidth: 22, halign: "center" },
          3: { cellWidth: CW - 8 - 50 - 22 },
        },
        didParseCell: function(hookData) {
          if (hookData.section === "body" && hookData.column.index === 2) {
            const sev = hookData.cell.raw.toLowerCase();
            if (sev === "critical" || sev === "high") hookData.cell.styles.textColor = RED;
            else if (sev === "medium") hookData.cell.styles.textColor = AMBER;
            else hookData.cell.styles.textColor = GREEN;
            hookData.cell.styles.fontStyle = "bold";
          }
        },
        didDrawPage: function() { drawPageFooter(); }
      });
      y = doc.lastAutoTable.finalY + 8;
    });
  }

  // ── Section 3: Missing Documents ──────────────────────────────────────────
  const missingDocs = data.missing_documents || [];
  if (missingDocs.length > 0) {
    newPageIfNeeded(30);
    if (y > 200) { doc.addPage(); drawPageFooter(); y = 20; }
    sectionHeader("Missing Documents", "3");

    const mdRows = missingDocs.map((d, i) => [
      i + 1,
      safe(d).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
      "Missing",
      "Required for title verification"
    ]);

    doc.autoTable({
      startY: y,
      head: [["#", "Document Type", "Status", "Reason"]],
      body: mdRows,
      margin: { left: ML, right: MR },
      styles: { fontSize: 8.5, cellPadding: 3.5, lineColor: MGRAY, lineWidth: 0.2 },
      headStyles: { fillColor: NAVY, textColor: WHITE, fontStyle: "bold" },
      alternateRowStyles: { fillColor: [255, 247, 237] },
      didParseCell: function(hookData) {
        if (hookData.section === "body" && hookData.column.index === 2) {
          hookData.cell.styles.textColor = AMBER;
          hookData.cell.styles.fontStyle = "bold";
        }
      },
      didDrawPage: function() { drawPageFooter(); }
    });
    y = doc.lastAutoTable.finalY + 10;
  }

  // ── Section 4: Final Legal Opinion ─────────────────────────────────────────
  doc.addPage();
  drawPageFooter();
  y = 20;
  sectionHeader("Final Legal Opinion", "4");

  // Stats
  doc.autoTable({
    startY: y,
    head: [["Documents Reviewed", "Total Findings", "Critical", "Medium", "Low"]],
    body: [[
      opinion.documents_reviewed || db.documents_processed || 0,
      opinion.total_findings || 0,
      opinion.critical || 0,
      opinion.medium || 0,
      opinion.low || 0,
    ]],
    margin: { left: ML, right: MR },
    styles: { fontSize: 9.5, cellPadding: 4, halign: "center" },
    headStyles: { fillColor: NAVY, textColor: WHITE, fontStyle: "bold" },
    didDrawPage: function() { drawPageFooter(); }
  });
  y = doc.lastAutoTable.finalY + 8;

  // Major risks
  if ((opinion.major_risks || []).length > 0) {
    subHeader("Major Risks Identified");
    bulletList(opinion.major_risks, RED);
    y += 4;
  }

  // Recommended actions
  if ((opinion.recommended_actions || []).length > 0) {
    subHeader("Recommended Actions");
    bulletList(opinion.recommended_actions, [17, 94, 48]);
    y += 4;
  }

  // Verdict box
  newPageIfNeeded(24);
  verdictBox(opinion.final_reason || db.recommended_action || "", !isFlagged);

  // Disclaimer
  y += 4;
  drawHRule(MGRAY);
  doc.setFont("helvetica", "italic");
  doc.setFontSize(7.5);
  doc.setTextColor(...DGRAY);
  const disclaimer =
    "DISCLAIMER: This report is generated by an AI-assisted document verification system and is intended for professional due diligence support only. " +
    "It does not constitute legal advice. All findings must be independently verified by a qualified advocate or property legal expert before proceeding with any transaction.";
  const disclaimerLines = doc.splitTextToSize(disclaimer, CW);
  newPageIfNeeded(disclaimerLines.length * 4 + 4);
  doc.text(disclaimerLines, ML, y);
  y += disclaimerLines.length * 4 + 4;

  // ── Save ──────────────────────────────────────────────────────────────────
  const dateStr = new Date().toISOString().slice(0, 10);
  doc.save(`VerificationReport_${safe(caseId)}_${dateStr}.pdf`);
};
