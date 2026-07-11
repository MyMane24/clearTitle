// ── Main Application ────────────────────────────────────────────────────────────

let selectedFiles = [];
let currentCaseId = sessionStorage.getItem("currentCaseId") || null;
let polling = null;
let verificationFindings = [];
let activeSubTab = "overview";
let activePerDocType = null;
let globalSearchQuery = "";
let filterSeverity = "";
let filterDocType = "";
let lastVerificationData = null;

// ── Health check ───────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const d = await API.health();
    const ok = d.sarvam_key && d.groq_key;
    document.getElementById("health-dot").className = "dot" + (ok ? "" : " red");
    document.getElementById("health-text").textContent = ok
      ? "API keys loaded"
      : `⚠ Missing: ${[!d.sarvam_key && "Sarvam", !d.groq_key && "Groq"].filter(Boolean).join(", ")}`;
  } catch {
    document.getElementById("health-dot").className = "dot red";
    document.getElementById("health-text").textContent = "Server offline";
  }
}

// ── File management ───────────────────────────────────────────────────────────
function handleFiles(files) {
  files.filter(f => f.name.toLowerCase().endsWith(".pdf")).forEach(f => {
    if (!selectedFiles.find(sf => sf.name === f.name && sf.size === f.size))
      selectedFiles.push(f);
  });
  renderFileList();
}


function renderFileList() {
  const list = document.getElementById("file-list");
  list.innerHTML = selectedFiles.map((f, i) =>
    `<div class="file-item">
      <span class="file-icon">📄</span>
      <span class="file-name">${escHtml(f.name)}</span>
      <span class="file-size">${(f.size / 1024).toFixed(1)} KB</span>
      <span class="file-remove" onclick="removeFile(${i})" title="Remove">✕</span>
    </div>`
  ).join("");
  document.getElementById("process-btn").disabled = selectedFiles.length === 0;
}

function removeFile(i) {
  selectedFiles.splice(i, 1);
  renderFileList();
}


function clearFiles() {
  selectedFiles = [];
  renderFileList();
  sessionStorage.removeItem("currentCaseId");
  currentCaseId = null;
}


async function clearAllData() {
  if (!confirm("This will clear ALL Redis data and purge pending Celery tasks. The page will reload. Continue?")) return;
  try { await API.clearAll(); } catch { /* ignore */ }
  location.reload();
}


// ── Start processing (upload + pipeline) ──────────────────────────────────────
async function startProcessing() {
  if (selectedFiles.length === 0) return;

  setStep(2);
  showStage("processing");
  updateProgress(5, "Uploading documents...");

  let uploadResp;
  try {
    uploadResp = await API.upload(selectedFiles);
  } catch (e) {
    addLog(`✗ Upload failed: ${e.message}`, "err");
    return;
  }

  currentCaseId = uploadResp.case_id;
  sessionStorage.setItem("currentCaseId", currentCaseId);
  addLog(`✓ ${(uploadResp.files || []).length} file(s) uploaded → Case ${currentCaseId}`, "ok");
  if (window.HistoryPanel) HistoryPanel.loadList();
  updateProgress(10, "Starting OCR pipeline...");

  try {
    const result = await API.process(currentCaseId);
    addLog("✓ Pipeline started — running in background", "ok");
    if (result.total_docs) addLog(`Total docs: ${result.total_docs}`, "info");
  } catch (e) {
    addLog(`✗ Pipeline start failed: ${e.message}`, "err");
    return;
  }

  pollInterval(currentCaseId);
}


function pollInterval(caseId) {
  if (polling) clearInterval(polling);
  polling = setInterval(() => pollStatus(caseId), 2000);
}

async function pollStatus(caseId) {
  if (!caseId) return;
  try {
    const s = await API.status(caseId);
    updateProgress(s.progress_pct || s.progress || 0, `${s.status || "running"} – ${s.completed_docs || 0}/${s.total_docs || 0} docs`);

    const logBox = document.getElementById("log-box");
    const lines = (s.log || []).slice(-60);
    if (lines.length) {
      logBox.innerHTML = lines.map(l => {
        const cls = l.includes("✗") || l.toLowerCase().includes("failed") ? "log-err"
                  : l.includes("✓") || l.toLowerCase().includes("complete") ? "log-ok"
                  : l.includes("Step") || l.includes("──") ? "log-info"
                  : l.includes("⚠") ? "log-warn"
                  : "";
        return `<span class="${cls}">${escHtml(l)}</span>`;
      }).join("<br>");
      logBox.scrollTop = logBox.scrollHeight;
    }

    if (s.status === "completed" || s.status === "complete" || s.status === "partial" || s.status === "failed") {
      clearInterval(polling);
      polling = null;
      updateProgress(100, "Pipeline complete");
      addLog(`── Pipeline finished: ${(s.results || []).length} complete, ${(s.errors || []).length} failed ──`, "ok");
      setTimeout(() => showResults(s), 800);
    }
  } catch (e) {
    addLog(`⚠ Polling error: ${e.message}`, "warn");
  }
}

