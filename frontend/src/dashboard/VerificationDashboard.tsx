import React, { useCallback, useEffect, useRef, useState } from 'react';
import './dashboard.css';
import {
  API, AuthResponse, CaseListItem, CaseResults, HealthStatus,
  StatusResponse, TitleChainEntry, VerificationItem, getToken, setToken,
} from '../api/backend';
import { AuthScreen } from './AuthScreen';
import { DocPanel } from './utils';
import clearTitleLogo from '../assets/clearTitle.png';
import {
  AlertTriangle, ArrowRight, BarChart3, Bot, CheckCircle2, FileText, FileUp,
  FlaskConical, FolderOpen, List, Lock, Play, RefreshCw, Trash2, Upload, X, LogOut,
} from 'lucide-react';

type View = 'upload' | 'processing' | 'results';

type UploadSlot = 'sale_deed' | 'ec' | 'additional';

interface SlotFile { file: File; slot: UploadSlot }

interface LogEntry { text: string; cls: string }

const COMPLETE_STATUSES = ['complete', 'completed', 'partial'];

function logClass(line: string): string {
  if (line.includes("✗") || line.toLowerCase().includes("failed")) return "log-err";
  if (line.includes("✓") || line.toLowerCase().includes("complete")) return "log-ok";
  if (line.includes("Step") || line.includes("──")) return "log-info";
  if (line.includes("⚠")) return "log-warn";
  return "";
}

function caseBadgeClass(status: string): string {
  if (status === "complete" || status === "completed") return "badge-green";
  if (status === "processing") return "badge-amber";
  if (status === "failed") return "badge-red";
  return "badge-blue";
}

function verdictBadge(verdict?: string | null): React.ReactNode {
  if (!verdict) return null;
  const v = verdict.toUpperCase();
  const cls = v === "VERIFIED" ? "badge-green" : v === "NOT_VERIFIED" ? "badge-red" : "badge-amber";
  return <span className={`badge ${cls}`}>{verdict}</span>;
}

function fmtDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

const CHAIN_ROLE_LABELS: Record<string, string> = {
  THE_SD: 'The Sale Deed being verified',
  PREDECESSOR_TITLE: 'Earlier title transfer (before the Sale Deed)',
  SUBSEQUENT_TRANSFER: 'Transfer after the Sale Deed — review for conflict',
  DIVERGENT_BRANCH: 'Different share/portion of the same property',
  ENCUMBRANCE: 'Non-title document (mortgage / lease / agreement)',
};

const UPLOAD_SLOTS: { id: UploadSlot; label: string; desc: string; required: boolean; multiple?: boolean }[] = [
  { id: 'sale_deed', label: 'Sale Deed', desc: 'The current sale deed conveying title to the buyer.', required: true },
  { id: 'ec', label: 'Encumbrance Certificate (EC)', desc: 'The EC ledger covering the search period.', required: true },
  { id: 'additional', label: 'Additional Documents', desc: 'RTC, Khata, Mutation, prior deeds — optional.', required: false, multiple: true },
];

function partyNames(list: any[]): string {
  return (list || [])
    .map(v => (typeof v === 'string' ? v : v?.entity_name || JSON.stringify(v)))
    .filter(Boolean)
    .join('; ') || '—';
}

function ChainCard({ e, tone }: { e: TitleChainEntry; tone: string }) {
  return (
    <div className={`chain-card${tone ? ' ' + tone : ''}`}>
      <div className="chain-head">
        <strong>{e.transaction_type || "Transaction"}</strong>
        <span className="badge badge-blue">Entry {e.transaction_index ?? "—"}</span>
      </div>
      {e.chain_role && (
        <div className={`chain-role role-${e.chain_role.toLowerCase()}`}>
          {CHAIN_ROLE_LABELS[e.chain_role] || e.chain_role}
        </div>
      )}
      {e.portion && (
        <div className="chain-field chain-portion"><span>Portion:</span> {e.portion}</div>
      )}
      <div className="chain-date">{e.execution_date ? `Date: ${e.execution_date}` : ""}</div>
      {e.property_identity && (
        <div className="chain-field"><span>Property:</span> {e.property_identity}</div>
      )}
      {e.registration_reference && (
        <div className="chain-field"><span>Registration:</span> {e.registration_reference}</div>
      )}
      {e.share_fraction && (
        <div className="chain-field"><span>Share:</span> {e.share_fraction}</div>
      )}
      {e.parties && (
        <div className="chain-field">
          <span>From:</span> {partyNames(e.parties?.vendors)}
          <div className="chain-field"><span>To:</span> {partyNames(e.parties?.purchasers)}</div>
        </div>
      )}
      {e.financials && (
        <div className="chain-field">
          <span>Financials:</span>{' '}
          {typeof e.financials === 'string' ? e.financials : JSON.stringify(e.financials)}
        </div>
      )}
      {e.explanation && <div className="chain-explanation">{e.explanation}</div>}
      {e.source && <div className="chain-source">source: {e.source}</div>}
    </div>
  );
}

