import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import './dashboard.css';
import './results/chain.css';
import clearTitleLogo from '../assets/clearTitle.png';
import {
  API, AuthResponse, AuthUser, CaseListItem, CaseResults as CaseResultsData,
  HealthStatus, StatusResponse, getToken, setToken,
} from '../api/backend';
import { CaseResults } from './results/CaseResults';
import { documentErrorMessage, pipelineErrors } from './results/labels';
import {
  AlertTriangle, Check, CheckCircle2, FileText, FileUp,
  LogIn, LogOut, Menu, Play, Plus, RefreshCw, Sparkles,
  Trash2, Upload, X, XCircle, ScrollText,
} from 'lucide-react';

type View = 'upload' | 'processing' | 'results';

type UploadSlot = 'sale_deed' | 'ec' | 'additional';

interface SlotFile { file: File; slot: UploadSlot }

interface LogEntry { text: string; cls: string }

const COMPLETE_STATUSES = ['complete', 'completed', 'partial'];

const ANALYSIS_WAIT_MS = 8 * 60 * 1000;

function profileInitials(u: AuthUser): string {
  const name = (u.full_name || '').trim();
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean);
    const first = parts[0]?.[0] || '';
    const last = parts.length > 1 ? parts[parts.length - 1][0] || '' : '';
    return (first + last).toUpperCase() || '?';
  }
  const email = (u.email || '').trim();
  return email ? email.slice(0, 2).toUpperCase() : '?';
}

function logClass(line: string): string {
  if (line.includes("✗") || line.toLowerCase().includes("failed")) return "log-err";
  if (line.includes("✓") || line.toLowerCase().includes("complete")) return "log-ok";
  if (line.includes("Step") || line.includes("--")) return "log-info";
  if (line.includes("⚠")) return "log-warn";
  return "";
}

function docStageInfo(docStatus: string, error = ''): { label: string; pct: number; state: 'waiting' | 'active' | 'done' | 'failed' } {
  const map: Record<string, { label: string; pct: number; state: 'waiting' | 'active' | 'done' | 'failed' }> = {
    uploaded:            { label: 'Waiting to process...',   pct: 0,   state: 'waiting' },
    preprocessing:       { label: 'Reading and understanding...', pct: 15, state: 'active' },
    preprocessed:        { label: 'Reading and understanding...', pct: 25, state: 'active' },
    ocr_in_progress:     { label: 'Reading and understanding...', pct: 35, state: 'active' },
    ocr_done:            { label: 'Reading and understanding...', pct: 50, state: 'active' },
    merging:             { label: 'Reading and understanding...', pct: 60, state: 'active' },
    merged:              { label: 'Reading and understanding...', pct: 70, state: 'active' },
    classifying:         { label: 'Identifying key details...',  pct: 80, state: 'active' },
    classified:          { label: 'Identifying key details...',  pct: 85, state: 'active' },
    structuring:         { label: 'Extracting property information...', pct: 90, state: 'active' },
    structuring_done:    { label: 'Extracting property information...', pct: 95, state: 'active' },
    structured:          { label: 'Complete',              pct: 100, state: 'done' },
    skipped:             { label: 'Skipped',               pct: 100, state: 'done' },
    failed:              { label: 'Failed',                pct: 0,   state: 'failed' },
    classification_failed:{ label: 'Unrecognized document', pct: 0, state: 'failed' },
    pending_retry:       { label: 'Waiting to retry...',  pct: 0,   state: 'waiting' },
  };
  if (error.toLowerCase().includes('insufficient credits')) {
    return { label: 'Insufficient OCR credits', pct: 0, state: 'failed' };
  }
  return map[docStatus] || { label: docStatus, pct: 0, state: 'waiting' };
}

function AiDots() {
  return <span className="ai-dots"><span /><span /><span /></span>;
}