// ── Results display ────────────────────────────────────────────────────────────
async function showResults(data) {
  setStep(3);
  showStage("results");

  const results = data.results || [];
  const errors = data.errors || [];

  const totalTokens = results.reduce((s, r) => s + (r.input_tokens || 0) + (r.output_tokens || 0), 0);
  const totalCost = results.reduce((s, r) => s + (r.cost_usd || 0), 0);

  // Fetch per-doc verification notes from V2 DB
  let perDocNotes = {};
  if (currentCaseId && results.length > 0) {
    try {
      const pn = await API.verifyPerDoc(currentCaseId);
      if (pn.documents) {
        pn.documents.forEach(d => { perDocNotes[d.doc_id] = d.verification_notes || []; });
      }
    } catch (e) { /* non-fatal */ }
  }

  document.getElementById("metrics-row").innerHTML = `
    <div class="metric-box"><div class="val">${results.length}</div><div class="lbl">Documents complete</div></div>
    <div class="metric-box"><div class="val">${errors.length}</div><div class="lbl">Failed</div></div>
    <div class="metric-box"><div class="val">${results.reduce((s, r) => s + (r.total_pages || 0), 0)}</div><div class="lbl">Total pages</div></div>
    <div class="metric-box"><div class="val">${results.reduce((s, r) => s + (r.chunks_used || 1), 0)}</div><div class="lbl">Sarvam calls</div></div>
    <div class="metric-box"><div class="val">${(totalTokens || 0).toLocaleString()}</div><div class="lbl">LLM tokens</div></div>
    <div class="metric-box"><div class="val">$${(totalCost || 0).toFixed(5)}</div><div class="lbl">LLM cost</div></div>
    <div class="metric-box"><div class="val"><span class="badge ${data.status === "complete" ? "badge-green" : "badge-amber"}">${escHtml(data.status)}</span></div><div class="lbl">Case status</div></div>
  `;

  const errSec = document.getElementById("errors-section");
  if (errors.length > 0) {
    const hasRetryable = errors.some(e => e.step !== "classify" || !e.action_required);
    errSec.innerHTML = `<div style="margin-top:14px"><strong style="color:var(--red)">⚠ Errors</strong><div style="margin-top:8px">` +
      errors.map(e =>
        `<div class="error-item"><strong>${escHtml(e.doc_id)}</strong> — Step: ${escHtml(e.step)}<br><code style="font-size:11px">${escHtml(e.error)}</code></div>`
      ).join("") +
      (hasRetryable
        ? `<div style="margin-top:12px"><button class="btn btn-primary" onclick="retryFailed('${currentCaseId}')">🔄 Retry Failed</button></div>`
        : "") +
      "</div>";
  } else {
    errSec.innerHTML = "";
  }

  const naSec = document.getElementById("needs-action-section");
  const needsAction = data.needs_action || [];
  if (needsAction.length > 0) {
    naSec.innerHTML = `<div style="margin-top:16px;padding:16px;background:#fffbeb;border:1px solid #fde68a;border-radius:10px">
      <strong style="color:#b45309">⚠ Document Requires Your Decision</strong>` +
      needsAction.map(d => `
        <div style="margin-top:12px;padding:12px;background:var(--white);border-radius:8px;border:1px solid var(--border)">
          <p style="font-size:14px;margin-bottom:10px"><strong>${escHtml(d.filename)}</strong> — document type not recognised</p>
          <p style="font-size:12px;color:var(--gray);margin-bottom:12px">What would you like to do with this document?</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button class="btn btn-secondary" onclick="skipDoc('${currentCaseId}','${d.doc_id}')">✅ Continue without this document</button>
            <button class="btn btn-primary" onclick="document.getElementById('replace-input-${d.doc_id}').click()">📤 Upload a replacement document</button>
            <input type="file" id="replace-input-${d.doc_id}" accept=".pdf" style="display:none" onchange="replaceDoc('${currentCaseId}','${d.doc_id}',this)">
          </div>
          <div id="replace-status-${d.doc_id}" style="margin-top:8px;font-size:12px"></div>
        </div>`).join("") + "</div>";
  } else {
    naSec.innerHTML = "";
  }

  const tabsEl = document.getElementById("doc-tabs");
  const panelsEl = document.getElementById("doc-panels");
  tabsEl.innerHTML = panelsEl.innerHTML = "";

  results.forEach((res, i) => {
    const tab = document.createElement("div");
    tab.className = `doc-tab ${i === 0 ? "active" : ""} complete`;
    tab.id = `tab-${res.doc_id}`;
    tab.textContent = res.doc_id;
    tab.onclick = () => switchTab(res.doc_id, results);
    tabsEl.appendChild(tab);

    const panel = document.createElement("div");
    panel.id = `panel-${res.doc_id}`;
    panel.style.display = i === 0 ? "block" : "none";
    panel.innerHTML = buildDocPanel(res, perDocNotes[res.doc_id] || []);
    panelsEl.appendChild(panel);
  });

  const verifyBtn = document.getElementById("verify-btn");
  verifyBtn.dataset.caseId = currentCaseId;
  verifyBtn.disabled = results.length === 0 || !["complete", "completed", "partial"].includes(data.status);
}

// ── Tab switching ──────────────────────────────────────────────────────────────
function switchTab(docId, results) {
  results.forEach(r => {
    document.getElementById(`panel-${r.doc_id}`).style.display = r.doc_id === docId ? "block" : "none";
    document.getElementById(`tab-${r.doc_id}`).classList.toggle("active", r.doc_id === docId);
  });
}


