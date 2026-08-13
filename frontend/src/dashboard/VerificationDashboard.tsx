import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import './dashboard.css';
import {
  API, AuthResponse, AuthUser, CaseListItem, CaseResults, HealthStatus,
  StatusResponse, TitleChainEntry, VerificationItem, getToken, setToken,
} from '../api/backend';
import { DocSummary } from './utils';
import clearTitleLogo from '../assets/clearTitle.png';
import {
  AlertTriangle, ArrowRight, BarChart3, Bot, CheckCircle2,
  FileText, FileUp, FlaskConical, FolderOpen, Lock, LogIn,
  LogOut, Menu, MinusCircle, Play, Plus, RefreshCw, ShieldCheck, Sparkles,
  Trash2, Upload, X, XCircle,
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

function partyInitials(name: string): string {
  const parts = name.replace(/^(Smt\.|Sri\.|Shri\.|Dr\.|Mr\.|Mrs\.|Ms\.|Late\s*)/i, "").split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] || "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] || "" : "";
  return (first + last).toUpperCase() || "?";
}

function partyList(list: any[]): string[] {
  return (list || [])
    .map(v => (typeof v === 'string' ? v : v?.entity_name || ''))
    .filter(Boolean);
}

function ChainCard({ e, tone }: { e: TitleChainEntry; tone: string }) {
  const vendors = partyList(e.parties?.vendors);
  const purchasers = partyList(e.parties?.purchasers);
  const financials = e.financials
    ? (typeof e.financials === 'string' ? e.financials : JSON.stringify(e.financials))
    : '';

  return (
    <div className={`chain-detail${tone ? ' tone-' + tone : ''}`}>
      <div className="chain-detail-hero">
        <div className="chain-detail-hero-top">
          <span className="chain-detail-type">{e.transaction_type || "Transaction"}</span>
          <span className="chain-detail-entry">Entry {e.transaction_index ?? "—"}</span>
        </div>
        {e.chain_role && (
          <span className={`chain-role role-${e.chain_role.toLowerCase()}`}>
            {CHAIN_ROLE_LABELS[e.chain_role] || e.chain_role}
          </span>
        )}
        {e.execution_date && <div className="chain-detail-date">{fmtChainDate(e.execution_date)}</div>}
      </div>

      <div className="chain-detail-body">
        <div className="chain-facts">
          {e.property_identity && (
            <div className="chain-fact">
              <span className="chain-fact-label">Property</span>
              <span className="chain-fact-value">{e.property_identity}</span>
            </div>
          )}
          {e.share_fraction && (
            <div className="chain-fact">
              <span className="chain-fact-label">Share</span>
              <span className="chain-fact-value">{e.share_fraction}</span>
            </div>
          )}
          {e.portion && (
            <div className="chain-fact">
              <span className="chain-fact-label">Portion</span>
              <span className="chain-fact-value">{e.portion}</span>
            </div>
          )}
          {e.registration_reference && (
            <div className="chain-fact">
              <span className="chain-fact-label">Registration</span>
              <span className="chain-fact-value">{e.registration_reference}</span>
            </div>
          )}
        </div>

        {(vendors.length > 0 || purchasers.length > 0) && (
          <div className="chain-transfer">
            <div className="chain-transfer-col">
              <span className="chain-transfer-label">From</span>
              {vendors.length ? vendors.map((v, i) => (
                <div className="chain-party" key={`v${i}`}>
                  <span className="chain-party-avatar">{partyInitials(v)}</span>
                  <span className="chain-party-name">{v}</span>
                </div>
              )) : <div className="chain-party-none">—</div>}
            </div>
            <div className="chain-transfer-arrow">→</div>
            <div className="chain-transfer-col">
              <span className="chain-transfer-label">To</span>
              {purchasers.length ? purchasers.map((p, i) => (
                <div className="chain-party" key={`p${i}`}>
                  <span className="chain-party-avatar">{partyInitials(p)}</span>
                  <span className="chain-party-name">{p}</span>
                </div>
              )) : <div className="chain-party-none">—</div>}
            </div>
          </div>
        )}

        {financials && (
          <div className="chain-block">
            <span className="chain-fact-label">Consideration / Financials</span>
            <div className="chain-block-value">{financials}</div>
          </div>
        )}

        {e.explanation && (
          <div className="chain-note">
            <Sparkles size={13} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{e.explanation}</span>
          </div>
        )}
      </div>

      {e.source && <div className="chain-source">source: {e.source}</div>}
    </div>
  );
}

