
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
      return `<button class="doc-tab" data-bundle-doc-id="${escHtml(d.doc_id)}">${escHtml(type)}</button>`;
    }).join("");

    const ocrTabs = ocrDocs.map(d =>
      `<button class="doc-tab" data-ocr-doc-id="${escHtml(d.doc_id)}">${escHtml(d.doc_id)} <small>OCR</small></button>`
    ).join("");

    let fileTreeHtml = "";
    if (files && files.entries) {
      fileTreeHtml = this.buildFileTree(files.entries);
    }

    panel.innerHTML = `
      <div class="hist-case-panel">
        <div class="hist-case-header">
          <div class="hist-case-header-left">
            <span class="hist-case-label">Case ID</span>
            <span class="hist-case-id">${escHtml(caseId)}</span>
          </div>
          <button class="btn btn-secondary" id="history-close" style="padding:6px 14px;font-size:12px">← Back to Upload</button>
        </div>
        <div class="history-tabs" id="history-tabs">
          <button class="history-tab active" data-panel="bundle">Bundle</button>
          <button class="history-tab" data-panel="ocr">OCR Raw</button>
          <button class="history-tab" data-panel="files">Files</button>
          <button class="history-tab" data-panel="verification">Verification</button>
          <button class="history-tab" data-panel="logs">Logs</button>
        </div>
        <div class="hist-case-body">
          <div id="history-panel-bundle">
            ${bundleTabs
              ? `<div class="hist-section-header">Documents</div><div class="doc-tabs" style="margin-bottom:16px">${bundleTabs}</div>`
              : `<p class="hist-empty">No structured bundle results found.</p>`}
            <div id="history-doc-detail"></div>
          </div>
          <div id="history-panel-ocr" style="display:none">
            ${ocrTabs
              ? `<div class="hist-section-header">OCR Raw Files</div><div class="doc-tabs" style="margin-bottom:16px">${ocrTabs}</div>`
              : `<p class="hist-empty">No OCR raw files found.</p>`}
            <div class="ocr-viewer" id="ocr-viewer">Select a document tab above to view OCR text.</div>
          </div>
          <div id="history-panel-files" style="display:none">
            ${fileTreeHtml || `<p class="hist-empty">No files found.</p>`}
          </div>
          <div id="history-panel-verification" style="display:none"></div>
          <div id="history-panel-logs" style="display:none">
            <div id="history-log-box" style="font-family:'JetBrains Mono','Fira Code',monospace;white-space:pre-wrap;background:#0f172a;color:#94a3b8;padding:20px;border-radius:8px;max-height:500px;overflow-y:auto;font-size:12px;line-height:1.7">Loading logs...</div>
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

    document.querySelectorAll(".doc-tab[data-bundle-doc-id]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".doc-tab[data-bundle-doc-id]").forEach(b => b.classList.remove("active"));
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

    document.querySelectorAll(".doc-tab[data-ocr-doc-id]").forEach(btn => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll(".doc-tab[data-ocr-doc-id]").forEach(b => b.classList.remove("active"));
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



    const firstBundleBtn = document.querySelector(".doc-tab[data-bundle-doc-id]");
    if (firstBundleBtn) firstBundleBtn.click();

    const firstOcrBtn = document.querySelector(".doc-tab[data-ocr-doc-id]");
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
      // Set globals so the global drawer/filters work
      lastVerificationData = verifyReport;
      verificationFindings = verifyReport.findings || [];

      // Render the same tabbed interactive UI structure inside history panel!
      container.innerHTML = `
        <div style="margin-top:12px">
          <!-- Sticky Navigation Sub-Tabs -->
          <div class="vr-nav-tabs-bar">
            <div class="vr-nav-tabs" id="vr-hist-nav-tabs">
              <div class="vr-nav-tab active" data-tab="hist-overview">Overview</div>
              <div class="vr-nav-tab" data-tab="hist-cross-doc">Cross Verification</div>
              <div class="vr-nav-tab" data-tab="hist-per-doc">Per Document</div>
              <div class="vr-nav-tab" data-tab="hist-missing-docs">Missing Documents</div>
              <div class="vr-nav-tab" data-tab="hist-final-report">Final Report</div>
            </div>
            <button class="btn-pdf-download" id="btn-hist-download-pdf" title="Download PDF Report">⬇ PDF Report</button>
          </div>

          <!-- Global Search and Filters -->
          <div class="vr-filter-bar">
            <input type="text" class="vr-search-input" id="vr-hist-global-search" placeholder="Search findings...">
            <select class="vr-filter-select" id="vr-hist-filter-severity">
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          <!-- Tab 1: Overview -->
          <div class="vr-tab-pane active" id="pane-hist-overview">
            <div id="vr-hist-dashboard"></div>
          </div>

          <!-- Tab 2: Cross-Document -->
          <div class="vr-tab-pane" id="pane-hist-cross-doc">
            <div id="vr-hist-cross-doc-section"></div>
          </div>

          <!-- Tab 3: Per-Document -->
          <div class="vr-tab-pane" id="pane-hist-per-doc">
            <div id="vr-hist-per-doc-section"></div>
          </div>

          <!-- Tab 4: Missing Documents -->
          <div class="vr-tab-pane" id="pane-hist-missing-docs">
            <div id="vr-hist-missing-docs-section"></div>
          </div>

          <!-- Tab 5: Final Report -->
          <div class="vr-tab-pane" id="pane-hist-final-report">
            <div id="vr-hist-final-opinion"></div>
          </div>
        </div>
      `;

      // Helper function to render Overview
      const renderHistOverview = () => {
        const db = verifyReport.dashboard || {};
        const isFlagged = db.overall_status !== "PASS";
        const riskScore = db.risk_score || 0;
        const statusIcon = isFlagged ? '🔴 FLAGGED' : '🟢 PASS';
        const actionClass = riskScore >= 70 ? "danger" : riskScore >= 40 ? "caution" : "safe";
        const topRisks = (verifyReport.cross_doc_findings || []).slice(0, 5);

        document.getElementById("vr-hist-dashboard").innerHTML = `
          <div class="vr-overview-grid">
            <div class="vr-overview-main-card">
              <h3 class="vr-opinion-title">Property Health Check</h3>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Overall Title Status</span><span class="vr-stat-val" style="color:${isFlagged ? 'var(--red)' : 'var(--green)'}">${statusIcon}</span></div>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Risk Score</span><span class="vr-stat-val">${riskScore} / 100 (${escHtml(db.risk_label || 'Low Risk')})</span></div>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Documents Processed</span><span class="vr-stat-val">${db.documents_processed || 0}</span></div>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Critical / High Risks</span><span class="vr-stat-val" style="color:var(--red)">${db.critical_findings || 0}</span></div>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Medium Risks</span><span class="vr-stat-val" style="color:var(--amber)">${verifyReport.dashboard?.medium_findings || 0}</span></div>
              <div class="vr-stat-box"><span class="vr-stat-lbl">Missing Critical Documents</span><span class="vr-stat-val" style="color:var(--red)">${db.missing_documents_count || 0}</span></div>
              <div class="vr-action-bar ${actionClass}" style="margin-top:16px">${escHtml(db.recommended_action || '')}</div>
            </div>
            <div class="vr-overview-side-card">
              <h3 class="vr-opinion-title">Top Risks Detected</h3>
              <ul class="vr-risk-list" style="margin:0">
                ${topRisks.map(r => `
                  <li style="display:flex;align-items:center;gap:8px;font-size:12px;border-bottom:1px solid var(--border);padding:8px 0">
                    <span class="vr-issue-dot ${r.severity}"></span>
                    <div style="flex:1">
                      <strong>${escHtml(r.title)}</strong>
                      <div style="color:var(--gray);font-size:10px">${escHtml(r.what_was_found || '')}</div>
                    </div>
                  </li>
                `).join('')}
              </ul>
            </div>
          </div>`;
      };

      // Helper to render Missing Docs
      const renderHistMissingDocs = () => {
        const missing = verifyReport.missing_documents || [];
        const importantMissing = ["SALE_DEED", "ENCUMBRANCE_CERTIFICATE", "KHATA", "PROPERTY_REGISTER_CARD", "PROPERTY_TAX_ASSESSMENT", "MUTATION", "OCCUPANCY_CERTIFICATE", "CONVERSION_ORDER", "RTC_PAHANI", "CDP_PLAN"];

        let missingDocsList = [...missing];
        const presentDocs = Object.keys(verifyReport.per_doc_findings || {});

        importantMissing.forEach(doc => {
          const cleanName = doc.replace(/_/g, ' ') || doc;
          const isPresent = presentDocs.some(p => p.toUpperCase() === doc.toUpperCase());
          const alreadyAdded = missingDocsList.some(m => m.toUpperCase().includes(doc.toUpperCase()));
          if (!isPresent && !alreadyAdded) {
            missingDocsList.push(cleanName.replace(/_/g, ' ').toUpperCase());
          }
        });

        document.getElementById("vr-hist-missing-docs-section").innerHTML = `
          <h3 class="vr-opinion-title">Due Diligence Document Completeness</h3>
          <p style="font-size:12px;color:var(--gray);margin-bottom:16px">Tiles show documents required for title clearance. Click on any tile to see why it is important.</p>
          <div class="vr-missing-tile-grid">
            ${missingDocsList.map(doc => `
              <div class="vr-missing-tile" onclick="openMissingDocExplanation('${escHtml(doc)}')">
                <div class="vr-missing-tile-title">${escHtml(doc.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()))}</div>
                <div class="vr-missing-tile-status">Missing</div>
              </div>`).join('')}
          </div>`;
      };

      // Helper to render Final opinion
      const renderHistFinalReport = () => {
        const opinion = verifyReport.final_opinion || {};
        const isUnsafe = opinion.final_recommendation !== "SAFE TO PROCEED";
        document.getElementById("vr-hist-final-opinion").innerHTML = `
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
              <div class="vr-field-label" style="margin-top:16px">Major Risks</div>
              <ul class="vr-risk-list">${opinion.major_risks.map(r => `<li>${escHtml(r)}</li>`).join('')}</ul>
            ` : ''}

            ${(opinion.recommended_actions || []).length > 0 ? `
              <div class="vr-field-label" style="margin-top:16px">Recommended Actions</div>
              <ul class="vr-checklist">${opinion.recommended_actions.map(a => `<li>${escHtml(a)}</li>`).join('')}</ul>
            ` : ''}

            <div class="vr-final-rec ${isUnsafe ? 'danger' : 'safe'}" style="margin-top:20px">
              ${isUnsafe ? '❌' : '✅'} ${escHtml(opinion.final_recommendation || '')}
              <div class="reason">${escHtml(opinion.final_reason || '')}</div>
            </div>
          </div>`;
      };

      // Dynamic filtering and rendering inside history
      let histSearchQuery = "";
      let histFilterSeverity = "";
      let histActivePerDocType = null;

      const applyHistFiltersAndRender = () => {
        const search = histSearchQuery.toLowerCase().trim();
        const matchesHistFilter = (f) => {
          if (histFilterSeverity && f.severity !== histFilterSeverity) return false;
          if (search) {
            const matchText = [f.title, f.what_was_found, f.why_flagged].join(' ').toLowerCase();
            if (!matchText.includes(search)) return false;
          }
          return true;
        };

        // Cross-doc
        const cross = (verifyReport.cross_doc_findings || []).filter(matchesHistFilter);
        let crossHtml = '<h3 class="vr-opinion-title">Cross-Document Inconsistencies</h3>';
        if (cross.length > 0) {
          crossHtml += cross.map(f => buildIssueRow(f)).join('');
        } else {
          crossHtml += '<p style="color:var(--gray);font-size:13px;padding:12px">No matching cross-document inconsistencies.</p>';
        }
        document.getElementById("vr-hist-cross-doc-section").innerHTML = crossHtml;

        // Per-doc
        const perDocMap = verifyReport.per_doc_findings || {};
        const perDocKeys = Object.keys(perDocMap);
        if (perDocKeys.length > 0 && !histActivePerDocType) {
          histActivePerDocType = perDocKeys[0];
        }

        let perDocHtml = `
          <h3 class="vr-opinion-title">Individual Document Verifications</h3>
          <div class="vr-split-layout">
            <div class="vr-split-sidebar">
              ${perDocKeys.map(dt => {
                const group = perDocMap[dt] || {};
                const issues = (group.issues || []).filter(matchesHistFilter);
                const docLabel = dt.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
                const activeClass = dt === histActivePerDocType ? "active" : "";
                return `
                  <div class="vr-split-sidebar-item ${activeClass}" id="hist-sidebar-item-${dt}">
                    <span>${escHtml(docLabel)}</span>
                    <span class="vr-split-sidebar-badge">${issues.length}</span>
                  </div>`;
              }).join('')}
            </div>
            <div class="vr-split-content" id="vr-hist-split-content">
              ${histActivePerDocType ? (() => {
                const group = perDocMap[histActivePerDocType] || {};
                const issues = (group.issues || []).filter(matchesHistFilter);
                if (issues.length > 0) {
                  return issues.map(f => buildIssueRow(f)).join('');
                }
                return '<p style="color:var(--gray);font-size:13px;padding:12px">No issues flagged in this document.</p>';
              })() : '<p style="color:var(--gray);font-size:13px;padding:12px">No document selected.</p>'}
            </div>
          </div>`;
        document.getElementById("vr-hist-per-doc-section").innerHTML = perDocHtml;

        // Bind sidebar item clicks
        perDocKeys.forEach(dt => {
          const el = document.getElementById(`hist-sidebar-item-${dt}`);
          if (el) {
            el.addEventListener("click", () => {
              histActivePerDocType = dt;
              applyHistFiltersAndRender();
            });
          }
        });
      };

      // Initial pane rendering
      renderHistOverview();
      renderHistMissingDocs();
      renderHistFinalReport();
      applyHistFiltersAndRender();

      // Bind Tab Navigation Click events for history
      document.getElementById("vr-hist-nav-tabs").addEventListener("click", e => {
        const tabEl = e.target.closest(".vr-nav-tab");
        if (tabEl) {
          container.querySelectorAll("#vr-hist-nav-tabs .vr-nav-tab").forEach(t => t.classList.remove("active"));
          tabEl.classList.add("active");
          const targetTab = tabEl.dataset.tab;
          container.querySelectorAll(".vr-tab-pane").forEach(p => p.classList.remove("active"));
          document.getElementById(`pane-${targetTab}`).classList.add("active");
        }
      });

      // Bind Search events
      document.getElementById("vr-hist-global-search").addEventListener("input", e => {
        histSearchQuery = e.target.value;
        applyHistFiltersAndRender();
      });

      // Bind Severity Select events
      document.getElementById("vr-hist-filter-severity").addEventListener("change", e => {
        histFilterSeverity = e.target.value;
        applyHistFiltersAndRender();
      });

      // Bind PDF download button
      const histPdfBtn = document.getElementById("btn-hist-download-pdf");
      if (histPdfBtn) {
        histPdfBtn.addEventListener("click", () => {
          histPdfBtn.textContent = "⏳ Generating…";
          histPdfBtn.disabled = true;
          setTimeout(() => {
            try {
              if (window.downloadVerificationPDF) {
                window.downloadVerificationPDF(verifyReport, caseId);
              } else {
                alert("PDF library not available. Please refresh the page.");
              }
            } catch (e) {
              console.error("PDF generation failed:", e);
              alert("PDF generation failed: " + e.message);
            }
            histPdfBtn.textContent = "⬇ PDF Report";
            histPdfBtn.disabled = false;
          }, 50);
        });
      }

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