// ── Document actions ───────────────────────────────────────────────────────────
async function skipDoc(caseId, docId) {
  try {
    const d = await API.skipDoc(caseId, docId);
    document.getElementById("needs-action-section").innerHTML = "";
    refreshStatus(caseId);
  } catch (e) {
    const el = document.getElementById(`replace-status-${docId}`);
    if (el) el.innerHTML = `<span style="color:var(--red)">✗ Skip failed: ${escHtml(e.message)}</span>`;
  }
}


async function replaceDoc(caseId, docId, input) {
  const file = input.files[0];
  if (!file) return;
  const statusEl = document.getElementById(`replace-status-${docId}`);
  statusEl.textContent = "⏳ Uploading replacement...";
  try {
    const d = await API.replaceDoc(caseId, docId, file);
    statusEl.innerHTML = `<span style="color:var(--green)">✅ Replaced with ${escHtml(file.name)}. Now retrying...</span>`;
    const r2 = await API.retry(caseId);
    document.getElementById("needs-action-section").innerHTML = "";
    showStage("processing");
    pollInterval(caseId);
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--red)">✗ Failed: ${escHtml(e.message)}</span>`;
  }
}


async function retryFailed(caseId) {
  try {
    const d = await API.retry(caseId);
    showStage("processing");
    addLog(`Retrying failed document(s)...`, "info");
    pollInterval(caseId);
  } catch (e) {
    addLog(`✗ Retry failed: ${e.message}`, "err");
    refreshStatus(caseId);
  }
}


async function refreshStatus(caseId) {
  try {
    const s = await API.status(caseId);
    showResults(s);
  } catch { /* ignore */ }
}


// ── Verification Engine ─────────────────────────────────────────────────────────
function showStage4() {
  showStage("verify");
  setStep(4);
}


async function startVerification() {
  if (!currentCaseId) return;
  document.getElementById("verify-before").classList.add("hidden");
  document.getElementById("verify-loading").classList.remove("hidden");
  document.getElementById("verify-results").classList.add("hidden");
  document.getElementById("verify-feedback-area").classList.add("hidden");

  addVerifyLog("Running cross-document verification (single-pass LLM)...", "info");
  document.getElementById("verify-progress-bar").style.width = "10%";

  try {
    const data = await API.verify(currentCaseId);
    showVerificationResults(data);
  } catch (e) {
    addVerifyLog(`✗ ${e.message}`, "err");
    document.getElementById("verify-progress-bar").style.width = "0%";
    document.getElementById("verify-before").classList.remove("hidden");
  }
}


function showVerificationResults(data) {
  document.getElementById("verify-loading").classList.add("hidden");
  document.getElementById("verify-results").classList.remove("hidden");
  document.getElementById("verify-feedback-area").classList.remove("hidden");

  lastVerificationData = data;
  const shapedFindings = [];
  if (data.cross_doc_findings) {
    shapedFindings.push(...data.cross_doc_findings);
  }
  if (data.per_doc_findings) {
    Object.values(data.per_doc_findings).forEach(group => {
      if (group.issues) {
        shapedFindings.push(...group.issues);
      }
    });
  }
  verificationFindings = shapedFindings;

  document.getElementById("verify-progress-bar").style.width = "100%";
  document.getElementById("verify-progress-label").textContent = "Verification complete";

  // Populate document filter dropdown
  const docFilterSelect = document.getElementById("vr-filter-doc");
  docFilterSelect.innerHTML = '<option value="">All Documents</option>';
  const docTypes = new Set();
  verificationFindings.forEach(f => {
    (f.documents_involved || []).forEach(d => docTypes.add(d));
  });
  docTypes.forEach(d => {
    docFilterSelect.innerHTML += `<option value="${escHtml(d)}">${escHtml(d)}</option>`;
  });

  // Render Static / State Independent tabs
  renderOverviewPane(data);
  renderMissingDocsPane(data);
  renderFinalReportPane(data);

  // Render filtered panels
  applyFiltersAndRender();
}

