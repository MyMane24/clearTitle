// ── Main Application ────────────────────────────────────────────────────────────

let selectedFiles = [];
let currentCaseId = sessionStorage.getItem("currentCaseId") || null;
let polling = null;
let verificationFindings = [];

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

  const findings = data.findings || [];
  verificationFindings = findings;

  document.getElementById("verify-progress-bar").style.width = "100%";
  document.getElementById("verify-progress-label").textContent = "Verification complete";

  const verdict = data.verdict || "UNKNOWN";
  const verdictBadge = verdict === "PASS"
    ? '<span class="badge badge-green">PASS ✓</span>'
    : '<span class="badge badge-red">FLAGGED ⚠</span>';

  const metadata = data.metadata || {};

  document.getElementById("verify-summary").innerHTML = `
    <div class="metric-box"><div class="val">${data.total_findings || 0}</div><div class="lbl">Total Findings</div></div>
    <div class="metric-box"><div class="val">${data.per_doc_findings || 0}</div><div class="lbl">Per-Doc</div></div>
    <div class="metric-box"><div class="val">${data.cross_doc_findings || 0}</div><div class="lbl">Cross-Doc</div></div>
    <div class="metric-box"><div class="val">${data.high_severity || 0}</div><div class="lbl">High Severity</div></div>
    <div class="metric-box"><div class="val">${verdictBadge}</div><div class="lbl">Verdict</div></div>
    ${metadata.model ? `<div class="metric-box" style="min-width:100px"><div class="val" style="font-size:13px">${escHtml(metadata.model)}</div><div class="lbl">Model</div></div>` : ""}
    ${metadata.total_cost_usd ? `<div class="metric-box"><div class="val">$${Number(metadata.total_cost_usd).toFixed(5)}</div><div class="lbl">Cost</div></div>` : ""}
  `;

  if (findings.length === 0) {
    document.getElementById("verify-findings").innerHTML = `
      <div style="padding:20px;text-align:center;color:var(--green);font-weight:600">✅ No issues found — all documents are consistent</div>`;
    document.getElementById("verify-feedback-area").classList.add("hidden");
    return;
  }

  const severityColors = { high: "badge-red", medium: "badge-amber", low: "badge-blue" };
  let tableHtml = `<div style="overflow-x:auto;margin-top:12px">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr>
        <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left">Type</th>
        <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left">Severity</th>
        <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left">Doc(s)</th>
        <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left">Summary</th>
      </tr></thead><tbody>`;

  findings.forEach(f => {
    const sevCls = severityColors[f.severity] || "badge-blue";
    tableHtml += `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:8px 10px;font-weight:600;white-space:nowrap">${escHtml(f.type)}</td>
      <td style="padding:8px 10px"><span class="badge ${sevCls}">${f.severity}</span></td>
      <td style="padding:8px 10px;font-family:monospace;font-size:11px">${escHtml((f.doc_ids && f.doc_ids.length ? f.doc_ids : f.source_doc_id ? [f.source_doc_id] : []).join(", "))}</td>
      <td style="padding:8px 10px">
        <strong>${escHtml(f.summary)}</strong>
        <div style="font-size:11px;color:var(--gray);margin-top:2px">${escHtml(f.details || f.legal_detail || "")}</div>
        ${f.suggestion ? `<div style="font-size:11px;color:var(--blue);margin-top:2px">💡 ${escHtml(f.suggestion)}</div>` : ""}
      </td>
    </tr>`;
  });

  tableHtml += "</tbody></table></div>";
  document.getElementById("verify-findings").innerHTML = tableHtml;
  buildFeedbackForm(findings);
}

function buildFeedbackForm(findings) {
  const area = document.getElementById("verify-feedback-area");
  area.classList.remove("hidden");
  const container = document.getElementById("feedback-items");
  container.innerHTML = "";

  findings.forEach((f, i) => {
    const div = document.createElement("div");
    div.style.cssText = "background:var(--white);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:10px";
    div.innerHTML = `
      <div style="display:flex;align-items:start;gap:10px;margin-bottom:8px">
        <input type="checkbox" id="fb-accept-${i}" checked style="margin-top:3px;width:16px;height:16px">
        <div style="flex:1">
          <strong style="font-size:13px">${escHtml(f.type)}</strong>
          <span class="badge ${f.severity === "high" ? "badge-red" : f.severity === "medium" ? "badge-amber" : "badge-blue"}" style="margin-left:6px">${f.severity}</span>
          <div style="font-size:12px;margin-top:4px">${escHtml(f.summary)}</div>
          <div style="font-size:11px;color:var(--gray);margin-top:2px">${escHtml(f.details)}</div>
        </div>
      </div>
      <div style="margin-left:26px">
        <textarea id="fb-correction-${i}" placeholder="If you disagree, explain the correction here..."
                  style="width:100%;border:1px solid var(--border);border-radius:6px;padding:8px;font-size:12px;resize:vertical;min-height:40px;font-family:inherit">${escHtml(f.suggestion || "")}</textarea>
        <input type="text" id="fb-reason-${i}" placeholder="Why? (e.g., 'Thumbprints are valid signatures for rural deeds in this region')"
               style="width:100%;border:1px solid var(--border);border-radius:6px;padding:8px;font-size:12px;margin-top:6px;font-family:inherit">
        <input type="hidden" id="fb-docid-${i}" value="${(f.doc_ids || []).join(",")}">
        <input type="hidden" id="fb-type-${i}" value="${f.type}">
      </div>`;
    container.appendChild(div);
  });
}

async function submitFeedback() {
  if (!currentCaseId) return;
  const feedback = [];
  verificationFindings.forEach((f, i) => {
    feedback.push({
      doc_id: document.getElementById(`fb-docid-${i}`).value,
      original_flag: f.summary,
      human_correction: (document.getElementById(`fb-correction-${i}`).value.trim()) || (document.getElementById(`fb-accept-${i}`).checked ? "Confirmed correct" : "Needs review"),
      reason: document.getElementById(`fb-reason-${i}`).value.trim(),
      accepted: document.getElementById(`fb-accept-${i}`).checked,
      finding_type: document.getElementById(`fb-type-${i}`).value,
    });
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

  // Init history panel
  if (window.HistoryPanel) {
    HistoryPanel.init();
  }
});