function toneFor(e: TitleChainEntry): string {
  const role = e.chain_role || "";
  if (role === "THE_SD") return "sd";
  if (role === "PREDECESSOR_TITLE") return "predecessor";
  if (role === "SUBSEQUENT_TRANSFER") return "subsequent";
  if (role === "DIVERGENT_BRANCH") return "divergent";
  if (role === "ENCUMBRANCE") return "encumbrance";
  return "";
}

function fmtChainDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function ChainTimeline({ chain, status, titleStory }: {
  chain: TitleChainEntry[];
  status?: string;
  titleStory?: string;
}) {
  const [selected, setSelected] = useState<TitleChainEntry | null>(null);

  useEffect(() => { setSelected(null); }, [chain]);

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

  const cards: Array<{ entry: TitleChainEntry; label: string }> = [];
  const hasRoles = chain.some(e => e.chain_role);
  if (!hasRoles) {
    chain.forEach(e => cards.push({ entry: e, label: "" }));
  } else {
    const pushSection = (entries: TitleChainEntry[], label: string) =>
      entries.forEach(e => cards.push({ entry: e, label }));
    const sd = chain.find(e => e.chain_role === 'THE_SD');
    const predecessors = chain.filter(e => e.chain_role === 'PREDECESSOR_TITLE');
    const subsequent = chain.filter(e => e.chain_role === 'SUBSEQUENT_TRANSFER');
    const divergent = chain.filter(e => e.chain_role === 'DIVERGENT_BRANCH');
    const encumbrances = chain.filter(e => e.chain_role === 'ENCUMBRANCE');
    const others = chain.filter(e => !e.chain_role);
    if (sd) pushSection([sd], "This Sale Deed");
    pushSection(predecessors, "Chain of title before this Sale Deed");
    pushSection(subsequent, "Transfers after this Sale Deed (review)");
    pushSection(divergent, "Other transactions on this property (different portions)");
    pushSection(encumbrances, "Encumbrances — mortgages, leases, agreements");
    pushSection(others, "Other entries");
  }

  const dateOf = (e: TitleChainEntry) => {
    const d = new Date(e.execution_date || "");
    return isNaN(d.getTime()) ? null : d.getTime();
  };

  cards.sort((a, b) => {
    const da = dateOf(a.entry), db = dateOf(b.entry);
    if (da != null && db != null && da !== db) return da - db;
    return (a.entry.transaction_index ?? 0) - (b.entry.transaction_index ?? 0);
  });

  let lastLabel = "";

  return (
    <div className="chain-tree">
      {titleStory && <div className="chain-story">{titleStory}</div>}
      <div className="chain-timeline">
        {cards.map((c, i) => {
          const showLabel = c.label && c.label !== lastLabel;
          lastLabel = c.label;
          const e = c.entry;
          const tone = toneFor(e);
          return (
            <div key={`${e.transaction_index ?? 'n'}-${i}`}>
              {showLabel && <div className="chain-tl-label">{c.label}</div>}
              <div className="chain-item">
                <div className="chain-marker">
                  <span className={`chain-dot${tone ? ' ' + tone : ''}`}>{e.transaction_index ?? "•"}</span>
                  {i < cards.length - 1 && <span className="chain-line" />}
                </div>
                <div
                  className={`chain-card chain-tl-card${tone ? ' ' + tone : ''}`}
                  onClick={() => setSelected(e)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); setSelected(e); } }}
                >
                  <div className="chain-tl-top">
                    <span className="chain-tl-type">{e.transaction_type || "Transaction"}</span>
                    {e.chain_role && (
                      <span className={`chain-role role-${e.chain_role.toLowerCase()}`}>
                        {CHAIN_ROLE_LABELS[e.chain_role] || e.chain_role}
                      </span>
                    )}
                  </div>
                  <div className="chain-tl-meta">
                    {e.execution_date && <span className="chain-tl-date">{fmtChainDate(e.execution_date)}</span>}
                    {e.portion && <span className="chain-tl-portion">{e.portion}</span>}
                    {e.share_fraction && <span>{e.share_fraction}</span>}
                  </div>
                  {e.parties && (
                    <div className="chain-tl-parties">
                      <span>{partyNames(e.parties?.vendors)}</span>
                      <span className="chain-tl-arrow">→</span>
                      <span>{partyNames(e.parties?.purchasers)}</span>
                    </div>
                  )}
                  <span className="chain-tl-view">View details</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="chain-popup-backdrop" onClick={() => setSelected(null)}>
          <div className="chain-popup" role="dialog" aria-modal="true" aria-label="Transaction details" onClick={e => e.stopPropagation()}>
            <button className="chain-popup-close" aria-label="Close" onClick={() => setSelected(null)}>
              <X size={18} />
            </button>
            <ChainCard e={selected} tone={toneFor(selected)} />
          </div>
        </div>
      )}
    </div>
  );
}

