// ── Case History Sidebar ────────────────────────────────────────────────────────

window.HistoryPanel = {
  cases: [],
  activeCaseId: null,

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
      return `<div class="sidebar-item${active}" data-case-id="${escHtml(c.id)}">
        <div class="case-id">${escHtml(c.id)}</div>
        <div class="case-meta">
          <span>${pct}% done</span>
          <span>${c.completed_docs}/${c.total_docs}</span>
          <span class="badge badge-${c.status === "completed" ? "green" : c.status === "processing" ? "amber" : "blue"}">${escHtml(c.status)}</span>
        </div>
        <div class="case-date">${escHtml(c.created_at || "")}</div>
      </div>`;
    }).join("");

    container.querySelectorAll(".sidebar-item").forEach(el => {
      el.addEventListener("click", () => this.selectCase(el.dataset.caseId));
    });
  },

  async selectCase(caseId) {
    this.activeCaseId = caseId;
    this.renderList();

    const panel = document.getElementById("history-detail");
    ["upload", "processing", "results", "verify"].forEach(stage => {
      document.getElementById(`stage-${stage}`).classList.add("hidden");
    });
    panel.classList.remove("hidden");
    panel.innerHTML = `<div class="sidebar-loading">Loading details...</div>`;

    const [bundle, ocrList, files] = await Promise.all([
      API.bundle(caseId),
      API.ocrRawList(caseId),
      API.caseFiles(caseId),
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
        </div>
      </div>
    `;

    document.getElementById("history-close").addEventListener("click", () => {
      this.activeCaseId = null;
      this.renderList();
      showStage("upload");
      setStep(1);
    });

    document.querySelectorAll("#history-tabs .history-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#history-tabs .history-tab").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        ["bundle", "ocr", "files"].forEach(p => {
          document.getElementById(`history-panel-${p}`).style.display = p === btn.dataset.panel ? "block" : "none";
        });
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
  }
};