function renderOverviewPane(data) {
  const db = data.dashboard || {};
  const isFlagged = db.overall_status !== "PASS";
  const riskScore = db.risk_score || 0;
  
  const statusIcon = isFlagged ? '🔴 FLAGGED' : '🟢 PASS';
  const actionClass = riskScore >= 70 ? "danger" : riskScore >= 40 ? "caution" : "safe";

  // Fetch top 5 risks
  const topRisks = (data.cross_doc_findings || []).slice(0, 5);

  document.getElementById("vr-dashboard").innerHTML = `
    <div class="vr-overview-grid">
      <div class="vr-overview-main-card">
        <h3 class="vr-opinion-title">Property Health Check</h3>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Overall Title Status</span>
          <span class="vr-stat-val" style="color:${isFlagged ? 'var(--red)' : 'var(--green)'}">${statusIcon}</span>
        </div>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Risk Score</span>
          <span class="vr-stat-val">${riskScore} / 100 (${escHtml(db.risk_label || 'Low Risk')})</span>
        </div>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Documents Processed</span>
          <span class="vr-stat-val">${db.documents_processed || 0}</span>
        </div>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Critical / High Risks</span>
          <span class="vr-stat-val" style="color:var(--red)">${db.critical_findings || 0}</span>
        </div>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Medium Risks</span>
          <span class="vr-stat-val" style="color:var(--amber)">${data.dashboard?.medium_findings || 0}</span>
        </div>
        <div class="vr-stat-box">
          <span class="vr-stat-lbl">Missing Critical Documents</span>
          <span class="vr-stat-val" style="color:var(--red)">${db.missing_documents_count || 0}</span>
        </div>
        <div class="vr-action-bar ${actionClass}" style="margin-top: 16px">${escHtml(db.recommended_action || '')}</div>
      </div>
      <div class="vr-overview-side-card">
        <h3 class="vr-opinion-title">Top Risks Detected</h3>
        <ul class="vr-risk-list" style="margin: 0">
          ${topRisks.length > 0 ? topRisks.map(r => `
            <li style="display:flex;align-items:center;gap:8px;font-size:12px;border-bottom:1px solid var(--border);padding:8px 0">
              <span class="vr-issue-dot ${r.severity}"></span>
              <div style="flex:1">
                <strong>${escHtml(r.title)}</strong>
                <div style="color:var(--gray);font-size:10px">${escHtml(r.what_was_found || '')}</div>
              </div>
            </li>
          `).join('') : '<li style="color:var(--gray);font-size:12px">No major risks detected</li>'}
        </ul>
      </div>
    </div>`;
}

function renderMissingDocsPane(data) {
  const missing = data.missing_documents || [];
  const importantMissing = ["SALE_DEED", "ENCUMBRANCE_CERTIFICATE", "KHATA", "PROPERTY_REGISTER_CARD", "PROPERTY_TAX_ASSESSMENT", "MUTATION", "OCCUPANCY_CERTIFICATE", "CONVERSION_ORDER", "RTC_PAHANI", "CDP_PLAN"];
  
  // Combine extracted missing and list tiles
  let missingDocsList = [...missing];
  importantMissing.forEach(doc => {
    const cleanName = doc.replace(/_/g, ' ') || doc;
    if (!missingDocsList.some(m => m.toUpperCase().includes(doc)) && !isDocPresent(doc)) {
      missingDocsList.push(cleanName.replace(/_/g, ' ').toUpperCase());
    }
  });

  const missingHtml = `
    <h3 class="vr-opinion-title">Due Diligence Document Completeness</h3>
    <p style="font-size:12px;color:var(--gray);margin-bottom:16px">Tiles show documents required for title clearance. Click on any tile to see why it is important.</p>
    <div class="vr-missing-tile-grid">
      ${missingDocsList.map(doc => {
        return `
          <div class="vr-missing-tile" onclick="openMissingDocExplanation('${escHtml(doc)}')">
            <div class="vr-missing-tile-title">${escHtml(doc.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()))}</div>
            <div class="vr-missing-tile-status">Missing</div>
          </div>`;
      }).join('')}
    </div>`;
  
  document.getElementById("vr-missing-docs-section").innerHTML = missingHtml;
}

function isDocPresent(docType) {
  if (!lastVerificationData) return false;
  const presentDocs = Object.keys(lastVerificationData.per_doc_findings || {});
  return presentDocs.some(p => p.toUpperCase() === docType.toUpperCase());
}

function openMissingDocExplanation(docName) {
  const descriptions = {
    "KHATA": "Khata certificate certifies property tax assessment register and is essential for title transfers, layout sanction, and municipal permissions.",
    "OCCUPANCY CERTIFICATE": "Issued by local planning authority stating construction complied with approved plans; critical to avoid illegal layout penalty or building demolition.",
    "ENCUMBRANCE CERTIFICATE": "Shows history of registered transactions, charges, and mortgages on the property. Critical to ensure no bank loan liability is active.",
    "SALE DEED": "The primary title document proving ownership transfer. The core basis of title verification.",
    "PROPERTY REGISTER CARD": "Government land registry record verifying actual CTS subdivision measurement and current ownership details.",
    "PROPERTY TAX ASSESSMENT": "Verifies tax records match seller ownership, proving no outstanding municipal tax default.",
    "MUTATION": "Record of transfer of title in government registry records; proves recognition of tax liability.",
    "RELEASE DEED": "Relinquishes co-owners' claims, proving single-owner marketable title.",
    "BUILDER AGREEMENT": "Proves contract terms and construction specifications in apartment purchases.",
    "CONVERSION ORDER": "Non-Agricultural Conversion Order issued by the Deputy Commissioner; legally permits agricultural land to be used for non-agricultural development.",
    "RTC PAHANI": "Record of Rights, Tenancy and Crops; verifies land ownership history, agricultural classifications (Kharab land), and active cultivation or tenancy claims.",
    "CDP PLAN": "Comprehensive Development Plan or layout approval plan; confirms the property zoning (residential vs. green belt/buffer zone) matches the intended transaction."
  };

  const nameUpper = docName.toUpperCase();
  const desc = descriptions[nameUpper] || "Essential supporting document required to establish marketable title and verify there are no active municipal violations or outstanding tax liabilities.";
  
  openDrawer({
    title: `Missing: ${docName.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}`,
    severity: "high",
    severity_icon: "🔴",
    what_was_found: "This document is missing from the submitted verification bundle.",
    evidence: [{source: "Due Diligence Bundle", detail: "Document was not uploaded by case creator"}],
    why_flagged: desc,
    impact: "Proceeding without this document prevents title verification, exposing the buyer to potential municipal demolition or past owner ownership claims.",
    possible_causes: ["Document was not provided by vendor", "Not yet issued by planning authority"],
    checklist: ["Request the seller to retrieve this document from respective local authority"],
    legal_references: ["Registration Act 1908"]
  });
}