function DocPipelineCard({ doc, compact }: { doc: { doc_id: string; original_name: string; status: string; document_type: string; error?: string }; compact?: boolean }) {
  const info = docStageInfo(doc.status, doc.error);
  const cardClass = `doc-pipeline-card ${info.state === 'active' ? 'active' : info.state === 'done' ? 'done' : info.state === 'failed' ? 'failed' : ''}`;

  if (compact && info.state === 'done') {
    return (
      <div className="doc-pipeline-card done" style={{ padding: '10px 16px' }}>
        <div className="doc-pipeline-top" style={{ marginBottom: 0 }}>
          <div className="doc-pipeline-name">
            <Check size={14} style={{ color: '#059669', flexShrink: 0 }} />
            <span>{doc.original_name}</span>
          </div>
           <span className="doc-pipeline-status done">{info.label}</span>
        </div>
      </div>
    );
  }

  return (
      <div className={cardClass}>
      <div className="doc-pipeline-top">
        <div className="doc-pipeline-name">
          {info.state === 'done' ? (
            <Check size={14} style={{ color: '#059669', flexShrink: 0 }} />
          ) : info.state === 'failed' ? (
            <XCircle size={14} style={{ color: '#dc2626', flexShrink: 0 }} />
          ) : (
            <FileText size={14} style={{ color: info.state === 'active' ? '#ea580c' : '#6b7280', flexShrink: 0 }} />
          )}
          <span>{doc.original_name}</span>
        </div>
        <div className={`doc-pipeline-status ${info.state}`}>
          {info.state === 'active' && <AiDots />}
          {info.label}
        </div>
      </div>
      {info.state === 'failed' && doc.error && (
        <div className="doc-pipeline-error" role="alert">{documentErrorMessage(doc.error)}</div>
      )}
      {info.state !== 'done' && info.state !== 'failed' && (
        <div className="doc-pipeline-bar-wrap">
          <div className={`doc-pipeline-bar ${info.state}`} style={{ width: `${info.pct}%` }} />
        </div>
      )}
    </div>
  );
}
function AIPipeline({ statusData }: { statusData: StatusResponse }) {
  const files = statusData.files || [];
  const terminal = (file: typeof files[number]) =>
    ['structured', 'skipped', 'failed', 'classification_failed'].includes(file.status) ||
    Boolean(file.error?.toLowerCase().includes('insufficient credits'));
  const allDone = files.length > 0 && files.every(terminal);
  const anyActive = files.some(f => f.status !== 'uploaded' && !terminal(f));
  const hasFiles = files.length > 0;

  const showAnalysis = allDone && hasFiles;
  const allComplete = allDone && statusData.status !== 'processing';
  const activeDocCount = files.filter(f => f.status !== 'uploaded' && !terminal(f)).length;
  const doneDocCount = files.filter(f => f.status === 'structured' || f.status === 'skipped').length;

  return (
    <div className="ai-pipeline">
      {/* Phase header */}
      <div className="ai-pipeline-header">
        <div className="ai-icon">
          {allComplete ? <Check size={18} /> : <Sparkles size={18} />}
        </div>
        <div>
          <div className="ai-text">
            {allComplete
              ? 'Document processing complete'
              : anyActive
                ? <>AI is analyzing your documents<AiDots /></>
                : showAnalysis
                  ? 'Finishing document processing...'
                  : 'Preparing documents...'}
          </div>
          {hasFiles && (
            <div className="ai-pipeline-sub">
              {showAnalysis
                ? `${doneDocCount}/${files.length} documents processed`
                : anyActive
                  ? `${activeDocCount} document${activeDocCount > 1 ? 's' : ''} processing`
                  : `${files.length} document${files.length > 1 ? 's' : ''} queued`}
            </div>
          )}
        </div>
      </div>

      {/* Phase 1: Document cards */}
      {files.map(f => (
        <DocPipelineCard key={f.doc_id} doc={f} compact={showAnalysis} />
      ))}

    </div>
  );
}

function caseBadgeClass(status: string): string {
  if (status === "complete" || status === "completed") return "badge-green";
  if (status === "processing") return "badge-amber";
  if (status === "failed") return "badge-red";
  return "badge-blue";
}

function fmtDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString();
}
const UPLOAD_SLOTS: { id: UploadSlot; label: string; desc: string; required: boolean; multiple?: boolean }[] = [
  { id: 'sale_deed', label: 'Sale Deed', desc: 'The current sale deed conveying title to the buyer.', required: true },
  { id: 'ec', label: 'Encumbrance Certificate (EC)', desc: 'The EC ledger covering the search period.', required: true },
  { id: 'additional', label: 'Additional Documents', desc: 'RTC, Khata, Mutation, prior deeds — optional.', required: false, multiple: true },
];

