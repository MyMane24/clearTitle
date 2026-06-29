// ── Case History Sidebar ────────────────────────────────────────────────────────

window.HistoryPanel = {
  cases: [],
  activeCaseId: null,
  polling: null,

  async init() {
    await this.loadList();
  },

  async loadList() {
    const container = document.getElementById("sidebar-list");
    if (!container) return;
    container.innerHTML = `<div class="sidebar-loading">⟳ Loading cases...</div>`;
    try {
      const data = await API.listCases();
      this.cases = data.cases || [];
      this.renderList();
    } catch {
      container.innerHTML = `<div class="sidebar-empty">Failed to load cases</div>`;
    }
  },

  renderList() {
    const container = document.getElementById("sidebar-list");
    if (!this.cases.length) {
      container.innerHTML = `<div class="sidebar-empty">No cases yet. Upload documents to get started.</div>`;
      return;
    }
    container.innerHTML = this.cases.map(c => {
      const active = c.id === this.activeCaseId ? " active" : "";
      const pct = c.total_docs > 0 ? Math.round((c.completed_docs / c.total_docs) * 100) : 0;
      
      let verdictBadge = "";
      if (c.verdict) {
        const v = c.verdict.toUpperCase();
        if (v === "PASS") {
          verdictBadge = `<span class="badge badge-green">PASS</span>`;
        } else if (v === "FLAGGED") {
          verdictBadge = `<span class="badge badge-red">FLAGGED</span>`;
        } else {
          verdictBadge = `<span class="badge badge-amber">${escHtml(c.verdict)}</span>`;
        }
      }

      return `<div class="sidebar-item${active}" data-case-id="${escHtml(c.id)}">
        <div class="sidebar-item-header">
          <span class="case-id">${escHtml(c.id)}</span>
          <button class="sidebar-delete-btn" data-case-id="${escHtml(c.id)}" title="Delete case">🗑</button>
        </div>
        <div class="case-meta">
          <span>${pct}% done</span>
          <span>${c.completed_docs}/${c.total_docs}</span>
          <span class="badge badge-${c.status === "completed" ? "green" : c.status === "processing" ? "amber" : "blue"}">${escHtml(c.status)}</span>
          ${verdictBadge}
        </div>
        <div class="case-date">${escHtml(c.created_at || "")}</div>
      </div>`;
    }).join("");

    container.querySelectorAll(".sidebar-item").forEach(el => {
      el.addEventListener("click", (e) => {
        if (e.target.closest(".sidebar-delete-btn")) return;
        this.selectCase(el.dataset.caseId);
      });
    });

    container.querySelectorAll(".sidebar-delete-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const caseId = btn.dataset.caseId;
        if (!confirm(`Delete case ${caseId} and all associated data? This cannot be undone.`)) return;
        try {
          btn.disabled = true;
          btn.textContent = "...";
          await API.deleteCase(caseId);
          if (this.activeCaseId === caseId) {
            this.activeCaseId = null;
            document.getElementById("history-detail")?.classList.add("hidden");
          }
          await this.loadList();
        } catch (err) {
          alert("Failed to delete case: " + err.message);
          btn.disabled = false;
          btn.textContent = "\u00d7";
        }
      });
    });
  },

  async selectCase(caseId) {
    if (this.polling) {
      clearInterval(this.polling);
      this.polling = null;
    }
    this.activeCaseId = caseId;
    this.renderList();

    const panel = document.getElementById("history-detail");
    ["upload", "processing", "results", "verify"].forEach(stage => {
      const el = document.getElementById(`stage-${stage}`);
      if (el) el.classList.add("hidden");
    });
    panel.classList.remove("hidden");
    panel.innerHTML = `<div class="sidebar-loading">Loading details...</div>`;

    const [bundle, ocrList, files, verifyReport] = await Promise.all([
      API.bundle(caseId),
      API.ocrRawList(caseId),
      API.caseFiles(caseId),
      API.getVerifyReport(caseId).catch(() => null),
    ]);

    const bundleDocs = bundle && bundle.documents
      ? [...bundle.documents].sort((a, b) => a.doc_id.localeCompare(b.doc_id))
      : [];
    const ocrDocs = ocrList && ocrList.documents
      ? [...ocrList.documents].sort((a, b) => a.doc_id.localeCompare(b.doc_id))
      : [];

    const bundleTabs = bundleDocs.map(d => {
      const type = d.document_type || d.structured_json?.document_type || "Unknown document";
      return `<button class="history-tab" data-bundle-doc-id="${escHtml(d.doc_id)}">${escHtml(type)}</button>`;
    }).join("");

    const ocrTabs = ocrDocs.map(d =>
      `<button class="history-tab" data-ocr-doc-id="${escHtml(d.doc_id)}">${escHtml(d.doc_id)} <small>OCR</small></button>`
    ).join("");

    let fileTreeHtml = "";
    if (files && files.entries) {
      fileTreeHtml = this.buildFileTree(files.entries);
    }

    panel.innerHTML = `
      <div class="card" style="margin:0">
        <div class="card-title"><span>Historical case: ${escHtml(caseId)}</span><button class="btn btn-secondary" id="history-close" style="margin-left:auto;padding:6px 12px">Back to upload</button></div>
        <div>
          <div class="history-tabs" id="history-tabs">
            <button class="history-tab active" data-panel="bundle">Bundle</button>
            <button class="history-tab" data-panel="ocr">OCR Raw</button>
            <button class="history-tab" data-panel="files">Files</button>
            <button class="history-tab" data-panel="verification">Verification</button>
            <button class="history-tab" data-panel="logs">Logs</button>
          </div>
          <div id="history-panel-bundle">
            ${bundleTabs ? `<div style="margin-bottom:12px"><strong>Documents:</strong><br><div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px">${bundleTabs}</div></div>` : "<p>No structured bundle results found</p>"}
            <div id="history-doc-detail"></div>
          </div>
          <div id="history-panel-ocr" style="display:none">
            ${ocrTabs ? `<div style="margin-bottom:12px"><strong>OCR raw files:</strong><br><div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px">${ocrTabs}</div></div>` : "<p>No OCR raw files found</p>"}
            <div class="ocr-viewer" id="ocr-viewer">Select a DOC tab above to view OCR text</div>
          </div>
          <div id="history-panel-files" style="display:none">
            ${fileTreeHtml || "<p>No files found</p>"}
          </div>
          <div id="history-panel-verification" style="display:none">
          </div>
          <div id="history-panel-logs" style="display:none">
            <div class="ocr-viewer" id="history-log-box" style="font-family:monospace;white-space:pre-wrap;background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:8px;max-height:400px;overflow-y:auto">Loading logs...</div>
          </div>
        </div>
      </div>
    `;

    const activeCase = this.cases.find(c => c.id === caseId);
    const caseStatus = activeCase ? activeCase.status : "unknown";
    this.renderVerificationReport(caseId, verifyReport, caseStatus);

    if (caseStatus === "processing") {
      this.startPolling(caseId);
    }

    document.getElementById("history-close").addEventListener("click", () => {
      if (this.polling) {
        clearInterval(this.polling);
        this.polling = null;
      }
      this.activeCaseId = null;
      this.renderList();
      showStage("upload");
      setStep(1);
    });

    document.querySelectorAll("#history-tabs .history-tab").forEach(btn => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll("#history-tabs .history-tab").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        ["bundle", "ocr", "files", "verification", "logs"].forEach(p => {
          const el = document.getElementById(`history-panel-${p}`);
          if (el) el.style.display = p === btn.dataset.panel ? "block" : "none";
        });
        
        if (btn.dataset.panel === "logs") {
          const logBox = document.getElementById("history-log-box");
          if (logBox) {
            logBox.textContent = "Loading logs...";
            const s = await API.status(caseId);
            logBox.innerHTML = (s.log || []).join("<br>");
            logBox.scrollTop = logBox.scrollHeight;
          }
        }
      });
    });

    document.querySelectorAll(".history-tab[data-bundle-doc-id]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".history-tab[data-bundle-doc-id]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const docId = btn.dataset.bundleDocId;
        const detail = document.getElementById("history-doc-detail");
        const storedDoc = bundleDocs.find(d => d.doc_id === docId);
        const doc = storedDoc ? {
          ...storedDoc,
          doc_type: storedDoc.document_type,
          structured: storedDoc.structured_json,
          total_pages: storedDoc.structured_json?.file_metadata?.scanned_sheet_count || "?",
          chunks_used: storedDoc.structured_json?.processing_metadata?.chunks_used || "?",
        } : null;
        if (detail) {
          detail.innerHTML = doc
            ? (window.buildDocPanel ? window.buildDocPanel(doc) : `<pre>${JSON.stringify(doc, null, 2)}</pre>`)
            : `<div class="info-box">No structured DB result for ${escHtml(docId)}.</div>`;
        }
      });
    });

    document.querySelectorAll(".history-tab[data-ocr-doc-id]").forEach(btn => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll(".history-tab[data-ocr-doc-id]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const docId = btn.dataset.ocrDocId;
        const ocrViewer = document.getElementById("ocr-viewer");
        if (ocrViewer) {
          ocrViewer.textContent = "Loading OCR text...";
          const raw = await API.ocrRaw(caseId, docId);
          ocrViewer.textContent = raw ? (raw.full_text || raw.text || JSON.stringify(raw, null, 2)) : "No OCR text available";
        }
      });
    });



    const firstBundleBtn = document.querySelector(".history-tab[data-bundle-doc-id]");
    if (firstBundleBtn) firstBundleBtn.click();

    const firstOcrBtn = document.querySelector(".history-tab[data-ocr-doc-id]");
    if (firstOcrBtn) firstOcrBtn.click();
  },

  startPolling(caseId) {
    if (this.polling) clearInterval(this.polling);
    this.polling = setInterval(async () => {
      if (this.activeCaseId !== caseId) {
        clearInterval(this.polling);
        this.polling = null;
        return;
      }
      try {
        const s = await API.status(caseId);
        
        // Update log if visible
        const logBox = document.getElementById("history-log-box");
        if (logBox && s.log) {
          logBox.innerHTML = s.log.map(l => {
            const cls = l.includes("✗") || l.toLowerCase().includes("failed") ? "log-err"
                      : l.includes("✓") || l.toLowerCase().includes("complete") ? "log-ok"
                      : l.includes("Step") || l.includes("──") ? "log-info"
                      : l.includes("⚠") ? "log-warn"
                      : "";
            return `<span class="${cls}">${escHtml(l)}</span>`;
          }).join("<br>");
          logBox.scrollTop = logBox.scrollHeight;
        }
        
        // Update sidebar and panel stats
        const activeCase = this.cases.find(c => c.id === caseId);
        if (activeCase) {
          activeCase.completed_docs = s.completed_docs || 0;
          activeCase.total_docs = s.total_docs || 0;
          activeCase.status = s.status || "processing";
          this.renderList();
        }
        
        // If finished processing, reload the details panel so everything is active!
        if (s.status === "completed" || s.status === "complete" || s.status === "partial" || s.status === "failed") {
          clearInterval(this.polling);
          this.polling = null;
          this.selectCase(caseId); // Reload case panel to fetch updated bundle and findings
        }
      } catch (err) {
        console.warn("Polling error in history", err);
      }
    }, 2000);
  },

  buildFileTree(entries, depth) {
    if (depth === undefined) depth = 0;
    if (!entries || !entries.length) return "<p>No files</p>";
    const indent = depth * 20;
    return `<div class="file-tree">${entries.map(e => {
      if (e.type === "dir") {
        return `<div class="file-tree-item" style="padding-left:${indent+8}px">
          <span class="dir">📁 ${escHtml(e.name)}</span>
        </div>
        <div class="file-tree-nested">${this.buildFileTree(e.children, depth+1)}</div>`;
      }
      return `<div class="file-tree-item" style="padding-left:${indent+8}px">
        <span class="file">📄 ${escHtml(e.name)}</span>
        ${e.size_kb !== undefined ? `<span class="size">${e.size_kb} KB</span>` : ""}
      </div>`;
    }).join("")}</div>`;
  },

  renderVerificationReport(caseId, verifyReport, caseStatus) {
    const container = document.getElementById("history-panel-verification");
    if (!container) return;

    if (verifyReport !== null) {
      const findings = verifyReport.findings || [];
      const totalFindings = findings.length;
      const highSeverity = findings.filter(f => f.severity === "high").length;
      const verdict = verifyReport.verdict || "UNKNOWN";
      
      let verdictBadge = "";
      if (verdict === "PASS") {
        verdictBadge = '<span class="badge badge-green" style="font-size:14px;padding:4px 10px">PASS ✓</span>';
      } else if (verdict === "FLAGGED") {
        verdictBadge = '<span class="badge badge-red" style="font-size:14px;padding:4px 10px">FLAGGED ⚠</span>';
      } else {
        verdictBadge = `<span class="badge badge-amber" style="font-size:14px;padding:4px 10px">${escHtml(verdict)}</span>`;
      }

      // Helper function to build findings tables
      const buildFindingsTable = (list, isPerDocTable) => {
        if (!list || list.length === 0) return "";
        const severityColors = { high: "badge-red", medium: "badge-amber", low: "badge-blue" };
        
        let tableHtml = `
          <div style="overflow-x:auto;margin-top:8px;margin-bottom:16px">
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead><tr>
                <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left;width:20%">Type</th>
                <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left;width:12%">Severity</th>
                <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left;width:18%">${isPerDocTable ? "Doc ID" : "Doc(s)"}</th>
                <th style="background:var(--navy);color:var(--white);padding:8px 10px;text-align:left">Summary & Details</th>
              </tr></thead>
              <tbody>
        `;
        
        list.forEach(f => {
          const sevCls = severityColors[f.severity] || "badge-blue";
          const docList = isPerDocTable 
            ? (f.source_doc_id || "") 
            : (f.doc_ids && f.doc_ids.length ? f.doc_ids : f.source_doc_id ? [f.source_doc_id] : []).join(", ");
            
          tableHtml += `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:8px 10px;font-weight:600;white-space:nowrap">${escHtml(f.type)}</td>
              <td style="padding:8px 10px"><span class="badge ${sevCls}">${escHtml(f.severity)}</span></td>
              <td style="padding:8px 10px;font-family:monospace;font-size:11px">${escHtml(docList)}</td>
              <td style="padding:8px 10px">
                <strong>${escHtml(f.summary)}</strong>
                <div style="font-size:11px;color:var(--gray);margin-top:2px">${escHtml(f.details || f.legal_detail || "")}</div>
                ${f.suggestion ? `<div style="font-size:11px;color:var(--blue);margin-top:2px">💡 ${escHtml(f.suggestion)}</div>` : ""}
              </td>
            </tr>
          `;
        });
        
        tableHtml += `</tbody></table></div>`;
        return tableHtml;
      };

      // Grouping
      const crossDocList = findings.filter(f => f.category !== "PER_DOC");
      const perDocList = findings.filter(f => f.category === "PER_DOC");

      // Group per-doc findings by document type
      const perDocGrouped = {};
      perDocList.forEach(f => {
        const docType = f.source_doc_type || "Other Documents";
        if (!perDocGrouped[docType]) {
          perDocGrouped[docType] = [];
        }
        perDocGrouped[docType].push(f);
      });

      // Build Cross-Doc findings HTML
      let crossDocHtml = "";
      if (crossDocList.length === 0) {
        crossDocHtml = `<div style="padding:15px;color:var(--green);font-weight:600;background:var(--lgreen);border-radius:8px;border:1px solid #bbf7d0;margin-top:8px">✅ No cross-document issues found — all documents are consistent</div>`;
      } else {
        crossDocHtml = buildFindingsTable(crossDocList, false);
      }

      // Build Per-Doc findings HTML
      let perDocHtml = "";
      if (perDocList.length === 0) {
        perDocHtml = `<div style="padding:15px;color:var(--green);font-weight:600;background:var(--lgreen);border-radius:8px;border:1px solid #bbf7d0;margin-top:8px">✅ No per-document issues found</div>`;
      } else {
        perDocHtml = Object.keys(perDocGrouped).map(docType => {
          const groupFindings = perDocGrouped[docType];
          return `
            <div style="margin-top:14px;margin-bottom:8px">
              <div style="font-weight:700;color:var(--navy);font-size:13px;border-left:3px solid var(--blue);padding-left:8px;margin-bottom:6px">
                ${escHtml(docType)} (${groupFindings.length} issue${groupFindings.length > 1 ? "s" : ""})
              </div>
              ${buildFindingsTable(groupFindings, true)}
            </div>
          `;
        }).join("");
      }

      container.innerHTML = `
        <div style="margin-top:12px">
          <strong>Metrics Overview:</strong>
          <div class="metrics-row" style="margin-top:6px">
            <div class="metric-box"><div class="val">${totalFindings}</div><div class="lbl">Total Findings</div></div>
            <div class="metric-box"><div class="val">${highSeverity}</div><div class="lbl">High Severity</div></div>
            <div class="metric-box"><div class="val">${verdictBadge}</div><div class="lbl">Verdict</div></div>
          </div>
          
          <div style="margin-top:18px">
            <h3 style="font-size:14px;color:var(--navy);border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:10px">⚖ Cross-Document Verification Results</h3>
            ${crossDocHtml}
          </div>

          <div style="margin-top:18px">
            <h3 style="font-size:14px;color:var(--navy);border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:10px">🔍 Per-Document Verification Results</h3>
            ${perDocHtml}
          </div>

          ${verifyReport.final_report ? `
            <div style="margin-top:18px">
              <h3 style="font-size:14px;color:var(--navy);border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:10px">📝 Legal Narrative Opinion / Report</h3>
              <div style="white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.6;background:var(--lgray);padding:16px;border-radius:8px;border:1px solid var(--border);margin-top:6px">
                ${escHtml(verifyReport.final_report)}
              </div>
            </div>
          ` : ""}
        </div>
      `;
    } else {
      const isComplete = ["complete", "completed", "partial"].includes(caseStatus);
      if (isComplete) {
        container.innerHTML = `
          <div class="info-box" style="padding:20px;text-align:center;background:var(--lblue);border:1px solid #bfdbfe;border-radius:8px;color:var(--navy);margin-top:12px">
            <p style="margin-bottom:12px;font-weight:600">Verification has not been run for this case yet.</p>
            <button class="btn btn-primary" id="run-verification-btn">🧪 Run Verification</button>
          </div>
        `;
        
        const btn = document.getElementById("run-verification-btn");
        if (btn) {
          btn.addEventListener("click", async () => {
            container.innerHTML = `
              <div style="padding:30px;text-align:center;color:var(--gray)">
                <div class="sidebar-loading">⏳ Running agentic verification...</div>
                <p style="font-size:12px;margin-top:6px">This may take up to a minute depending on findings count.</p>
              </div>
            `;
            try {
              await API.verify(caseId);
              const newReport = await API.getVerifyReport(caseId);
              await HistoryPanel.loadList();
              HistoryPanel.renderVerificationReport(caseId, newReport, caseStatus);
            } catch (err) {
              container.innerHTML = `
                <div class="error-item" style="margin-top:12px">
                  <strong>Error running verification:</strong> ${escHtml(err.message)}
                </div>
                <div class="info-box" style="padding:20px;text-align:center;background:var(--lblue);border:1px solid #bfdbfe;border-radius:8px;color:var(--navy);margin-top:12px">
                  <button class="btn btn-primary" id="run-verification-btn">🧪 Run Verification</button>
                </div>
              `;
              HistoryPanel.renderVerificationReport(caseId, null, caseStatus);
            }
          });
        }
      } else {
        container.innerHTML = `
          <div class="info-box" style="padding:20px;text-align:center;background:var(--lamber);border:1px solid #fde68a;border-radius:8px;color:var(--amber);margin-top:12px">
            <p style="font-weight:600">Please wait for document processing to finish before running verification.</p>
          </div>
        `;
      }
    }

    // --- Add PDF Documents Uploader inside Verification tab ---
    const uploaderHtml = `
      <div class="card" style="margin-top:20px;border:1px dashed var(--blue);background:var(--lblue)">
        <div style="font-weight:700;color:var(--navy);font-size:14px;margin-bottom:8px">➕ Add PDF Documents to this Case</div>
        <div style="font-size:11px;color:var(--gray);margin-bottom:12px">Upload additional property documents to complete your title due diligence bundle. Only new documents will be processed, saving time and credit cost.</div>
        
        <input type="file" id="add-docs-input" multiple accept=".pdf" style="display:none" />
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn btn-primary" id="add-docs-select-btn" style="padding:6px 12px;font-size:12px">📁 Select PDF Files</button>
          <button class="btn btn-green" id="add-docs-upload-btn" style="padding:6px 12px;font-size:12px" disabled>⚡ Upload & Process</button>
        </div>
        <div id="add-docs-preview" style="margin-top:10px;font-size:11px;color:var(--navy)">No files staged</div>
      </div>
    `;
    container.insertAdjacentHTML('beforeend', uploaderHtml);

    // Bind event listeners for the uploader
    let stagedFiles = [];
    const selectBtn = document.getElementById("add-docs-select-btn");
    const uploadBtn = document.getElementById("add-docs-upload-btn");
    const fileInput = document.getElementById("add-docs-input");
    const previewDiv = document.getElementById("add-docs-preview");

    if (selectBtn && fileInput) {
      selectBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", (e) => {
        const stagedList = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith(".pdf"));
        stagedList.forEach(f => {
          if (!stagedFiles.find(sf => sf.name === f.name && sf.size === f.size)) {
            stagedFiles.push(f);
          }
        });
        renderStagedFiles();
      });
    }

    function renderStagedFiles() {
      if (stagedFiles.length === 0) {
        previewDiv.innerHTML = "No files staged";
        uploadBtn.disabled = true;
      } else {
        previewDiv.innerHTML = `<strong>Staged files:</strong><ul style="margin:4px 0 0 16px;padding:0">` +
          stagedFiles.map((sf, i) => `<li>${escHtml(sf.name)} (${(sf.size / 1024).toFixed(1)} KB) <span style="color:var(--red);cursor:pointer;margin-left:6px" onclick="window.removeStagedFile(${i})">✕</span></li>`).join("") +
          `</ul>`;
        uploadBtn.disabled = false;
      }
    }

    window.removeStagedFile = (i) => {
      stagedFiles.splice(i, 1);
      renderStagedFiles();
    };

    if (uploadBtn) {
      uploadBtn.addEventListener("click", async () => {
        if (stagedFiles.length === 0) return;
        uploadBtn.disabled = true;
        uploadBtn.textContent = "Uploading...";
        
        try {
          // 1. Upload files
          await API.uploadMore(caseId, stagedFiles);
          
          // 2. Start processing
          await API.process(caseId);
          
          stagedFiles = [];
          renderStagedFiles();
          
          // Switch to logs panel automatically so user can watch in real time
          const logsTab = document.querySelector("#history-tabs button[data-panel='logs']");
          if (logsTab) logsTab.click();
          
          // Update status in sidebar and start polling
          const activeCaseInList = HistoryPanel.cases.find(c => c.id === caseId);
          if (activeCaseInList) {
            activeCaseInList.status = "processing";
            HistoryPanel.renderList();
          }
          HistoryPanel.startPolling(caseId);
          
        } catch (err) {
          alert("Error: " + err.message);
          uploadBtn.disabled = false;
          uploadBtn.textContent = "⚡ Upload & Process";
        }
      });
    }
  }
};