function ChainList({ entries, tone }: { entries: TitleChainEntry[]; tone: string }) {
  return (
    <div className="chain-timeline">
      {entries.map((e, i) => (
        <div className="chain-item" key={e.transaction_index ?? i}>
          <div className="chain-marker">
            <span className="chain-dot">{i + 1}</span>
            {i < entries.length - 1 && <span className="chain-line" />}
          </div>
          <ChainCard e={e} tone={tone} />
        </div>
      ))}
    </div>
  );
}

function ChainSection({ title, entries, tone }: { title: string; entries: TitleChainEntry[]; tone: string }) {
  if (!entries.length) return null;
  return (
    <>
      <div className="chain-section-title">{title}</div>
      <ChainList entries={entries} tone={tone} />
    </>
  );
}

function ChainTimeline({ chain, status, titleStory }: {
  chain: TitleChainEntry[];
  status?: string;
  titleStory?: string;
}) {
  if (status === 'no_transactions') {
    return (
      <div className="vr-sheet-empty warn">
        There are no transactions existing for this property in EC. Please upload a valid EC.
      </div>
    );
  }
  if (!chain || chain.length === 0) {
    return <div className="vr-sheet-empty">No title chain entries yet. Title chain is built once all documents are structured.</div>;
  }

  const hasRoles = chain.some(e => e.chain_role);
  if (!hasRoles) {
    return (
      <div>
        {titleStory && <div className="chain-story">{titleStory}</div>}
        <ChainList entries={chain} tone="" />
      </div>
    );
  }

  const sd = chain.find(e => e.chain_role === 'THE_SD');
  const predecessors = chain.filter(e => e.chain_role === 'PREDECESSOR_TITLE');
  const subsequent = chain.filter(e => e.chain_role === 'SUBSEQUENT_TRANSFER');
  const divergent = chain.filter(e => e.chain_role === 'DIVERGENT_BRANCH');
  const encumbrances = chain.filter(e => e.chain_role === 'ENCUMBRANCE');
  const others = chain.filter(e => !e.chain_role);

  return (
    <div className="chain-tree">
      {titleStory && <div className="chain-story">{titleStory}</div>}
      {sd && (
        <>
          <div className="chain-section-title">This Sale Deed</div>
          <div className="chain-timeline">
            <div className="chain-item">
              <div className="chain-marker">
                <span className="chain-dot sd">SD</span>
              </div>
              <ChainCard e={sd} tone="sd" />
            </div>
          </div>
        </>
      )}
      <ChainSection title="Chain of title before this Sale Deed" entries={predecessors} tone="predecessor" />
      <ChainSection title="Transfers after this Sale Deed (review)" entries={subsequent} tone="subsequent" />
      <ChainSection title="Other transactions on this property (different portions)" entries={divergent} tone="divergent" />
      <ChainSection title="Encumbrances — mortgages, leases, agreements" entries={encumbrances} tone="encumbrance" />
      <ChainSection title="Other entries" entries={others} tone="" />
    </div>
  );
}