function renderFinalReportPane(data) {
  const opinion = data.final_opinion || {};
  const isUnsafe = opinion.final_recommendation !== "SAFE TO PROCEED";
  
  document.getElementById("vr-final-opinion").innerHTML = `
    <div class="vr-opinion">
      <div class="vr-opinion-title">📜 Final Legal Opinion Summary</div>
      <p style="font-size:13px;color:var(--gray);margin-bottom:16px">Executive Summary: ${escHtml(opinion.executive_summary || '')}</p>
      
      <div class="vr-opinion-grid">
        <div class="vr-opinion-stat"><div class="val">${opinion.documents_reviewed || 0}</div><div class="lbl">Documents</div></div>
        <div class="vr-opinion-stat"><div class="val">${opinion.total_findings || 0}</div><div class="lbl">Total Findings</div></div>
        <div class="vr-opinion-stat"><div class="val" style="color:var(--red)">${opinion.critical || 0}</div><div class="lbl">Critical</div></div>
        <div class="vr-opinion-stat"><div class="val" style="color:var(--amber)">${opinion.medium || 0}</div><div class="lbl">Medium</div></div>
        <div class="vr-opinion-stat"><div class="val" style="color:var(--blue)">${opinion.low || 0}</div><div class="lbl">Low</div></div>
      </div>

      ${(opinion.major_risks || []).length > 0 ? `
        <div class="vr-field-label">Major Risks</div>
        <ul class="vr-risk-list">${opinion.major_risks.map(r => `<li>${escHtml(r)}</li>`).join('')}</ul>
      ` : ''}

      ${(opinion.recommended_actions || []).length > 0 ? `
        <div class="vr-field-label">Recommended Actions</div>
        <ul class="vr-checklist">${opinion.recommended_actions.map(a => `<li>${escHtml(a)}</li>`).join('')}</ul>
      ` : ''}

      <div class="vr-final-rec ${isUnsafe ? 'danger' : 'safe'}">
        ${isUnsafe ? '❌' : '✅'} ${escHtml(opinion.final_recommendation || '')}
        <div class="reason">${escHtml(opinion.final_reason || '')}</div>
      </div>
    </div>`;
}

function applyFiltersAndRender() {
  if (!lastVerificationData) return;

  const search = globalSearchQuery.toLowerCase().trim();
  const severityFilter = filterSeverity;
  const docFilter = filterDocType;

  // Filter helper
  const matchesFilter = (f) => {
    if (severityFilter && f.severity !== severityFilter) return false;
    if (docFilter && !(f.documents_involved || []).includes(docFilter)) return false;
    if (search) {
      const matchText = [
        f.title,
        f.what_was_found,
        f.why_flagged,
        f.impact,
        (f.evidence || []).map(e => e.detail).join(' '),
        (f.possible_causes || []).join(' ')
      ].join(' ').toLowerCase();
      if (!matchText.includes(search)) return false;
    }
    return true;
  };

  // 1. Cross-doc findings
  const crossFindings = (lastVerificationData.cross_doc_findings || []).filter(matchesFilter);
  let crossHtml = '<h3 class="vr-opinion-title">Cross-Document Inconsistencies</h3>';
  if (crossFindings.length > 0) {
    crossHtml += crossFindings.map(f => buildIssueRow(f)).join('');
  } else {
    crossHtml += '<p style="color:var(--gray);font-size:13px;padding:12px">No matching cross-document inconsistencies.</p>';
  }
  document.getElementById("vr-cross-doc-section").innerHTML = crossHtml;

  // 2. Per-doc findings split view
  const perDocMap = lastVerificationData.per_doc_findings || {};
  const perDocKeys = Object.keys(perDocMap);
  
  // Set default selected perDoc if not set
  if (perDocKeys.length > 0 && !activePerDocType) {
    activePerDocType = perDocKeys[0];
  }

  let perDocHtml = `
    <h3 class="vr-opinion-title">Individual Document Verifications</h3>
    <div class="vr-split-layout">
      <div class="vr-split-sidebar">
        ${perDocKeys.map(dt => {
          const group = perDocMap[dt] || {};
          const issues = (group.issues || []).filter(matchesFilter);
          const docLabel = dt.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
          const activeClass = dt === activePerDocType ? "active" : "";
          return `
            <div class="vr-split-sidebar-item ${activeClass}" onclick="switchActivePerDoc('${escHtml(dt)}')">
              <span>${escHtml(docLabel)}</span>
              <span class="vr-split-sidebar-badge">${issues.length}</span>
            </div>`;
        }).join('')}
      </div>
      <div class="vr-split-content">
        ${activePerDocType ? (() => {
          const group = perDocMap[activePerDocType] || {};
          const issues = (group.issues || []).filter(matchesFilter);
          if (issues.length > 0) {
            return issues.map(f => buildIssueRow(f)).join('');
          }
          return '<p style="color:var(--gray);font-size:13px;padding:12px">No issues flagged in this document.</p>';
        })() : '<p style="color:var(--gray);font-size:13px;padding:12px">No document selected.</p>'}
      </div>
    </div>`;
  
  document.getElementById("vr-per-doc-section").innerHTML = perDocHtml;

  // 3. Human review pane
  const reviewItems = verificationFindings
    .map((f, idx) => ({ finding: f, originalIndex: idx }))
    .filter(item => matchesFilter(item.finding));
  buildFeedbackForm(reviewItems);
}