function vrfStatusClass(s: string): string {
  const up = (s || "N/A").toUpperCase();
  if (up === "VERIFIED") return "ok";
  if (up === "NOT_VERIFIED") return "fail";
  return "na";
}

const FIELD_ORDER: RegExp[] = [
  /vendor/i,
  /purchaser|buyer/i,
  /survey|cts/i,
  /locality|project name/i,
  /execution|registration/i,
];

function fieldRank(name: string): number {
  const idx = FIELD_ORDER.findIndex(r => r.test(name));
  return idx === -1 ? 999 : idx;
}

const ABBR = /^(smt|sri|shri|dr|mr|mrs|ms|no|nos|fig|vs|etc|sd|ec|gpa|plot|st|rd|pvt|ltd)\.?$/i;

function splitSummary(text: string): string[] {
  const chunks = text.split(/\s+-\s+(?=[A-Z])/);
  const sentences: string[] = [];
  for (const chunk of chunks) {
    let buf = "";
    let prev = "";
    for (let i = 0; i < chunk.length; i++) {
      const ch = chunk[i];
      const next = chunk[i + 1] || "";
      const nextNext = chunk[i + 2] || "";
      const wordBefore = chunk.slice(0, i).split(/\s+/).pop() || "";
      const isSentenceEnd =
        (ch === "." || ch === "!" || ch === "?") &&
        next === " " &&
        /[a-z0-9)]/.test(prev) &&
        /[A-Z]/.test(nextNext) &&
        !ABBR.test(wordBefore);
      buf += ch;
      if (isSentenceEnd) {
        sentences.push(buf.trim());
        buf = "";
      }
      prev = ch;
    }
    if (buf.trim()) sentences.push(buf.trim());
  }
  return sentences
    .map(s => s.replace(/^[-•*]\s*/, "").trim())
    .filter(Boolean)
    .filter(s => !/^these include:?$/i.test(s) && !/^they include:?$/i.test(s));
}

function TypewriterBullets({ sentences, speed = 14 }: { sentences: string[]; speed?: number }) {
  const total = sentences.reduce((n, s) => n + s.length + 1, 0);
  const [count, setCount] = useState(0);
  useEffect(() => {
    setCount(0);
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setCount(i);
      if (i >= total) window.clearInterval(id);
    }, speed);
    return () => window.clearInterval(id);
  }, [total, speed]);

  let remaining = count;
  const items: Array<{ text: string; done: boolean }> = [];
  for (const s of sentences) {
    if (remaining >= s.length + 1) {
      items.push({ text: s, done: true });
      remaining -= s.length + 1;
    } else {
      items.push({ text: s.slice(0, Math.max(remaining, 0)), done: false });
      remaining = 0;
      break;
    }
  }

  return (
    <ul className="vrf-summary-list">
      {items.map((it, i) => (
        <li key={i} className={it.done ? "done" : "typing"}>
          {it.text}
          {!it.done && <span className="vrf-typing-caret" />}
        </li>
      ))}
    </ul>
  );
}