export function VerificationDashboard() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [auth, setAuth] = useState<AuthResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(!!getToken());
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [files, setFiles] = useState<SlotFile[]>([]);
  const [currentCaseId, setCurrentCaseId] = useState<string | null>(null);
  const [view, setView] = useState<View>('upload');
  const [progressPct, setProgressPct] = useState(0);
  const [progressLabel, setProgressLabel] = useState('Initialising...');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [statusData, setStatusData] = useState<StatusResponse | null>(null);
  const [results, setResults] = useState<CaseResultsData | null>(null);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [chainBusy, setChainBusy] = useState(false);
  const [historyUploadBusy, setHistoryUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pipelineStartError, setPipelineStartError] = useState<string | null>(null);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const analysisTimerRef = useRef<number | null>(null);

  const addLog = useCallback((msg: string, cls = 'log-info') => {
    setLogs(prev => [...prev.slice(-200), { text: msg, cls }]);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // -- Auth bootstrap --
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

  // Clear any pending verification-polling timer on unmount.
  useEffect(() => () => {
    if (analysisTimerRef.current) clearTimeout(analysisTimerRef.current);
  }, []);

  // Sync activeDocId with results.documents
  useEffect(() => {
    if (results?.documents && results.documents.length > 0) {
      if (!activeDocId || !results.documents.some(d => String(d.doc_id) === String(activeDocId))) {
        setActiveDocId(String(results.documents[0].doc_id));
      }
    }
  }, [results]);

  // Close profile menu on outside click / Escape
  useEffect(() => {
    if (!profileOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setProfileOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [profileOpen]);

  const logout = () => {
    setToken(null);
    setAuth(null);
    setAuthLoading(false);
    stopPolling();
    sessionStorage.removeItem("currentCaseId");
    setResults(null);
    setStatusData(null);
    setCurrentCaseId(null);
    setView('upload');
  };

  const openAuth = (linkCaseId?: string) => {
    navigate(linkCaseId ? `/login?link=${encodeURIComponent(linkCaseId)}` : '/login');
  };

  // -- Health check --
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await API.health();
        if (!cancelled) setHealth(d);
      } catch {
        if (!cancelled) setHealth({ status: 'error', sarvam_key: false, openai_key: false, gemini_key: false, agent_provider: 'openai', agent_provider_key: false });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const healthOk = !!health && !!health.sarvam_key && !!health.openai_key && !!health.agent_provider_key;
  const healthText = !health ? "Checking..."
    : healthOk ? "API keys loaded"
      : `⚠ Missing: ${[
          !health.sarvam_key && "Sarvam",
          !health.openai_key && "OpenAI",
          !health.agent_provider_key && `${health.agent_provider} agent provider`,
        ].filter(Boolean).join(", ")}`;

  // -- Sidebar: load cases --
  const loadCases = useCallback(async () => {
    try {
      const data = await API.listCases();
      setCases(data.cases || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (auth) loadCases();
  }, [auth, loadCases]);

  // -- Resume last guest scan after a page refresh --
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

  // -- Files --
  const slotCount = (slot: UploadSlot) => files.filter(f => f.slot === slot).length;

  const addFilesToSlot = (slot: UploadSlot, incoming: File[]) => {
    const pdfs = incoming.filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) return;
    setUploadError(null);
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
    setUploadError(null);
  };

  const clearFiles = () => {
    setFiles([]);
    setCurrentCaseId(null);
    setUploadError(null);
  };

  // -- Processing --
  const startProcessing = async () => {
    if (slotCount('sale_deed') < 1 || slotCount('ec') < 1) return;
    const maxSizeMb = health?.max_upload_size_mb ?? 50;
    const oversizedFile = files.find(item => item.file.size > maxSizeMb * 1024 * 1024);
    if (oversizedFile) {
      setUploadError(`${oversizedFile.file.name} is larger than the ${maxSizeMb} MB upload limit. Reduce or split the PDF, then try again.`);
      return;
    }
    setUploadError(null);
    setPipelineStartError(null);
    setView('processing');
    updateProgress(5, "Uploading documents...");

    let uploadResp;
    try {
      uploadResp = await API.upload(
        files.map(f => f.file),
        files.map(f => f.slot),
      );
    } catch (e: any) {
      const message = e?.message || 'The upload could not be completed.';
      addLog(`✗ Upload failed: ${message}`, "log-err");
      setUploadError(message);
      setView('upload');
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
      const message = e?.message || 'The document pipeline could not be started.';
      addLog(`✗ Pipeline start failed: ${message}`, "log-err");
      setPipelineStartError(message);
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

      const isTerminal = COMPLETE_STATUSES.includes(s.status) || s.status === "failed";

      if (isTerminal) {
        stopPolling();
        updateProgress(100, "Pipeline complete");
        await showResults(caseId);
        loadCases();
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
      if (docs.length > 0) {
        setActiveDocId(String(docs[0].doc_id));
        // Finalization queues the chain build after processing; follow it until
        // the chain is saved (or the agent pauses for a history document).
        void pollTitleChain(caseId);
      }
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

  // -- Link a case after signing in via /login?link=<caseId> --
  useEffect(() => {
    const linkCase = searchParams.get('link');
    if (!linkCase || authLoading) return;
    if (!auth) {
      setSearchParams({}, { replace: true });
      return;
    }
    (async () => {
      try { await API.link(linkCase); } catch { /* ignore */ }
      loadResultsFor(linkCase);
      setSearchParams({}, { replace: true });
    })();
  }, [searchParams, auth, authLoading]);

  // -- Auto-link guest case on login (no ?link= param) --
  useEffect(() => {
    if (authLoading || !auth) return;
    const caseId = sessionStorage.getItem("currentCaseId");
    if (!caseId || searchParams.get('link')) return;
    API.link(caseId).catch(() => {});
  }, [auth, authLoading, searchParams]);

  // The chain build runs in a Celery worker; follow the case until it settles.
  const pollTitleChain = async (caseId: string) => {
    if (analysisTimerRef.current) window.clearTimeout(analysisTimerRef.current);
    const startedAt = Date.now();
    const tick = async () => {
      if (Date.now() - startedAt > ANALYSIS_WAIT_MS) {
        setChainBusy(false);
        addLog('Title-chain status timed out. Reload the case to check its progress.', 'log-warn');
        return;
      }
      try {
        const fresh = await API.getResults(caseId);
        setResults(fresh);
        if (['done', 'error', 'paused'].includes(String(fresh.agent?.status || ''))) {
          setChainBusy(false);
          loadCases();
          return;
        }
      } catch (error: any) {
        addLog(`Could not read title-chain status: ${error.message}. Retrying.`, 'log-warn');
      }
      analysisTimerRef.current = window.setTimeout(tick, 3000);
    };
    await tick();
  };

  const runChainBuild = async () => {
    if (!currentCaseId || chainBusy) return;
    setChainBusy(true);
    try {
      await API.buildChain(currentCaseId);
      addLog("Title-chain build queued", "log-info");
    } catch (e: any) {
      addLog(`✗ Build failed: ${e.message}`, "log-err");
      setChainBusy(false);
      return;
    }
    await pollTitleChain(currentCaseId);
  };

  // -- Results actions --
  const openPdf = (docId: string) => {
    const url = `/api/case/${currentCaseId}/doc/${docId}/pdf`;
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    fetch(url, { headers })
      .then(r => { if (!r.ok) throw new Error('Failed'); return r.blob(); })
      .then(blob => window.open(URL.createObjectURL(blob), '_blank'))
      .catch(() => alert('Could not load the PDF. Please try again.'));
  };

  const skipDoc = async (docId: string) => {
    if (!currentCaseId) return;
    try {
      await API.skipDoc(currentCaseId, docId);
      addLog(`Skipped ${docId} — finishing analysis…`, "log-warn");
      setView('processing');
      startPolling(currentCaseId);
    } catch (e: any) {
      addLog(`✗ Skip failed: ${e.message}`, "log-err");
    }
  };

  const retryPipelineStart = async () => {
    if (!currentCaseId) return;
    setPipelineStartError(null);
    try {
      await API.process(currentCaseId);
      startPolling(currentCaseId);
    } catch (e: any) {
      setPipelineStartError(e?.message || 'The document pipeline could not be started.');
    }
  };

  // The title chain is built from history records (EC, mutation, RTC). With
  // none uploaded the agent pauses before any transaction
  // exists, so these documents are added to the case itself.
  const uploadHistoryDocuments = async (files: File[]) => {
    if (!currentCaseId || !files.length) return;
    setHistoryUploadBusy(true);
    try {
      await API.uploadMore(currentCaseId, files);
      addLog(`Submitted ${files.length} document(s); OCR processing started. The title chain is built when processing finishes.`, "log-info");
      setView('processing');
      startPolling(currentCaseId);
    } catch (e: any) {
      addLog(`✗ Upload failed: ${e.message}`, "log-err");
    } finally {
      setHistoryUploadBusy(false);
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

  // -- History --
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

const needsActionSource = statusData?.needs_action?.length ? statusData.needs_action : results?.needs_action || [];
const needsAction = needsActionSource.filter(
  (item: any, index: number, items: any[]) => items.findIndex((candidate: any) => candidate.doc_id === item.doc_id) === index,
);
const visibleErrors = pipelineErrors(statusData, results);
  const agent = results?.agent;
  const caseInfo = results?.case;
  // Paused without a chain: the agent is waiting for a history document.
  const historyRequest = String(agent?.status || '').toLowerCase() === 'paused'
    ? String(agent?.next_action || '')
    : '';

  return (
    <div className="ctd-root">
      {/* Main Top Bar */}
      <header className={`header ${auth ? '' : 'header-guest'}`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {auth && (
            <button
              className="vr-sidebar-toggle"
              onClick={() => setSidebarCollapsed(c => !c)}
              title="Case history"
              aria-label="Toggle case history"
              aria-expanded={!sidebarCollapsed}
            >
              <Menu size={18} />
            </button>
          )}
          <Link to="/" className="ct-brand" style={{ textDecoration: 'none' }}>
            <img src={clearTitleLogo} alt="clearTitle" className="ct-brand-logo" />
          </Link>
        </div>

        <div className="ct-actions">
          {auth && (
            <>
              <button className="ct-btn-new-case" onClick={() => navigate('/ocr')} title="View raw OCR text for a case">
                <ScrollText size={16} />
                <span>OCR Text</span>
              </button>
              <button className="ct-btn-new-case" onClick={backToUpload} title="Start a new case">
                <Plus size={16} />
                <span>New Case</span>
              </button>
            </>
          )}
          {auth ? (
            <div className="ct-profile-wrap" ref={profileMenuRef}>
              <button
                className="ct-avatar"
                onClick={() => setProfileOpen(o => !o)}
                title={auth.user.email}
                aria-haspopup="menu"
                aria-expanded={profileOpen}
              >
                {profileInitials(auth.user)}
              </button>
              {profileOpen && (
                <div className="profile-menu" role="menu">
                  <div className="profile-menu-head">
                    <div className="profile-menu-avatar">{profileInitials(auth.user)}</div>
                    <div>
                      <div className="profile-menu-name">{auth.user.full_name || 'Guest'}</div>
                      <div className="profile-menu-email">{auth.user.email}</div>
                    </div>
                  </div>
                  <div className="profile-menu-divider" />
                  <button className="profile-menu-item" role="menuitem" onClick={logout}>
                    <LogOut size={15} />
                    <span>Sign out</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button className="ct-btn-login" onClick={() => openAuth()}>
              <LogIn size={15} />
              <span>Login</span>
            </button>
          )}
        </div>
      </header>

      <div className="app-layout">
        {/* Sidebar */}
        {auth && (
          <div className={`sidebar${sidebarCollapsed ? ' collapsed' : ''}`}>
            <div className="sidebar-header">Case History</div>
            <div className="sidebar-list">
              {cases.length === 0 ? (
                <div className="sidebar-empty">No cases yet. Upload documents to get started.</div>
              ) : cases.map(c => (
                <div
                  key={c.id}
                  className={`sidebar-item${c.id === activeCaseId ? ' active' : ''}`}
                  onClick={() => {
                    loadResultsFor(c.id);
                    if (window.innerWidth <= 800) setSidebarCollapsed(true);
                  }}
                >
                  <div className="sidebar-item-header">
                    <span className="case-id">{c.id}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <button
                        className="sidebar-delete-btn"
                        title="Delete case"
                        onClick={e => { e.stopPropagation(); deleteCase(c.id); }}
                      ><Trash2 size={14} /></button>
                    </div>
                  </div>
                  <div className="case-meta">
                    <span>{c.completed_docs}/{c.total_docs}</span>
                    {(c.status === 'complete' || c.status === 'completed') ? (
                      <span className="case-status-done"><CheckCircle2 size={11} style={{ verticalAlign: '-1px' }} /> Documents Processed</span>
                    ) : (
                      <span className={`badge ${caseBadgeClass(c.status)}`}>{c.status}</span>
                    )}
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
            <div className="card upload-card-full">
              <div className="upload-header-meta">
                <h1 className="upload-main-title">Upload documents</h1>
                <p className="upload-main-sub">We extract, cross-check and verify against Kaveri records. Nothing is shared.</p>
              </div>

              {uploadError && (
                <div role="alert" style={{ margin: '0 0 18px', padding: '12px 14px', border: '1px solid #fecaca', borderRadius: 10, background: '#fef2f2', color: '#991b1b', lineHeight: 1.5 }}>
                  <strong>Upload did not start.</strong> {uploadError}
                </div>
              )}

              <div className="upload-slots-grid">
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
              </div>

              <div className="btn-row">
                <button className="btn btn-secondary" onClick={clearFiles}>
                  <X size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Clear Files
                </button>
                <button className="btn btn-primary" disabled={slotCount('sale_deed') < 1 || slotCount('ec') < 1} onClick={startProcessing}>
                  <Play size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Verify Title
                </button>
              </div>
            </div>
          )}

          {view === 'processing' && (
            <div className="card plain">
              {pipelineStartError && (
                <div role="alert" style={{ marginBottom: 16, padding: '12px 14px', border: '1px solid #fecaca', borderRadius: 10, background: '#fef2f2', color: '#991b1b', lineHeight: 1.5 }}>
                  <strong>Processing has not started.</strong> {pipelineStartError}{' '}
                  <button className="btn btn-primary" onClick={() => void retryPipelineStart()}>Try starting again</button>
                </div>
              )}
              <AIPipeline statusData={statusData || { status: 'processing', files: files.map((f, i) => ({ doc_id: `DOC_${String(i+1).padStart(3,'0')}`, original_name: f.file.name, status: 'uploaded', document_type: '' })) }} />
            </div>
          )}

          {view === 'results' && results && (
            <div className="report-main-wrap">
              {/* Action Required Banner (if any errors or unclassified docs) */}
              {(needsAction.length > 0 || visibleErrors.length > 0) && (
                <div className="cr-notice">
                  <div className="cr-notice-title">
                    <AlertTriangle size={16} /> Action required
                  </div>
                  {needsAction.map((d: any) => (
                    <div key={d.doc_id} className="cr-notice-item">
                      <p>
                        <strong>{d.filename}</strong>
                        {d.document_type && <span> — detected: {String(d.document_type).replace(/_/g, ' ')}</span>}
                        <br />{d.message || 'This document needs review. Replace it with a property document or skip it.'}
                      </p>
                      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
                        <button className="btn btn-secondary" onClick={() => skipDoc(d.doc_id)}><CheckCircle2 size={14} /> Continue without this document</button>
                        <button className="btn btn-primary" onClick={() => document.getElementById(`replace-input-${d.doc_id}`)?.click()}><Upload size={14} /> Upload a replacement document</button>
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
                  {visibleErrors.length > 0 && (
                    <>
                      <div style={{ marginTop: 14 }}>
                        {visibleErrors.map((e: any, i: number) => (
                          <div className="error-item" key={i}>
                            <strong>{e.doc_id}</strong> — Step: {e.step}<br />
                            <code style={{ fontSize: 11 }}>{documentErrorMessage(e.error)}</code>
                          </div>
                        ))}
                      </div>
                      {visibleErrors.some((e: any) => e.step !== "classify" || !e.action_required) && (
                        <div style={{ marginTop: 12 }}>
                          <button className="btn btn-primary" onClick={retryFailed}><RefreshCw size={14} /> Retry failed</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {historyRequest && (
                <div className="cr-notice" style={{ marginBottom: 24 }}>
                  <p style={{ margin: '0 0 12px' }}>{historyRequest}</p>
                  <label className="btn btn-primary" style={{ cursor: historyUploadBusy ? 'default' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <Upload size={14} />
                    {historyUploadBusy ? 'Uploading…' : 'Upload documents'}
                    <input
                      type="file"
                      accept="application/pdf"
                      multiple
                      hidden
                      disabled={historyUploadBusy}
                      onChange={event => {
                        void uploadHistoryDocuments(Array.from(event.target.files || []));
                        event.target.value = '';
                      }}
                    />
                  </label>
                </div>
              )}

              <CaseResults
                caseId={currentCaseId || caseInfo?.case_id || ''}
                results={results}
                chainBusy={chainBusy}
                onRebuildChain={runChainBuild}
                onOpenPdf={openPdf}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