function switchActivePerDoc(docType) {
  activePerDocType = docType;
  applyFiltersAndRender();
}

function buildIssueRow(f) {
  const sev = f.severity || 'low';
  const docPills = (f.documents_involved || []).map(d => `<span class="vr-doc-pill">${escHtml(d)}</span>`).join('');
  const key = encodeURIComponent(JSON.stringify(f)).replace(/'/g, "%27");
  
  return `
    <div class="vr-issue-row">
      <div class="vr-issue-row-left">
        <span class="vr-issue-dot ${sev}"></span>
        <div>
          <span class="vr-issue-title">${escHtml(f.title)}</span>
          <span class="vr-issue-meta">${escHtml(f.what_was_found || '')}</span>
          <div style="margin-top:4px">${docPills}</div>
        </div>
      </div>
      <div class="vr-issue-row-btn" onclick="triggerOpenDrawer('${key}')">[View]</div>
    </div>`;
}

function triggerOpenDrawer(key) {
  try {
    const finding = JSON.parse(decodeURIComponent(key));
    openDrawer(finding);
  } catch (e) {
    console.error("Failed to parse drawer finding:", e);
  }
}

function openDrawer(f) {
  document.getElementById("vr-drawer-title").textContent = f.title;
  
  let bodyHtml = `
    <div class="vr-finding-severity ${f.severity}">
      ${f.severity === "high" || f.severity === "critical" ? "🔴" : f.severity === "medium" ? "🟠" : "🔵"} ${f.severity.toUpperCase()}
    </div>
    
    <div class="vr-field-label">What was found</div>
    <p style="font-size:13px;line-height:1.5;margin-bottom:12px">${escHtml(f.what_was_found || '')}</p>
  `;

  // Evidence Display: Render Side-by-Side comparison if possible
  if (f.evidence && f.evidence.length > 0) {
    bodyHtml += `<div class="vr-field-label">Evidence Comparison</div>`;
    
    // Parse comparative values if there are multiple evidence points or pipe elements
    if (f.evidence.length >= 2) {
      bodyHtml += `<div class="vr-evidence-split">`;
      f.evidence.forEach((ev, idx) => {
        if (idx < 2) {
          bodyHtml += `
            <div class="vr-evidence-column highlight">
              <div class="vr-evidence-title">${escHtml(ev.source || 'Doc')}</div>
              <div class="vr-evidence-value">${escHtml(ev.detail || '')}</div>
            </div>`;
          if (idx === 0) {
            bodyHtml += `<div class="vr-evidence-arrow">↔</div>`;
          }
        }
      });
      bodyHtml += `</div>`;
    } else {
      // Standard evidence fallback
      f.evidence.forEach(ev => {
        bodyHtml += `
          <div class="vr-evidence-block" style="background:#f9fafb;border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:8px">
            <strong style="font-size:11px;color:var(--gray);text-transform:uppercase">${escHtml(ev.source || 'Evidence')}</strong>
            <p style="font-size:13px;margin-top:4px">${escHtml(ev.detail || '')}</p>
          </div>`;
      });
    }
  }

  bodyHtml += `
    <div class="vr-field-label">Why Flagged (Lawyer Reasoning)</div>
    <p style="font-size:13px;line-height:1.5;margin-bottom:12px">${escHtml(f.why_flagged || '')}</p>
  `;

  if (f.possible_causes && f.possible_causes.length > 0) {
    bodyHtml += `
      <div class="vr-field-label">Possible Causes</div>
      <ul class="vr-checklist" style="margin-bottom:12px">
        ${f.possible_causes.map(c => `<li>${escHtml(c)}</li>`).join('')}
      </ul>`;
  }

  if (f.impact) {
    bodyHtml += `
      <div class="vr-field-label">Business / Legal Impact</div>
      <p style="font-size:13px;line-height:1.5;margin-bottom:12px;color:var(--red);font-weight:600">${escHtml(f.impact)}</p>
    `;
  }

  if (f.checklist && f.checklist.length > 0) {
    bodyHtml += `
      <div class="vr-field-label">Actionable Checklist</div>
      <ul class="vr-checklist" style="margin-bottom:12px">
        ${f.checklist.map(c => `<li>${escHtml(c)}</li>`).join('')}
      </ul>`;
  }

  if (f.confidence) {
    const pct = Math.round(f.confidence * 100);
    bodyHtml += `
      <div class="vr-confidence">
        <span>Confidence</span>
        <div class="vr-confidence-bar"><div class="vr-confidence-fill" style="width:${pct}%"></div></div>
        <span>${pct}%</span>
      </div>`;
  }

  if (f.legal_references && f.legal_references.length > 0) {
    bodyHtml += `
      <details class="vr-legal-toggle" style="margin-top:16px">
        <summary>View Legal Reference ▼</summary>
        <div class="vr-legal-content">${f.legal_references.map(r => escHtml(r)).join('<br>')}</div>
      </details>`;
  }

  document.getElementById("vr-drawer-body").innerHTML = bodyHtml;
  
  // Open transitions
  document.getElementById("vr-drawer-overlay").classList.add("active");
  document.getElementById("vr-drawer").classList.add("active");
}

function closeDrawer() {
  document.getElementById("vr-drawer-overlay").classList.remove("active");
  document.getElementById("vr-drawer").classList.remove("active");
}

function buildFeedbackForm(reviewItems) {
  const container = document.getElementById("feedback-items");
  container.innerHTML = "";

  reviewItems.forEach((item) => {
    const f = item.finding;
    const i = item.originalIndex;

    const evidenceHtml = (f.evidence && f.evidence.length > 0)
      ? `<div style="font-size:11px;color:var(--gray);background:#f3f4f6;padding:6px;border-radius:4px;margin-top:6px">
          <strong>Evidence:</strong>
          ${f.evidence.map(e => `<div><span class="vr-doc-pill" style="font-size:9px;padding:2px 4px">${escHtml(e.source)}</span> ${escHtml(e.detail)}</div>`).join('')}
         </div>`
      : '';

    const whyFlaggedHtml = f.why_flagged 
      ? `<div style="font-size:11px;color:var(--red);margin-top:4px"><strong>Why Flagged:</strong> ${escHtml(f.why_flagged)}</div>`
      : '';

    const legalRefHtml = (f.legal_references && f.legal_references.length > 0)
      ? `<div style="font-size:11px;color:var(--blue);margin-top:4px"><strong>Legal Reference:</strong> ${f.legal_references.map(r => escHtml(r)).join(', ')}</div>`
      : '';

    const div = document.createElement("div");
    div.className = "vr-review-card";
    div.innerHTML = `
      <div class="vr-review-header">
        <div style="flex:1;padding-right:16px">
          <strong style="font-size:13px">${escHtml(f.title || '')}</strong>
          <span class="badge ${f.severity === "high" || f.severity === "critical" ? "badge-red" : f.severity === "medium" ? "badge-amber" : "badge-blue"}" style="margin-left:6px">${f.severity || 'low'}</span>
          <div style="font-size:12px;color:var(--gray);margin-top:4px">${escHtml(f.what_was_found || '')}</div>
          ${whyFlaggedHtml}
          ${legalRefHtml}
          ${evidenceHtml}
        </div>
        <div class="vr-review-actions">
          <button class="vr-review-btn accept active" id="fb-accept-btn-${i}" onclick="toggleHumanReviewChoice(${i}, true)">✔ Accept</button>
          <button class="vr-review-btn reject" id="fb-reject-btn-${i}" onclick="toggleHumanReviewChoice(${i}, false)">✖ Reject</button>
        </div>
      </div>
      <div class="vr-review-expand" id="fb-expand-${i}">
        <textarea id="fb-correction-${i}" placeholder="Enter the corrected fact or observation here..."
                  style="width:100%;border:1px solid var(--border);border-radius:6px;padding:8px;font-size:12px;resize:vertical;min-height:40px;font-family:inherit"></textarea>
        <input type="text" id="fb-reason-${i}" placeholder="Provide legal context or reason (e.g. 'This survey number has been rectified under correction deed page 2')"
               style="width:100%;border:1px solid var(--border);border-radius:6px;padding:8px;font-size:12px;margin-top:6px;font-family:inherit">
      </div>
      <input type="hidden" id="fb-docid-${i}" value="${((f.doc_ids || []).join(",")) || (f.source_doc_id || "")}">
      <input type="hidden" id="fb-type-${i}" value="${f.type || ''}">
      <input type="hidden" id="fb-accept-val-${i}" value="true">`;
    container.appendChild(div);
  });
}

function toggleHumanReviewChoice(index, accept) {
  const acceptBtn = document.getElementById(`fb-accept-btn-${index}`);
  const rejectBtn = document.getElementById(`fb-reject-btn-${index}`);
  const expandArea = document.getElementById(`fb-expand-${index}`);
  const valInput = document.getElementById(`fb-accept-val-${index}`);

  if (accept) {
    acceptBtn.classList.add("active");
    rejectBtn.classList.remove("active");
    expandArea.classList.remove("active");
    valInput.value = "true";
  } else {
    acceptBtn.classList.remove("active");
    rejectBtn.classList.add("active");
    expandArea.classList.add("active");
    valInput.value = "false";
  }
}

async function submitFeedback() {
  if (!currentCaseId || !verificationFindings) return;
  
  const feedback = [];
  
  verificationFindings.forEach((f, i) => {
    const acceptedVal = document.getElementById(`fb-accept-val-${i}`);
    if (acceptedVal) {
      const accepted = acceptedVal.value === "true";
      const correction = document.getElementById(`fb-correction-${i}`).value.trim();
      const reason = document.getElementById(`fb-reason-${i}`).value.trim();
      feedback.push({
        doc_id: document.getElementById(`fb-docid-${i}`).value,
        original_flag: f.title || f.summary,
        human_correction: correction || (accepted ? "Confirmed correct" : "Needs review"),
        reason: reason,
        accepted: accepted,
        finding_type: f.type || '',
      });
    }
  });

  const statusEl = document.getElementById("feedback-status");
  statusEl.innerHTML = '<span style="color:var(--blue)">⏳ Storing feedback and updating vector database...</span>';

  try {
    const data = await API.submitFeedback(currentCaseId, feedback);
    statusEl.innerHTML = `<span style="color:var(--green)">✅ ${data.message}</span>`;
    await showLearningsStats();
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--red)">✗ ${e.message}</span>`;
  }
}


