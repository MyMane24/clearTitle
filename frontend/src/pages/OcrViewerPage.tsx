import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, FileText, Loader2, RefreshCw, ScrollText } from 'lucide-react';
import { API, getToken, OcrDocText } from '../api/backend';

/** Split a merged OCR `full_text` on its `--- Page N ---` markers. */
export function splitPages(fullText: string): { page: number; text: string }[] {
  if (!fullText || !fullText.trim()) return [];
  const re = /---\s*Page\s+(\d+)\s*---/gi;
  const blocks: { page: number; text: string }[] = [];
  let m: RegExpExecArray | null;
  let prevEnd = 0;
  let prevPage = 0;
  while ((m = re.exec(fullText)) !== null) {
    const chunk = fullText.slice(prevEnd, m.index).trim();
    if (chunk) blocks.push({ page: prevPage, text: chunk });
    prevPage = parseInt(m[1], 10);
    prevEnd = re.lastIndex;
  }
  const tail = fullText.slice(prevEnd).trim();
  if (tail) blocks.push({ page: prevPage, text: tail });
  return blocks;
}

function fmtDate(value?: string | null): string {
  if (!value) return '';
  const d = new Date(value);
  return isNaN(d.getTime()) ? value : d.toLocaleString();
}

export function OcrViewerPage() {
  const navigate = useNavigate();
  const { caseId: routeCaseId } = useParams<{ caseId?: string }>();

  const [cases, setCases] = useState<{ id: string; created_at?: string }[]>([]);
  const [selectedCase, setSelectedCase] = useState<string>('');
  const [docs, setDocs] = useState<OcrDocText[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  // Guard: this page needs an authenticated session.
  useEffect(() => {
    if (!getToken()) navigate('/login', { replace: true });
  }, [navigate]);

  // Load the user's cases once.
  useEffect(() => {
    (async () => {
      const res = await API.listCases();
      setCases(res.cases);
      setSelectedCase(prev => prev || routeCaseId || res.cases[0]?.id || '');
    })();
  }, [routeCaseId]);

  const loadOcr = useCallback(async (caseId: string) => {
    if (!caseId) return;
    setLoading(true);
    setError('');
    try {
      const res = await API.getOcr(caseId);
      setDocs(res.documents);
      setSelectedDoc(res.documents[0]?.doc_id || '');
    } catch (e: any) {
      setError(e.message || 'Failed to load OCR text.');
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedCase) loadOcr(selectedCase);
  }, [selectedCase, loadOcr]);

  const activeDoc = useMemo(
    () => docs.find(d => d.doc_id === selectedDoc) || null,
    [docs, selectedDoc],
  );
  const pages = useMemo(() => (activeDoc ? splitPages(activeDoc.full_text) : []), [activeDoc]);

  const copyText = async () => {
    if (!activeDoc) return;
    try {
      await navigator.clipboard.writeText(activeDoc.full_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div style={S.root}>
      <style>{`@keyframes ocrspin{to{transform:rotate(360deg)}}.ocr-spin{animation:ocrspin 1s linear infinite}`}</style>
      <header style={S.header}>
        <Link to="/app" style={S.back}>
          <ArrowLeft size={16} />
          <span>Dashboard</span>
        </Link>
        <div style={S.headerMid}>
          <ScrollText size={18} style={{ color: '#ea580c' }} />
          <span style={S.headerTitle}>OCR Full Text Viewer</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={S.selectLabel}>Case</label>
<select
            style={S.select}
            value={selectedCase}
            onChange={e => setSelectedCase(e.target.value)}
          >
            {cases.length === 0 && <option value="">No cases</option>}
            {cases.map(c => (
              <option key={c.id} value={c.id}>
                {c.id}{c.created_at ? ` · ${fmtDate(c.created_at)}` : ''}
              </option>
            ))}
          </select>
          <button
            style={S.iconBtn}
            title="Reload"
            onClick={() => selectedCase && loadOcr(selectedCase)}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </header>

      <div style={S.layout}>
        <aside style={S.sidebar}>
          <div style={S.sidebarHead}>Documents ({docs.length})</div>
          {docs.length === 0 && !loading && (
            <div style={S.empty}>No documents for this case.</div>
          )}
          {docs.map(d => {
            const active = d.doc_id === selectedDoc;
            return (
              <button
                key={d.doc_id}
                onClick={() => setSelectedDoc(d.doc_id)}
                style={{ ...S.docItem, ...(active ? S.docItemActive : {}) }}
              >
                <FileText size={15} style={{ flexShrink: 0, color: active ? '#ea580c' : '#94a3b8' }} />
                <span style={S.docItemBody}>
                  <span style={S.docItemName}>{d.filename || d.doc_id}</span>
                  <span style={S.docItemMeta}>
                    {d.doc_id}
                    {d.document_type ? ` · ${d.document_type}` : ''}
                    {d.total_pages ? ` · ${d.total_pages}p` : ''}
                  </span>
                </span>
              </button>
            );
          })}
        </aside>

        <main style={S.main}>
        {loading && (
          <div style={S.center}>
            <Loader2 size={22} className="ocr-spin" />
            <span>Loading OCR text…</span>
          </div>
        )}

        {!loading && error && <div style={S.errorBox}>{error}</div>}

        {!loading && !error && activeDoc && (
          <>
            <div style={S.docHead}>
              <div>
                <h1 style={S.docTitle}>{activeDoc.filename || activeDoc.doc_id}</h1>
                <div style={S.docSub}>
                  {activeDoc.doc_id}
                  {activeDoc.document_type ? ` · ${activeDoc.document_type}` : ''}
                  {activeDoc.total_pages ? ` · ${activeDoc.total_pages} page(s)` : ''}
                  {` · ${activeDoc.full_text.length.toLocaleString()} chars`}
                </div>
              </div>
              <button style={S.copyBtn} onClick={copyText} disabled={!activeDoc.full_text}>
                {copied ? 'Copied' : 'Copy full text'}
              </button>
            </div>

            {pages.length === 0 ? (
              <div style={S.emptyBox}>No OCR text available for this document.</div>
            ) : (
              pages.map((p, i) => (
                <section key={i} style={S.pageCard}>
                  <div style={S.pageCardHead}>
                    {p.page > 0 ? `Page ${p.page}` : 'Content'}
                  </div>
                  <pre style={S.pageText}>{p.text}</pre>
                </section>
              ))
            )}
          </>
        )}
        </main>
      </div>
    </div>
  );
}

const S: Record<string, React.CSSProperties> = {
  root: { minHeight: '100vh', background: '#f8fafc', color: '#1e293b', fontFamily: 'inherit' },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
    padding: '12px 20px', background: '#fff', borderBottom: '1px solid #e2e8f0',
    position: 'sticky', top: 0, zIndex: 10,
  },
  back: { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#475569', textDecoration: 'none', fontSize: 13, fontWeight: 600 },
  headerMid: { display: 'flex', alignItems: 'center', gap: 8 },
  headerTitle: { fontSize: 15, fontWeight: 700 },
  selectLabel: { fontSize: 12, color: '#64748b', fontWeight: 600 },
  select: { padding: '6px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff', fontSize: 13, color: '#1e293b' },
  iconBtn: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 7, borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff', color: '#475569', cursor: 'pointer' },
  layout: { display: 'flex', alignItems: 'flex-start', gap: 0 },
  sidebar: { width: 300, flexShrink: 0, borderRight: '1px solid #e2e8f0', background: '#fff', minHeight: 'calc(100vh - 49px)', padding: '12px 8px', boxSizing: 'border-box' },
  sidebarHead: { fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#94a3b8', padding: '6px 10px' },
  empty: { padding: '10px 12px', color: '#94a3b8', fontSize: 13 },
  docItem: { display: 'flex', gap: 10, width: '100%', textAlign: 'left', padding: '9px 10px', borderRadius: 8, border: 'none', background: 'transparent', cursor: 'pointer', marginBottom: 2 },
  docItemActive: { background: '#fff7ed' },
  docItemBody: { display: 'flex', flexDirection: 'column', minWidth: 0 },
  docItemName: { fontSize: 13, fontWeight: 600, color: '#292524', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  docItemMeta: { fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' },
  main: { flex: 1, padding: 24, maxWidth: 960, margin: '0 auto', boxSizing: 'border-box' },
  center: { display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 40, justifyContent: 'center' },
  errorBox: { padding: 16, background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', borderRadius: 10, fontSize: 14 },
  emptyBox: { padding: 24, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, color: '#64748b', fontSize: 14 },
  docHead: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 18 },
  docTitle: { margin: 0, fontSize: 18, fontWeight: 700, color: '#0f172a' },
  docSub: { marginTop: 4, fontSize: 12, color: '#64748b', fontFamily: 'monospace' },
  copyBtn: { flexShrink: 0, padding: '7px 14px', borderRadius: 8, border: '1px solid #fdba74', background: '#fff7ed', color: '#c2410c', fontSize: 12, fontWeight: 700, cursor: 'pointer' },
  pageCard: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, marginBottom: 16, overflow: 'hidden' },
  pageCardHead: { padding: '8px 16px', borderBottom: '1px solid #f1f5f9', fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#ea580c', background: '#fffbf7' },
  pageText: { margin: 0, padding: '16px 18px', fontSize: 13.5, lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: '#1e293b', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
};

export default OcrViewerPage;