function FieldRow({ it, index }: { it: VerificationItem; index: number }) {
  const [open, setOpen] = useState(false);
  const s = (it.status || "N/A").toUpperCase();
  const cls = vrfStatusClass(s);
  const Icon = s === "VERIFIED" ? CheckCircle2 : s === "NOT_VERIFIED" ? XCircle : MinusCircle;

  return (
    <div
      className={`vrf-field ${cls}${open ? " open" : ""}`}
      style={{ animationDelay: `${Math.min(index * 55, 600)}ms` }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={() => setOpen(o => !o)}
      role="button"
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setOpen(o => !o);
        }
      }}
    >
      <span className="vrf-field-icon"><Icon size={16} /></span>
      <span className="vrf-field-name">{it.field || "—"}</span>
      <span className={`vrf-badge ${cls}`}>{s}</span>

      <div className="vrf-evidence">
        <div className="vrf-evidence-row">
          <span className="vrf-evidence-label">Sale Deed</span>
          <span className="vrf-evidence-value">{it.sd_value != null && it.sd_value !== "" ? String(it.sd_value) : "—"}</span>
        </div>
        <div className="vrf-evidence-row">
          <span className="vrf-evidence-label">EC Ledger</span>
          <span className="vrf-evidence-value">{it.ec_value != null && it.ec_value !== "" ? String(it.ec_value) : "—"}</span>
        </div>
        {it.notes ? (
          <div className="vrf-evidence-note">
            <span className="vrf-evidence-label">Conclusion</span>
            <span className="vrf-evidence-value">{it.notes}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function VerifyResults({ verification, locked, onUnlock }: {
  verification: NonNullable<CaseResults['verification']>;
  locked?: boolean;
  onUnlock?: () => void;
}) {
  const items: VerificationItem[] = verification.items || [];
  const orderedItems = [...items].sort((a, b) => fieldRank(a.field || "") - fieldRank(b.field || ""));
  const summary = verification.summary || {};
  const [summaryOpen, setSummaryOpen] = useState(false);
  const verdict = String(verification.verdict || summary.verdict || "N/A").toUpperCase();
  const heroCls = vrfStatusClass(verdict);
  const HeroIcon = verdict === "VERIFIED" ? ShieldCheck : verdict === "NOT_VERIFIED" ? XCircle : MinusCircle;
  const summarySentences = summary.overall_comment ? splitSummary(String(summary.overall_comment)) : [];

  return (
    <div className="vrf">
      <div className={`vrf-hero ${heroCls}`}>
        <div className="vrf-hero-icon"><HeroIcon size={34} /></div>
        <div className="vrf-hero-text">
          <span className="vrf-hero-label">Case Verdict</span>
          <span className="vrf-hero-verdict">{verdict}</span>
        </div>
      </div>

      {locked ? (
        <div className="guest-lock">
          <Lock size={22} />
          <p><strong>Field-by-field verification is locked.</strong></p>
          <p>Sign in to see the full verification for every field.</p>
          {onUnlock && <button className="btn btn-primary" onClick={onUnlock}>Sign in to unlock</button>}
        </div>
      ) : orderedItems.length === 0 ? (
        <div className="vr-sheet-empty">Verification has not run yet.</div>
      ) : (
        <div className="vrf-fields">
          {orderedItems.map((it, i) => <FieldRow key={i} it={it} index={i} />)}
        </div>
      )}

      {summarySentences.length > 0 && (
        <div className="vrf-summary">
          {summaryOpen ? (
            <div className="vrf-summary-body">
              <div className="vrf-summary-title"><Sparkles size={15} /> Summary</div>
              <TypewriterBullets sentences={summarySentences} />
            </div>
          ) : (
            <button className="vrf-summary-toggle" onClick={() => setSummaryOpen(true)}>
              <Sparkles size={15} /> View Summary
            </button>
          )}
        </div>
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
  const [results, setResults] = useState<CaseResults | null>(null);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const analysisTimerRef = useRef<number | null>(null);
  const analysisWaitStartRef = useRef<number>(0);

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

  // Clear any pending verification-polling timer on unmount.
  useEffect(() => () => {
    if (analysisTimerRef.current) clearTimeout(analysisTimerRef.current);
  }, []);

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
    analysisWaitStartRef.current = 0;
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
        // Docs are structured but the title-chain + verification pass is still
        // running in the background. Keep polling until it lands (or a cap).
        const waitForAnalysis = s.status === "complete" && !s.verification_status;
        if (waitForAnalysis) {
          if (!analysisWaitStartRef.current) analysisWaitStartRef.current = Date.now();
          if (Date.now() - analysisWaitStartRef.current < ANALYSIS_WAIT_MS) {
            updateProgress(100, "All documents structured – finishing title analysis…");
            return;
          }
        }
        stopPolling();
        analysisWaitStartRef.current = 0;
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

  // ── Link a case after signing in via /login?link=<caseId> ──
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

  const runAnalysis = async () => {
    if (!currentCaseId) return;
    setAnalyzing(true);
    const before = results?.verification?.updated_at || null;
    try {
      await API.analyze(currentCaseId);
      addLog("⏳ Title-chain + verification queued…", "log-info");
    } catch (e: any) {
      addLog(`✗ Analyze failed: ${e.message}`, "log-err");
      setAnalyzing(false);
      return;
    }

    const startedAt = Date.now();
    const POLL_MS = 3000;
    const tick = async () => {
      try {
        const fresh = await API.getResults(currentCaseId);
        const ver = fresh.verification;
        const done = !!ver &&
          ver.status &&
          (ver.status === 'complete' || ver.status === 'error' || ver.status === 'skipped') &&
          ver.updated_at && ver.updated_at !== before;
        if (done || Date.now() - startedAt > ANALYSIS_WAIT_MS) {
          setResults(fresh);
          setAnalyzing(false);
          addLog(
            done
              ? "✓ Verification refreshed with latest results"
              : "⚠ Verification still running — showing latest available results",
            done ? "log-ok" : "log-warn"
          );
          return;
        }
        analysisTimerRef.current = window.setTimeout(tick, POLL_MS);
      } catch (e: any) {
        addLog(`⚠ Checking results failed: ${e.message}`, "log-warn");
        analysisTimerRef.current = window.setTimeout(tick, POLL_MS);
      }
    };
    await tick();
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
        <Link to="/" className="header-logo-link" title="Back to home">
          <img src={clearTitleLogo} className="header-logo" alt="clearTitle" />
        </Link>
        <div>
          <p>Karnataka Property Title Verification</p>
        </div>
        <div className="header-actions">
          <div className="health-dot">
            <div className={`dot${healthOk ? '' : ' red'}`}></div>
            <span>{healthText}</span>
          </div>
          {auth && (
            <button className="btn btn-primary header-newcase" onClick={backToUpload} title="Start a new case">
              <Plus size={14} style={{ verticalAlign: '-2px', marginRight: 5 }} /> New Case
            </button>
          )}
          {auth ? (
            <div className="profile">
              <button className="profile-avatar" title="Account">
                {profileInitials(auth.user)}
              </button>
              <div className="profile-popup">
                <div className="profile-popup-name">{auth.user.full_name || 'User'}</div>
                <div className="profile-popup-email">{auth.user.email}</div>
                <button className="profile-logout" onClick={logout}>
                  <LogOut size={13} /> Sign out
                </button>
              </div>
            </div>
          ) : (
            <button className="btn btn-primary header-signin" onClick={() => openAuth()}>
              <LogIn size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} /> Sign in
            </button>
          )}
        </div>
      </div>

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
              {/* Action required — only shown when there are unresolved docs or errors */}
              {(needsAction.length > 0 || (statusData?.errors || []).length > 0) && (
                <div className="card">
                  <div className="card-title">
                    <AlertTriangle size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Action Required
                  </div>
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
                  {(statusData?.errors || []).length > 0 && (
                    <>
                      <div style={{ marginTop: 14 }}>
                        {(statusData?.errors || []).map((e: any, i: number) => (
                          <div className="error-item" key={i}>
                            <strong>{e.doc_id}</strong> — Step: {e.step}<br />
                            <code style={{ fontSize: 11 }}>{e.error}</code>
                          </div>
                        ))}
                      </div>
                      {(statusData?.errors || []).some((e: any) => e.step !== "classify" || !e.action_required) && (
                        <div style={{ marginTop: 12 }}>
                          <button className="btn btn-primary" onClick={retryFailed}><RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Retry Failed</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}



              {/* Verification Results */}
              <div className="card plain">
                <div className="card-title">
                  <FlaskConical size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Verification Results
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
                <div className="vrf-actions">
                  <button
                    className="btn btn-primary"
                    disabled={!allComplete || analyzing}
                    onClick={runAnalysis}
                  >
                    <RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                    {analyzing ? 'Analyzing…' : 'Run / Re-run Verification'}
                  </button>
                </div>
              </div>

              {/* Title Chain */}
              <div className="card plain">
                <div className="card-title">
                  <Bot size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Title Chain Timeline
                </div>
                <ChainTimeline chain={chain} status={titleChainStatus} titleStory={titleStory} />
              </div>

              {/* Uploaded Docs & Extractions */}
              <div className="card plain">
                <div className="card-title">
                  <FolderOpen size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} />Uploaded Docs &amp; Extractions
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

                {activeDoc && activeDoc.status === 'structured' && (
                  <DocSummary res={{ ...activeDoc, structured: activeDoc.structured || activeDoc.structured_json }} />
                )}
                {activeDoc && activeDoc.status !== 'structured' && (
                  <div className="vr-sheet-empty">
                    <AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                    {activeDoc.filename} — {activeDoc.error || activeDoc.status}
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
