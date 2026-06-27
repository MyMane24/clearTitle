// ── UI helpers ──────────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function syntaxHighlight(json) {
  return escHtml(json)
    .replace(/("(?:[^"\\]|\\.)*")(\s*:)/g, '<span class="jk">$1</span>$2')
    .replace(/:\s*("(?:[^"\\]|\\.)*")/g,   ': <span class="js">$1</span>')
    .replace(/:\s*(-?\d+\.?\d*)/g,          ': <span class="jn">$1</span>')
    .replace(/:\s*(true|false|null)/g,       ': <span class="jb">$1</span>');
}

function showStage(s) {
  ["upload","processing","results","verify"].forEach(id => {
    $(`stage-${id}`).classList.toggle("hidden", id !== s);
  });
  const history = $("history-detail");
  if (history) history.classList.add("hidden");
}

function setStep(n) {
  [1,2,3,4].forEach(i => {
    const el = $(`step-${i}`);
    el.className = "step" + (i < n ? " done" : i === n ? " active" : "");
  });
}

function updateProgress(pct, label) {
  $("progress-bar").style.width = `${pct}%`;
  $("progress-label").textContent = label;
}

function addLog(msg, type="info") {
  const box = $("log-box");
  const span = document.createElement("span");
  span.className = `log-${type}`;
  span.textContent = msg;
  box.appendChild(document.createElement("br"));
  box.appendChild(span);
  box.scrollTop = box.scrollHeight;
}

function flattenObj(obj, prefix, depth) {
  if (depth > 4) return [];
  const rows = [];
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      rows.push(...flattenObj(v, key, depth+1));
    } else if (Array.isArray(v)) {
      v.forEach((item, i) => {
        if (typeof item === "object") rows.push(...flattenObj(item, `${key}[${i}]`, depth+1));
        else rows.push({ key: `${key}[${i}]`, value: item, raw: item });
      });
    } else {
      rows.push({ key, value: v, raw: v });
    }
  }
  return rows;
}

function buildSummaryTable(structured) {
  const rows = flattenObj(structured, "", 0)
    .filter(r => r.value !== null && r.value !== "" && !Array.isArray(r.raw))
    .map(r => `<tr>
      <td style="font-family:monospace;font-size:11px;color:var(--navy);padding:6px 12px;border-bottom:1px solid var(--border);white-space:nowrap">${escHtml(r.key)}</td>
      <td style="padding:6px 12px;border-bottom:1px solid var(--border);font-size:13px">${escHtml(String(r.value))}</td>
    </tr>`).join("");
  return `<div style="overflow:auto;max-height:520px">
    <table style="width:100%;border-collapse:collapse">
      <thead><tr>
        <th style="background:var(--navy);color:var(--white);padding:8px 12px;text-align:left;font-size:12px">Field</th>
        <th style="background:var(--navy);color:var(--white);padding:8px 12px;text-align:left;font-size:12px">Value</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function buildDocPanel(res) {
  const structured = res.structured || {};
  const jsonPretty = syntaxHighlight(JSON.stringify(structured, null, 2));

  return `
    <div class="doc-panel-inner">
      <div class="doc-info-bar">
        <strong>${escHtml(res.filename || "")}</strong>
        <span class="badge badge-blue">${escHtml(res.doc_type || "")}</span>
        <span style="color:var(--gray)">Pages: <strong>${escHtml(res.total_pages ?? "?")}</strong></span>
        <span style="color:var(--gray)">Chunks: <strong>${escHtml(res.chunks_used ?? "?")}</strong></span>
        ${res.input_tokens ? `<span style="color:var(--gray)">Tokens: <strong>${res.input_tokens} in / ${res.output_tokens} out</strong></span>` : ""}
        <span class="badge badge-green">✓ complete</span>
      </div>
      <div class="view-toggle">
        <button class="vt-btn active" data-view="json" onclick="switchView(this,'json')">🗄 Structured JSON</button>
        <button class="vt-btn"       data-view="summary" onclick="switchView(this,'summary')">📋 Field Summary</button>
      </div>
      <div class="view-json">
        <div class="json-viewer">${jsonPretty}</div>
      </div>
      <div class="view-summary" style="display:none">
        ${buildSummaryTable(structured)}
      </div>
    </div>
  `;
}

function switchView(btn, view) {
  const panel = btn.closest('.doc-panel-inner') || btn.parentElement.parentElement;
  if (!panel) return;
  const jsonView = panel.querySelector('.view-json');
  const summaryView = panel.querySelector('.view-summary');
  if (jsonView) jsonView.style.display = view === "json" ? "block" : "none";
  if (summaryView) summaryView.style.display = view === "summary" ? "block" : "none";
  btn.parentElement.querySelectorAll('.vt-btn').forEach(button => {
    button.classList.toggle("active", button.getAttribute("data-view") === view);
  });
}

window.buildDocPanel = buildDocPanel;
window.switchView = switchView;
