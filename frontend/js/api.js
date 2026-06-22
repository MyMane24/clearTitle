// ── API client ──────────────────────────────────────────────────────────────────

async function apiError(response, fallback = "Request failed") {
  const text = await response.text();
  if (!text) return fallback;
  try {
    const data = JSON.parse(text);
    return data.detail || data.message || fallback;
  } catch {
    return text;
  }
}

const API = {
  async health() {
    const r = await fetch("/health");
    return r.json();
  },

  async upload(files) {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await apiError(r));
    return r.json();
  },

  async process(caseId) {
    const r = await fetch(`/api/process/${caseId}`, { method: "POST" });
    if (!r.ok) throw new Error(await apiError(r));
    return r.json();
  },

  async status(caseId) {
    const r = await fetch(`/api/status/${caseId}`);
    return r.json();
  },

  async retry(caseId) {
    const r = await fetch(`/api/retry/${caseId}`, { method: "POST" });
    if (!r.ok) throw new Error(await apiError(r));
    return r.json();
  },

  async clearAll() {
    await fetch("/api/clear", { method: "POST" });
  },

  async skipDoc(caseId, docId) {
    const r = await fetch(`/api/case/${caseId}/doc/${docId}/skip`, { method: "POST" });
    if (!r.ok) throw new Error(await apiError(r));
    return r.json();
  },

  async replaceDoc(caseId, docId, file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/case/${caseId}/doc/${docId}/replace`, { method: "POST", body: fd });
    if (!r.ok) throw new Error(await apiError(r));
    return r.json();
  },

  async result(caseId, docId) {
    const r = await fetch(`/api/result/${caseId}/${docId}`);
    if (!r.ok) throw new Error("Result not ready");
    return r.json();
  },

  async bundle(caseId) {
    const r = await fetch(`/api/case/${caseId}/bundle`);
    if (!r.ok) return null;
    return r.json();
  },

  async ocrRaw(caseId, docId) {
    const r = await fetch(`/api/case/${caseId}/doc/${docId}/ocr-raw`);
    if (!r.ok) return null;
    return r.json();
  },

  async ocrRawList(caseId) {
    const r = await fetch(`/api/case/${caseId}/ocr-raw`);
    if (!r.ok) return { documents: [] };
    return r.json();
  },

  async caseFiles(caseId) {
    const r = await fetch(`/api/case/${caseId}/files`);
    if (!r.ok) return null;
    return r.json();
  },

  async listCases() {
    const r = await fetch("/api/cases");
    if (!r.ok) return { cases: [] };
    return r.json();
  },

  async verify(caseId) {
    const r = await fetch(`/api/verify/${caseId}`, { method: "POST" });
    if (!r.ok) throw new Error(await apiError(r, "Verification failed"));
    return r.json();
  },

  async submitFeedback(caseId, feedback) {
    const r = await fetch(`/api/verify/${caseId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: caseId, feedback }),
    });
    if (!r.ok) throw new Error(await apiError(r, "Failed"));
    return r.json();
  },

  async learningsStats() {
    const r = await fetch("/api/verify/learnings/stats");
    return r.json();
  },
};