function VerifyResults({ verification, locked, onUnlock }: {
  verification: NonNullable<CaseResults['verification']>;
  locked?: boolean;
  onUnlock?: () => void;
}) {
  const items: VerificationItem[] = verification.items || [];
  const summary = verification.summary || {};
  const counts: Record<string, number> = summary.counts || {};
  const verdict = (verification.verdict || "N/A").toUpperCase();
  const verdictCls = verdict === "VERIFIED" ? "badge-green" : verdict === "NOT_VERIFIED" ? "badge-red" : "badge-amber";

  return (
    <div>
      <div className="metrics-row">
        <div className="metric-box">
          <div className="val"><span className={`badge ${verdictCls}`}>{verdict}</span></div>
          <div className="lbl">Verdict</div>
        </div>
        <div className="metric-box"><div className="val">{counts.VERIFIED ?? 0}</div><div className="lbl">Verified</div></div>
        <div className="metric-box"><div className="val">{counts.NOT_VERIFIED ?? 0}</div><div className="lbl">Not verified</div></div>
        <div className="metric-box"><div className="val">{counts['N/A'] ?? 0}</div><div className="lbl">N/A</div></div>
        <div className="metric-box"><div className="val">{items.length}</div><div className="lbl">Fields checked</div></div>
      </div>

      {summary.overall_comment && (
        <div className="verify-comment">{summary.overall_comment}</div>
      )}

      {locked ? (
        <div className="guest-lock">
          <Lock size={22} />
          <p><strong>Field-by-field verification is locked.</strong></p>
          <p>Sign in to see the full verification table for every field.</p>
          {onUnlock && <button className="btn btn-primary" onClick={onUnlock}>Sign in to unlock</button>}
        </div>
      ) : items.length === 0 ? (
        <div className="vr-sheet-empty">Verification has not run yet.</div>
      ) : (
        <table className="verify-table">
          <thead>
            <tr><th>Field</th><th>Sale Deed</th><th>EC Ledger</th><th>Status</th><th>Notes</th></tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const s = (it.status || "N/A").toUpperCase();
              const cls = s === "VERIFIED" ? "vstatus-ok" : s === "NOT_VERIFIED" ? "vstatus-fail" : "vstatus-na";
              return (
                <tr key={i}>
                  <td className="verify-field" data-label="Field">{it.field}</td>
                  <td data-label="Sale Deed">{it.sd_value != null ? String(it.sd_value) : "—"}</td>
                  <td data-label="EC Ledger">{it.ec_value != null ? String(it.ec_value) : "—"}</td>
                  <td data-label="Status"><span className={`vstatus ${cls}`}>{s}</span></td>
                  <td className="verify-notes" data-label="Notes">{it.notes || ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function GuestReportPreview({ results, onSignIn, onNewCase }: {
  results: CaseResults;
  onSignIn: () => void;
  onNewCase: () => void;
}) {
  const sd = results.documents.find(d =>
    d.document_type === 'SALE_DEED' || d.structured?.document_type === 'SALE_DEED'
  );
  const s = sd?.structured || {};
  const vendors: string[] = (s.parties?.vendors || []).map((v: any) => v.entity_name).filter(Boolean);
  const purchasers: string[] = (s.parties?.purchasers || []).map((p: any) => p.entity_name).filter(Boolean);
  const scheduleText = String(
    s.property_schedule?.full_schedule_description
      || [s.property_schedule?.cts_number, s.property_schedule?.survey_number].filter(Boolean).join(', ')
      || (results.title_chain?.source?.sd_property
        ? (typeof results.title_chain.source.sd_property === 'string'
          ? results.title_chain.source.sd_property
          : JSON.stringify(results.title_chain.source.sd_property))
        : '')
  );
  const meta = s.file_metadata || {};
  const execDate = meta.execution_date || meta.registration_date || meta.document_date || undefined;
  const caseInfo = results.case;

  return (
    <div className="guest-preview">
      <div className="guest-preview-top">
        <span className="guest-preview-badge"><Lock size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} /> Guest Preview</span>
        <span className="guest-preview-meta">{caseInfo?.case_id}{caseInfo?.status ? ` · ${caseInfo.status}` : ''}</span>
        <button className="btn btn-secondary" style={{ marginLeft: 'auto' }} onClick={onNewCase}>New Case</button>
      </div>

      <div className="guest-preview-hero">
        <h3 className="guest-preview-title">Property Summary</h3>
        {vendors.length > 0 && (
          <div className="guest-preview-field">
            <div className="gp-label">Seller{vendors.length > 1 ? 's' : ''}</div>
            <div className="gp-value">{vendors.join(', ')}</div>
          </div>
        )}
        {purchasers.length > 0 && (
          <div className="guest-preview-field">
            <div className="gp-label">Purchaser{purchasers.length > 1 ? 's' : ''}</div>
            <div className="gp-value">{purchasers.join(', ')}</div>
          </div>
        )}
        {scheduleText && (
          <div className="guest-preview-field">
            <div className="gp-label">Property Schedule</div>
            <div className="gp-value">{scheduleText}</div>
          </div>
        )}
        {execDate && (
          <div className="guest-preview-field">
            <div className="gp-label">Execution Date</div>
            <div className="gp-value">{execDate}</div>
          </div>
        )}
        {!vendors.length && !purchasers.length && !scheduleText && (
          <div className="guest-preview-field">
            <div className="gp-label">Property</div>
            <div className="gp-value muted">The summary will appear here once the Sale Deed is processed.</div>
          </div>
        )}
      </div>

      <div className="guest-preview-lock">
        <div className="guest-preview-lock-icon"><Lock size={26} /></div>
        <p className="guest-preview-lock-title">Full verification report is locked</p>
        <p className="guest-preview-lock-sub">Sign in to unlock the complete title chain and field-by-field verification report.</p>
        <button className="btn btn-primary guest-preview-cta" onClick={onSignIn}>
          <Lock size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Sign in to Unlock Full Report
        </button>
      </div>
    </div>
  );
}

export function VerificationDashboard() {
  const [auth, setAuth] = useState<AuthResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(!!getToken());
  const [showAuth, setShowAuth] = useState(false);
  const pendingLinkRef = useRef<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [files, setFiles] = useState<SlotFile[]>([]);
  const [currentCaseId, setCurrentCaseId] = useState<string | null>(null);
  const [view, setView] = useState<View>('upload');
  const [progressPct, setProgressPct] = useState(0);
  const [progressLabel, setProgressLabel] = useState('Initialising...');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [statusData, setStatusData] = useState<StatusResponse | null>(null);
  const [results, setResults] = useState<CaseResults | null>(null);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const addLog = useCallback((msg: string, cls = 'log-info') => {
    setLogs(prev => [...prev.slice(-200), { text: msg, cls }]);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // ── Auth bootstrap ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken()) { setAuthLoading(false); return; }
      try {
        const a = await API.me();
        if (!cancelled) setAuth(a);
      } catch {
        setToken(null);
        if (!cancelled) setAuth(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const logout = () => {
    setToken(null);
    setAuth(null);
    setAuthLoading(false);
    setShowAuth(false);
    pendingLinkRef.current = null;
    stopPolling();
    sessionStorage.removeItem("currentCaseId");
    setResults(null);
    setStatusData(null);
    setCurrentCaseId(null);
    setView('upload');
  };

  const handleAuthed = async (a: AuthResponse) => {
    setAuth(a);
    setShowAuth(false);
    loadCases();
    const linkCase = pendingLinkRef.current;
    pendingLinkRef.current = null;
    if (linkCase) {
      try { await API.link(linkCase); } catch { /* ignore */ }
      try {
        const data = await API.getResults(linkCase);
        setResults(data);
        const docs = data.documents.filter(d => d.status === "structured");
        if (docs.length > 0) setActiveDocId(String(docs[0].doc_id));
      } catch { /* ignore */ }
    }
  };

  const openAuth = (linkCaseId?: string) => {
    if (linkCaseId) pendingLinkRef.current = linkCaseId;
    setShowAuth(true);
  };

  // ── Health check ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await API.health();
        if (!cancelled) setHealth(d);
      } catch {
        if (!cancelled) setHealth({ status: 'error', sarvam_key: false, groq_key: false, gemini_key: false });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const healthOk = !!health && !!health.sarvam_key && !!health.groq_key && !!health.gemini_key;
  const healthText = !health ? "Checking..."
    : healthOk ? "API keys loaded"
      : `⚠ Missing: ${[!health.sarvam_key && "Sarvam", !health.groq_key && "Groq", !health.gemini_key && "Gemini"].filter(Boolean).join(", ")}`;

  // ── Sidebar: load cases ──
  const loadCases = useCallback(async () => {
    try {
      const data = await API.listCases();
      setCases(data.cases || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (auth) loadCases();
  }, [auth, loadCases]);

  // ── Resume last guest scan after a page refresh ──
  useEffect(() => {
    if (authLoading || auth) return;
    const caseId = sessionStorage.getItem("currentCaseId");
    if (!caseId) return;
    (async () => {
      try {
        const data = await API.getResults(caseId);
        setCurrentCaseId(caseId);
        setResults(data);
        const docs = data.documents.filter(d => d.status === "structured");
        if (docs.length > 0) setActiveDocId(String(docs[0].doc_id));
        const cs = data.case?.status;
        if (cs && !COMPLETE_STATUSES.includes(cs) && cs !== "failed") {
          setView('processing');
          startPolling(caseId);
        } else {
          setView('results');
        }
      } catch {
        sessionStorage.removeItem("currentCaseId");
      }
    })();
  }, [authLoading, auth]);

  // ── Files ──
  const slotCount = (slot: UploadSlot) => files.filter(f => f.slot === slot).length;

  const addFilesToSlot = (slot: UploadSlot, incoming: File[]) => {
    const pdfs = incoming.filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) return;
    setFiles(prev => {
      if (slot === 'additional') {
        const next = [...prev];
        pdfs.forEach(f => {
          if (!next.find(x => x.file.name === f.name && x.file.size === f.size)) {
            next.push({ file: f, slot });
          }
        });
        return next;
      }
      return [
        ...prev.filter(x => x.slot !== slot),
        { file: pdfs[0], slot },
      ];
    });
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const clearFiles = () => {
    setFiles([]);
    setCurrentCaseId(null);
  };

  const clearAllData = async () => {
    if (!confirm("This will clear ALL Redis data and purge pending Celery tasks. The page will reload. Continue?")) return;
    try { await API.clearAll(); } catch { /* ignore */ }
    window.location.reload();
  };

  // ── Processing ──
  const startProcessing = async () => {
    if (slotCount('sale_deed') < 1 || slotCount('ec') < 1) return;
    setView('processing');
    updateProgress(5, "Uploading documents...");

    let uploadResp;
    try {
      uploadResp = await API.upload(
        files.map(f => f.file),
        files.map(f => f.slot),
      );
    } catch (e: any) {
      addLog(`✗ Upload failed: ${e.message}`, "log-err");
      return;
    }

    setCurrentCaseId(uploadResp.case_id);
    sessionStorage.setItem("currentCaseId", uploadResp.case_id);
    addLog(`✓ ${(uploadResp.files || []).length} file(s) uploaded → Case ${uploadResp.case_id}`, "log-ok");
    loadCases();
    updateProgress(10, "Starting OCR pipeline...");

    try {
      await API.process(uploadResp.case_id);
      addLog("✓ Pipeline started — running in background", "log-ok");
    } catch (e: any) {
      addLog(`✗ Pipeline start failed: ${e.message}`, "log-err");
      return;
    }

    startPolling(uploadResp.case_id);
  };

  const updateProgress = useCallback((pct: number, label: string) => {
    setProgressPct(pct);
    setProgressLabel(label);
  }, []);

  const startPolling = (caseId: string) => {
    stopPolling();
    pollRef.current = setInterval(() => pollStatus(caseId), 2000);
  };

  const pollStatus = async (caseId: string) => {
    try {
      const s = await API.status(caseId);
      setStatusData(s);
      updateProgress(
        s.progress || 0,
        `${s.status || "running"} – ${s.completed_docs || 0}/${s.total_docs || 0} docs`
      );
      if (s.log && s.log.length) {
        setLogs(s.log.slice(-200).map(l => ({ text: l, cls: logClass(l) })));
      }
      if (COMPLETE_STATUSES.includes(s.status) || s.status === "failed") {
        stopPolling();
        updateProgress(100, "Pipeline complete");
        await showResults(caseId);
      }
    } catch (e: any) {
      addLog(`⚠ Polling error: ${e.message}`, "log-warn");
    }
  };

  const showResults = async (caseId: string) => {
    setView('results');
    sessionStorage.setItem("currentCaseId", caseId);
    try {
      const data = await API.getResults(caseId);
      setResults(data);
      const docs = data.documents.filter(d => d.status === "structured");
      if (docs.length > 0) setActiveDocId(String(docs[0].doc_id));
    } catch (e: any) {
      addLog(`✗ Failed to load results: ${e.message}`, "log-err");
    }
  };

  const loadResultsFor = async (caseId: string) => {
    setCurrentCaseId(caseId);
    setActiveCaseId(caseId);
    sessionStorage.setItem("currentCaseId", caseId);
    try {
      const data = await API.getResults(caseId);
      setResults(data);
      const docs = data.documents.filter(d => d.status === "structured");
      if (docs.length > 0) setActiveDocId(String(docs[0].doc_id));
      setView('results');
    } catch (e: any) {
      addLog(`✗ Failed to load results: ${e.message}`, "log-err");
    }
  };

  const runAnalysis = async () => {
    if (!currentCaseId) return;
    setAnalyzing(true);
    try {
      await API.analyze(currentCaseId);
      addLog("⏳ Title-chain + verification queued…", "log-info");
      setTimeout(() => {
        API.getResults(currentCaseId).then(setResults).catch(() => { });
        setAnalyzing(false);
      }, 4000);
    } catch (e: any) {
      addLog(`✗ Analyze failed: ${e.message}`, "log-err");
      setAnalyzing(false);
    }
  };

  // ── Results actions ──
  const skipDoc = async (docId: string) => {
    if (!currentCaseId) return;
    try {
      await API.skipDoc(currentCaseId, docId);
      addLog(`Skipped ${docId}`, "log-warn");
    } catch (e: any) {
      addLog(`✗ Skip failed: ${e.message}`, "log-err");
    }
  };

  const replaceDoc = async (docId: string, file: File) => {
    if (!currentCaseId) return;
    try {
      await API.replaceDoc(currentCaseId, docId, file);
      await API.retry(currentCaseId);
      setView('processing');
      addLog(`Replaced ${docId} — reprocessing…`, "log-info");
      startPolling(currentCaseId);
    } catch (e: any) {
      addLog(`✗ Replace failed: ${e.message}`, "log-err");
    }
  };

  const retryFailed = async () => {
    if (!currentCaseId) return;
    try {
      await API.retry(currentCaseId);
      setView('processing');
      addLog("Retrying failed document(s)…", "log-info");
      startPolling(currentCaseId);
    } catch (e: any) {
      addLog(`✗ Retry failed: ${e.message}`, "log-err");
    }
  };

  // ── History ──
  const deleteCase = async (caseId: string) => {
    if (!confirm(`Delete case ${caseId} and all associated data? This cannot be undone.`)) return;
    try {
      await API.deleteCase(caseId);
      if (activeCaseId === caseId) {
        setActiveCaseId(null);
        setResults(null);
        setView('upload');
      }
      await loadCases();
    } catch (err: any) {
      alert("Failed to delete case: " + err.message);
    }
  };

  const backToUpload = () => {
    stopPolling();
    sessionStorage.removeItem("currentCaseId");
    setView('upload');
    setResults(null);
    setStatusData(null);
    setCurrentCaseId(null);
    setActiveCaseId(null);
    loadCases();
  };

  if (authLoading) {
    return (
      <div className="ctd-root auth-root">
        <div className="auth-card"><p>Checking session…</p></div>
      </div>
    );
  }

  if (showAuth) {
    return <AuthScreen onAuthed={handleAuthed} />;
  }

  const needsAction = statusData?.needs_action || [];
  const activeDoc = results?.documents?.find(d => String(d.doc_id) === String(activeDocId));
  const chain = results?.title_chain?.chain || [];
  const titleChainStatus = results?.title_chain?.status;
  const titleStory = results?.title_chain?.source?.title_story || undefined;
  const verification = results?.verification || null;
  const caseInfo = results?.case;
  const allComplete = caseInfo ? COMPLETE_STATUSES.includes(caseInfo.status) : false;

  return (
    <div className="ctd-root">
      {/* Header */}
      <div className="header">
        <img src={clearTitleLogo} className="header-logo" alt="clearTitle" />
        <div>
          <p>Karnataka Property Title Verification</p>
          {auth && <p className="header-user">{auth.user.email}</p>}
        </div>
        <div className="health-dot">
          <div className={`dot${healthOk ? '' : ' red'}`}></div>
          <span>{healthText}</span>
          {auth ? (
            <button className="header-logout" title="Sign out" onClick={logout}><LogOut size={14} /></button>
          ) : (
            <button className="btn btn-primary header-signin" onClick={() => openAuth()}>
              <LogOut size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} /> Sign in
            </button>
          )}
        </div>
      </div>

      <div className="app-layout">
        {/* Sidebar */}
        {auth && (
          <div className={`sidebar${sidebarCollapsed ? ' collapsed' : ''}`}>
            <div className="sidebar-header"><List size={14} /> Case History</div>
            <div className="sidebar-list">
              {cases.length === 0 ? (
                <div className="sidebar-empty">No cases yet. Upload documents to get started.</div>
              ) : cases.map(c => (
                <div
                  key={c.id}
                  className={`sidebar-item${c.id === activeCaseId ? ' active' : ''}`}
                  onClick={() => loadResultsFor(c.id)}
                >
                  <div className="sidebar-item-header">
                    <span className="case-id">{c.id}</span>
                    <button
                      className="sidebar-delete-btn"
                      title="Delete case"
                      onClick={e => { e.stopPropagation(); deleteCase(c.id); }}
                    ><Trash2 size={14} /></button>
                  </div>
                  <div className="case-meta">
                    <span>{c.completed_docs}/{c.total_docs}</span>
                    <span className={`badge ${caseBadgeClass(c.status)}`}>{c.status}</span>
                    {verdictBadge(c.verdict)}
                  </div>
                  <div className="case-date">{fmtDate(c.created_at)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Main content */}
        <div className="main-content" onClick={() => {
          if (window.innerWidth <= 800 && !sidebarCollapsed) setSidebarCollapsed(true);
        }}>
          {view === 'upload' && (
            <div className="card">
              <div className="card-title"><FolderOpen size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} /> Section 1 — Uploaded Documents</div>

              {UPLOAD_SLOTS.map(slotCfg => {
                const slotFiles = files.filter(f => f.slot === slotCfg.id);
                const count = slotFiles.length;
                const limit = slotCfg.multiple ? Infinity : 1;
                return (
                  <div className={`upload-slot ${count > 0 ? 'has-files' : ''}`} key={slotCfg.id}>
                    <div className="upload-slot-head">
                      <span className="upload-slot-label">
                        {slotCfg.label}
                        {slotCfg.required && <span className="upload-slot-required">Required</span>}
                      </span>
                      <span className={`upload-slot-count ${count >= limit ? 'ok' : ''}`}>
                        {count}{slotCfg.multiple ? '' : '/1'}
                      </span>
                    </div>
                    <div className="upload-slot-sub">{slotCfg.desc}</div>
                    <div
                      className="upload-slot-zone"
                      onClick={() => document.getElementById(`slot-input-${slotCfg.id}`)?.click()}
                      onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }}
                      onDragLeave={e => e.currentTarget.classList.remove('drag-over')}
                      onDrop={e => {
                        e.preventDefault();
                        e.currentTarget.classList.remove('drag-over');
                        addFilesToSlot(slotCfg.id, Array.from(e.dataTransfer.files));
                      }}
                    >
                      <FileUp size={22} />
                      <span>Drop PDF here or click to add</span>
                    </div>
                    <input
                      type="file"
                      id={`slot-input-${slotCfg.id}`}
                      multiple={slotCfg.multiple}
                      accept=".pdf"
                      onChange={e => {
                        addFilesToSlot(slotCfg.id, Array.from(e.target.files || []));
                        e.target.value = "";
                      }}
                    />
                    {slotFiles.length > 0 && (
                      <div className="file-list">
                        {slotFiles.map((f, i) => {
                          const globalIndex = files.findIndex(x => x === f);
                          return (
                            <div className="file-item" key={`${f.file.name}-${f.file.size}`}>
                              <span className="file-icon"><FileText size={18} /></span>
                              <span className="file-name">{f.file.name}</span>
                              <span className="file-size">{(f.file.size / 1024).toFixed(1)} KB</span>
                              <span className="file-remove" title="Remove" onClick={() => removeFile(globalIndex)}><X size={14} /></span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="btn-row">
                <button className="btn btn-primary" disabled={slotCount('sale_deed') < 1 || slotCount('ec') < 1} onClick={startProcessing}>
                  <Play size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Verify Title
                </button>
                <button className="btn btn-secondary" onClick={clearFiles}><X size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Clear Files</button>
                <button className="btn btn-danger" style={{ marginLeft: 'auto' }} onClick={clearAllData}><Trash2 size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Clear All Data</button>
              </div>
            </div>
          )}

          {view === 'processing' && (
            <div className="card">
              <div className="card-title"><BarChart3 size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} /> Pipeline Running</div>
              <div className="progress-label">{progressLabel}</div>
              <div className="progress-bar-wrap">
                <div className="progress-bar" style={{ width: `${progressPct}%` }}></div>
              </div>
              <div className="log-box">
                {logs.length === 0 ? <span className="log-info">Pipeline started...</span> : (
                  logs.map((l, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <br />}
                      <span className={l.cls}>{l.text}</span>
                    </React.Fragment>
                  ))
                )}
              </div>
            </div>
          )}

          {view === 'results' && results && (
            !auth ? (
              <GuestReportPreview
                results={results}
                onSignIn={() => openAuth(currentCaseId || undefined)}
                onNewCase={backToUpload}
              />
            ) : (
            <>
              {/* Uploaded Docs & Extractions */}
              <div className="card">
                <div className="card-title">
                  <FolderOpen size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Uploaded Docs &amp; Extractions
                  <button className="btn btn-secondary" style={{ float: 'right' }} onClick={backToUpload}>
                    <ArrowRight size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> New Case
                  </button>
                </div>
                <div className="metrics-row">
                  <div className="metric-box">
                    <div className="val"><span className={`badge ${caseBadgeClass(caseInfo?.status || '')}`}>{caseInfo?.status || '—'}</span></div>
                    <div className="lbl">Case status</div>
                  </div>
                  <div className="metric-box"><div className="val">{results.documents.filter(d => d.status === 'structured').length}</div><div className="lbl">Structured</div></div>
                  <div className="metric-box"><div className="val">{results.documents.filter(d => d.status === 'failed' || d.status === 'classification_failed').length}</div><div className="lbl">Failed</div></div>
                  <div className="metric-box"><div className="val">{caseInfo?.total_docs ?? 0}</div><div className="lbl">Total docs</div></div>
                  <div className="metric-box"><div className="val">{verdictBadge(caseInfo?.verdict)}</div><div className="lbl">Verdict</div></div>
                </div>

                {results.documents.length > 0 ? (
                  <div className="doc-tabs">
                    {results.documents.map(d => (
                      <button
                        key={String(d.doc_id)}
                        className={`doc-tab ${d.status === 'structured' ? 'complete' : 'failed'} ${activeDocId === String(d.doc_id) ? 'active' : ''}`}
                        onClick={() => setActiveDocId(String(d.doc_id))}
                      >
                        {d.doc_id} {d.status !== 'structured' && '⚠'}
                      </button>
                    ))}
                  </div>
                ) : null}

                {activeDoc && activeDoc.status === 'structured' && auth && (
                  <DocPanel res={{ ...activeDoc, structured: activeDoc.structured || activeDoc.structured_json }} />
                )}
                {activeDoc && activeDoc.status === 'structured' && !auth && (
                  <div className="guest-lock">
                    <Lock size={22} />
                    <p><strong>{activeDoc.filename}</strong></p>
                    <p>Extracted fields are locked in guest mode. Sign in to view the full details for this {activeDoc.document_type || 'document'}.</p>
                    <button className="btn btn-primary" onClick={() => openAuth(currentCaseId || undefined)}>Sign in to unlock</button>
                  </div>
                )}
                {activeDoc && activeDoc.status !== 'structured' && (
                  <div className="vr-sheet-empty">
                    <AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                    {activeDoc.filename} — {activeDoc.error || activeDoc.status}
                  </div>
                )}

                {needsAction.length > 0 && (
                  <div style={{ marginTop: 16, padding: 16, background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 10 }}>
                    <strong style={{ color: '#b45309' }}><AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Document Requires Your Decision</strong>
                    {needsAction.map((d: any) => (
                      <div key={d.doc_id} style={{ marginTop: 12, padding: 12, background: 'var(--white)', borderRadius: 8, border: '1px solid var(--border)' }}>
                        <p style={{ fontSize: 14, marginBottom: 10 }}><strong>{d.filename}</strong> — document type not recognised</p>
                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                          <button className="btn btn-secondary" onClick={() => skipDoc(d.doc_id)}><CheckCircle2 size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Continue without this document</button>
                          <button className="btn btn-primary" onClick={() => document.getElementById(`replace-input-${d.doc_id}`)?.click()}><Upload size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Upload a replacement document</button>
                          <input
                            type="file"
                            id={`replace-input-${d.doc_id}`}
                            accept=".pdf"
                            style={{ display: 'none' }}
                            onChange={e => {
                              const f = e.target.files?.[0];
                              if (f) replaceDoc(d.doc_id, f);
                              e.target.value = "";
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {(statusData?.errors || []).length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <strong style={{ color: 'var(--red)' }}><AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Errors</strong>
                    <div style={{ marginTop: 8 }}>
                      {(statusData?.errors || []).map((e: any, i: number) => (
                        <div className="error-item" key={i}>
                          <strong>{e.doc_id}</strong> — Step: {e.step}<br />
                          <code style={{ fontSize: 11 }}>{e.error}</code>
                        </div>
                      ))}
                      {(statusData?.errors || []).some((e: any) => e.step !== "classify" || !e.action_required) && (
                        <div style={{ marginTop: 12 }}>
                          <button className="btn btn-primary" onClick={retryFailed}><RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Retry Failed</button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Section 2 — Title Chain */}
              <div className="card">
                <div className="card-title">
                  <Bot size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Title Chain Timeline
                </div>
                <ChainTimeline chain={chain} status={titleChainStatus} titleStory={titleStory} />
              </div>

              {/* Section 3 — Verification Results */}
              <div className="card">
                <div className="card-title">
                  <FlaskConical size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Verification Results
                  <button
                    className="btn btn-primary"
                    style={{ float: 'right' }}
                    disabled={!allComplete || analyzing}
                    onClick={runAnalysis}
                  >
                    <RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                    {analyzing ? 'Analyzing…' : 'Run / Re-run Verification'}
                  </button>
                </div>
                {verification ? (
                  <VerifyResults
                    verification={verification}
                    locked={!auth}
                    onUnlock={() => openAuth(currentCaseId || undefined)}
                  />
                ) : (
                  <div className="vr-sheet-empty">
                    Verification has not run yet. Click “Run / Re-run Verification” once all documents are structured.
                  </div>
                )}
              </div>
            </>
          )
          )}
        </div>
      </div>
    </div>
  );
}