async function showLearningsStats() {
  try {
    const d = await API.getLearningStats();
    document.getElementById("verify-learnings-card").classList.remove("hidden");
    document.getElementById("learnings-stats").innerHTML =
      `📊 ${d.total_learnings} past corrections stored in vector database (Qdrant in-memory)`;
  } catch { /* ignore */ }
}


function addVerifyLog(msg, type) {
  const box = document.getElementById("verify-log-box");
  const span = document.createElement("span");
  span.className = `log-${type}`;
  span.textContent = msg;
  box.appendChild(document.createElement("br"));
  box.appendChild(span);
  box.scrollTop = box.scrollHeight;
}

// ── Initialization ──────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  checkHealth();

  // Restore previous session
  if (currentCaseId) {
    API.status(currentCaseId).then(s => {
      if (s.status === "complete" || s.status === "completed" || s.status === "partial") {
        showResults(s);
      }
    }).catch(() => {});
  }

  addLog("System ready. Upload documents to begin.", "info");

  // Drag & drop
  const zone = document.getElementById("upload-zone");
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    handleFiles([...e.dataTransfer.files]);
  });

  document.getElementById("file-input").addEventListener("change", e => {
    handleFiles([...e.target.files]);
    e.target.value = "";
  });

  document.getElementById("process-btn").addEventListener("click", startProcessing);
  document.getElementById("clear-files-btn").addEventListener("click", clearFiles);
  document.getElementById("clear-btn").addEventListener("click", clearAllData);

  const verifyBtn = document.getElementById("verify-btn");
  if (verifyBtn) {
    verifyBtn.addEventListener("click", showStage4);
  }

  const startVerifyBtn = document.getElementById("start-verify-btn");
  if (startVerifyBtn) {
    startVerifyBtn.addEventListener("click", startVerification);
  }

  const submitFeedbackBtn = document.getElementById("submit-feedback-btn");
  if (submitFeedbackBtn) {
    submitFeedbackBtn.addEventListener("click", submitFeedback);
  }

  // Sticky sub-tabs navigation
  const tabContainer = document.getElementById("vr-nav-tabs");
  if (tabContainer) {
    tabContainer.addEventListener("click", e => {
      const tabEl = e.target.closest(".vr-nav-tab");
      if (tabEl) {
        // Toggle tab active classes
        document.querySelectorAll(".vr-nav-tab").forEach(t => t.classList.remove("active"));
        tabEl.classList.add("active");

        // Toggle pane active classes
        const targetTab = tabEl.dataset.tab;
        document.querySelectorAll(".vr-tab-pane").forEach(p => p.classList.remove("active"));
        const targetPane = document.getElementById(`pane-${targetTab}`);
        if (targetPane) targetPane.classList.add("active");
        
        activeSubTab = targetTab;
      }
    });
  }

  // Global search input
  const searchInput = document.getElementById("vr-global-search");
  if (searchInput) {
    searchInput.addEventListener("input", e => {
      globalSearchQuery = e.target.value;
      applyFiltersAndRender();
    });
  }

  // Severity filter
  const severitySelect = document.getElementById("vr-filter-severity");
  if (severitySelect) {
    severitySelect.addEventListener("change", e => {
      filterSeverity = e.target.value;
      applyFiltersAndRender();
    });
  }

  // Document filter
  const docSelect = document.getElementById("vr-filter-doc");
  if (docSelect) {
    docSelect.addEventListener("change", e => {
      filterDocType = e.target.value;
      applyFiltersAndRender();
    });
  }

  // Drawer backdrop/close controls
  const closeBtn = document.getElementById("vr-drawer-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeDrawer);
  }
  const overlay = document.getElementById("vr-drawer-overlay");
  if (overlay) {
    overlay.addEventListener("click", closeDrawer);
  }

  // Sidebar expand/collapse toggle
  const toggleBtn = document.getElementById("sidebar-toggle-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const sidebar = document.getElementById("sidebar");
      if (sidebar) {
        sidebar.classList.toggle("collapsed");
      }
    });
  }

  // Init history panel
  if (window.HistoryPanel) {
    HistoryPanel.init();
  }

  // PDF download button
  const pdfBtn = document.getElementById("btn-download-pdf");
  if (pdfBtn) {
    pdfBtn.addEventListener("click", () => {
      if (!lastVerificationData) {
        alert("No verification report loaded. Please run verification first.");
        return;
      }
      pdfBtn.textContent = "⏳ Generating…";
      pdfBtn.disabled = true;
      setTimeout(() => {
        try {
          window.downloadVerificationPDF(lastVerificationData, currentCaseId || "Unknown");
        } catch (e) {
          console.error("PDF generation failed:", e);
          alert("PDF generation failed: " + e.message);
        }
        pdfBtn.textContent = "⬇ PDF Report";
        pdfBtn.disabled = false;
      }, 50);
    });
  }
});
