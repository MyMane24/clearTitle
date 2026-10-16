import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import './dashboard.css';
import clearTitleLogo from '../assets/clearTitle.png';
import {
  API, AuthResponse, AuthUser, CaseListItem, CaseResults, HealthStatus,
  StatusResponse, TitleChainEntry, getToken, setToken,
} from '../api/backend';
import { DocSummary } from './utils';
import {
  AlertTriangle, ArrowLeft, Check, CheckCircle2,
  ChevronDown, ChevronUp, FileText, FileUp,
  GitMerge, Lock, LogIn, LogOut, MapPin, Menu,
  Play, Plus, RefreshCw, ShieldCheck, Sparkles, Download,
  Trash2, Upload, Users, X, XCircle, ScrollText,
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

function docStageInfo(docStatus: string): { label: string; pct: number; state: 'waiting' | 'active' | 'done' | 'failed' } {
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
  return map[docStatus] || { label: docStatus, pct: 0, state: 'waiting' };
}

function AiDots() {
  return <span className="ai-dots"><span /><span /><span /></span>;
}

function DocPipelineCard({ doc, compact }: { doc: { doc_id: string; original_name: string; status: string; document_type: string }; compact?: boolean }) {
  const info = docStageInfo(doc.status);
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
  const terminal = (status: string) => ['structured', 'skipped', 'failed', 'classification_failed'].includes(status);
  const allDone = files.length > 0 && files.every(f => terminal(f.status));
  const anyActive = files.some(f => f.status !== 'uploaded' && !terminal(f.status));
  const hasFiles = files.length > 0;

  const showAnalysis = allDone && hasFiles;
  const allComplete = allDone && statusData.status !== 'processing';
  const activeDocCount = files.filter(f => f.status !== 'uploaded' && !terminal(f.status)).length;
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

function verdictBadge(verdict?: string | null): React.ReactNode {
  if (!verdict) return null;
  const v = verdict.toUpperCase();
  const isClear = v === "VERIFIED" || v === "CLEAR_TITLE" || v.includes("CLEAR");
  const isAttention = v === "NOT_VERIFIED" || v === "REQUIRED_ATTENTION" || v === "ATTENTION_REQUIRED" || v.includes("ATTENTION") || v.includes("DISCREPANC") || v.includes("NOT_");

  if (isClear) {
    return (
      <span className="verdict-text verdict-clear">
        <ShieldCheck size={12} /> ClearTitle
      </span>
    );
  }
  if (isAttention) {
    return (
      <span className="verdict-text verdict-attention">
        <AlertTriangle size={12} /> Attention Required
      </span>
    );
  }
  return <span className="verdict-text">{verdict}</span>;
}

function fmtDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString();
}
function chainDateMs(e: any): number | null {
  const d = e.execution_date || e.executed_date || e.registration_date || '';
  const t = Date.parse(d);
  return isNaN(t) ? null : t;
}

function normalizeParties(raw: any): any[] {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map(p => typeof p === 'string' ? { entity_name: p } : p);
  }
  if (typeof raw === 'string') return [{ entity_name: raw }];
  return [raw];
}

function sortChain(chain: any[]): any[] {
  return [...chain].sort((a, b) => {
    const idxA = a.sequence ?? a.transaction_index ?? (a.tx_id ? parseInt(String(a.tx_id).replace(/\D/g, '')) : 0);
    const idxB = b.sequence ?? b.transaction_index ?? (b.tx_id ? parseInt(String(b.tx_id).replace(/\D/g, '')) : 0);
    if (idxA !== idxB) return idxA - idxB;
    const da = chainDateMs(a), db = chainDateMs(b);
    if (da != null && db != null && da !== db) return da - db;
    return 0;
  });
}

const UPLOAD_SLOTS: { id: UploadSlot; label: string; desc: string; required: boolean; multiple?: boolean }[] = [
  { id: 'sale_deed', label: 'Sale Deed', desc: 'The current sale deed conveying title to the buyer.', required: true },
  { id: 'ec', label: 'Encumbrance Certificate (EC)', desc: 'The EC ledger covering the search period.', required: true },
  { id: 'additional', label: 'Additional Documents', desc: 'RTC, Khata, Mutation, prior deeds — optional.', required: false, multiple: true },
];

function parsePartyIdentity(raw: string): { name: string; rep: string; addr: string } {
  const out = { name: '', rep: '', addr: '' };
  if (!raw) return out;
  let s = raw.trim();

  const addrMatch = s.match(/(?:,\s*)?(?:r\/o|r\.o\.|residing at|resident of|at)\s+([\s\S]+)$/i);
  if (addrMatch && addrMatch[1].trim()) {
    out.addr = addrMatch[1].trim().replace(/,+$/, '');
    s = s.slice(0, addrMatch.index).trim().replace(/,+$/, '');
  }

  const repMatch = s.match(
    /(?:,\s*)?(rep(?:resented)?(?:'|’)?d?\s+by\s+(?:his|her|their)?\s*)(gpa|general power of attorney|power of attorney|poa|attorney)?[\s/]*holder?\s*([\s\S]+)$/i
  );
  if (repMatch && repMatch[3].trim()) {
    const hasGPA = !!repMatch[2];
    const rname = repMatch[3].trim().replace(/,+$/, '');
    out.rep = (hasGPA ? 'Rep by GPA ' : 'Rep by ') + rname;
    s = s.slice(0, repMatch.index).trim().replace(/,+$/, '');
  } else {
    const guardMatch = s.match(/(?:,\s*)?((?:legal\s+)?guardian)\s+of\s+([\s\S]+)$/i);
    if (guardMatch && guardMatch[2].trim()) {
      const role = guardMatch[1][0].toUpperCase() + guardMatch[1].slice(1);
      out.rep = role + ' of ' + guardMatch[2].split(',')[0].trim();
      s = s.slice(0, guardMatch.index).trim().replace(/,+$/, '');
    }
  }

  out.name = s
    .replace(/(?:,\s*)?(?:s\/o|d\/o|w\/o|son of|daughter of|wife of)\s+[^,\s]+/gi, '')
    .replace(/\s+/g, ' ')
    .replace(/(\s+)(\w+)\s*\2$/i, '$1$2')
    .replace(/^,|,\s*$/g, '')
    .trim();
  return out;
}

function PartyRow({ p }: { p: any }) {
  const raw = typeof p === 'string' ? p : p?.entity_name || '';
  const parsed = parsePartyIdentity(raw);
  const rep = (p && typeof p === 'object' && p.represented_by) || parsed.rep || null;
  const addr = (p && typeof p === 'object' && p.address) || parsed.addr || null;
  const name = parsed.name || raw || '—';
  return (
    <div className="chain-party">
      <p className="chain-party-name" title={raw || name}>{name}</p>
      {rep && <p className="chain-party-rep">{rep}</p>}
      {addr && <p className="chain-party-addr">{addr}</p>}
    </div>
  );
}

const ADVISORY_ROLES = new Set(['DIVERGENT_BRANCH', 'ENCUMBRANCE', 'SUBSEQUENT_TRANSFER']);

function chainTagCls(e: TitleChainEntry): string {
  switch (e.chain_role || '') {
    case 'THE_SD':
    case 'SUBSEQUENT_TRANSFER': return 'orange';
    case 'DIVERGENT_BRANCH': return 'amber';
    case 'PREDECESSOR_TITLE': return 'indigo';
    default: return 'slate';
  }
}

function chainPropertyDescription(e: TitleChainEntry): string {
  if (e.schedule_property) return e.schedule_property;
  if (e.property_location) return e.property_location;
  const pd = e.property_details;
  if (pd && typeof pd === 'object') {
    if (pd.description) return pd.description;
    const plot = pd.plot_no || pd.pid_no || pd.cts_no || pd.survey_number;
    if (plot) return String(plot);
  }
  return e.property_identity || '';
}

function chainSurveyIdentity(e: TitleChainEntry): string {
  if (e.survey_number || e.plot_number || e.site_flat_number) {
    return [e.survey_number, e.plot_number, e.site_flat_number].filter(Boolean).join(' / ');
  }
  const pd = e.property_details;
  if (e.property_identity) return e.property_identity;
  if (pd && typeof pd === 'object') {
    const plot = pd.plot_no || pd.cts_no || pd.survey_number || pd.pid_no;
    if (plot) return String(plot);
  }
  return '';
}

function chainConsideration(e: TitleChainEntry): string {
  if (e.consideration != null && e.consideration !== '') return String(e.consideration);
  const f = e.financials;
  const v = f && typeof f === 'object' ? f.consideration_amount : (typeof f === 'string' ? f : null);
  if (v == null || v === '') return '';
  if (typeof v === 'number') return '₹ ' + v.toLocaleString('en-IN');
  return String(v);
}

function chainMarketValue(e: TitleChainEntry): string {
  if (e.market_value != null && e.market_value !== '') return String(e.market_value);
  const f = e.financials;
  const v = f && typeof f === 'object' ? f.market_value : null;
  if (v == null || v === '') return '';
  if (typeof v === 'number') return '₹ ' + v.toLocaleString('en-IN');
  return String(v);
}

function fmtChainDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function ChainTimeline({ chain }: {
  chain: TitleChainEntry[];
}) {
  if (!chain || chain.length === 0) {
    return (
      <div className="vr-sheet-empty warn">
        No title chain entries are available yet.
      </div>
    );
  }

  const sorted = sortChain(chain);

  return (
    <div className="chain-tree">
      <section className="chain-nodes">
        <div className="chain-spine-v" />
        {sorted.map((e: any, i: number) => {
          const isLast = i === sorted.length - 1;
          const isAgreement = !!e.is_agreement_to_sell;
          const rawVendors = e.parties?.vendors || e.vendors || [];
          const rawPurchasers = e.parties?.purchasers || e.purchasers || [];
          const vendors = normalizeParties(rawVendors);
          const purchasers = normalizeParties(rawPurchasers);
          const execDate = e.execution_date || e.executed_date || e.registration_date;
          const regRef = e.registration_reference || e.registration_number;
          const typeKey = String(e.transaction_type || '').toUpperCase();
          const docType = e.document_type || e.transaction_type || 'Transaction';
          const leftPartyLabel = typeKey === 'SALE' ? 'VENDORS (SELLER)'
            : typeKey === 'GIFT' ? 'DONORS'
            : typeKey === 'MORTGAGE' ? 'BORROWERS / MORTGAGORS'
            : typeKey === 'RELEASE' || typeKey === 'RELEASE_OF_MORTGAGE' ? 'RELEASING PARTY'
            : typeKey === 'PARTITION' ? 'CO-OWNERS / PARTIES'
            : 'PARTIES (VENDORS FIELD)';
          const rightPartyLabel = typeKey === 'SALE' ? 'PURCHASERS (BUYER)'
            : typeKey === 'GIFT' ? 'DONEES'
            : typeKey === 'MORTGAGE' ? 'LENDER / MORTGAGEE'
            : typeKey === 'RELEASE' || typeKey === 'RELEASE_OF_MORTGAGE' ? 'RELEASE BENEFICIARY'
            : typeKey === 'PARTITION' ? 'ALLOTTED PARTIES'
            : 'PARTIES (PURCHASERS FIELD)';
          const entryIdx = e.sequence ?? e.transaction_index ?? (e.tx_id ? e.tx_id.replace(/^T/, '') : null);
          const schedule = chainPropertyDescription(e);
          const survey = chainSurveyIdentity(e);
          const consideration = chainConsideration(e);
          const marketValue = chainMarketValue(e);
          const isAdvisory = ADVISORY_ROLES.has(e.chain_role || '');
          const uncertainty = (e.uncertainty || []).join('; ');
          const scheduleLong = !!schedule && schedule.length > 40;
          const portion = e.conveyed_portion || e.portion || null;
          const portionLong = !!portion && portion.length > 40;
          const tagCls = chainTagCls(e);
          return (
            <div key={`${e.transaction_index ?? 'n'}-${i}`} className={`chain-node${isLast ? ' last' : ''}`}>
              <div className={`chain-node-tag tag-${tagCls}`}>
                {String(i + 1).padStart(2, '0')}
              </div>
              <div className="chain-node-body">
                <div className="chain-node-meta">
                  <div>
                    <span className="chain-node-label">DOCUMENT TYPE</span>
                    <p className="chain-node-value doc">
                      {docType}
                      {entryIdx != null && (
                        <span className={`chain-entry-badge badge-${tagCls}`}>ENTRY #{entryIdx}</span>
                      )}
                    </p>
                    {e.transaction_type && e.transaction_type !== docType && (
                      <p className="chain-node-classification">Transaction class: {e.transaction_type}</p>
                    )}
                  </div>
                  {execDate && (
                    <div className="chain-meta-right">
                      <span className="chain-node-label">EXECUTED DATE</span>
                      <p className="chain-node-value mono">{fmtChainDate(execDate)}</p>
                    </div>
                  )}
                  {regRef && (
                    <div className="chain-meta-right">
                      <span className="chain-node-label">REGISTRATION NO</span>
                      <p className="chain-node-value reg">{regRef}</p>
                    </div>
                  )}
                </div>

                <div className="chain-node-sections">
                  <div className="chain-node-section">
                    <div className="chain-node-section-head">
                      <Users size={20} className="chain-section-icon" />
                      <span>Parties</span>
                    </div>
                    <div className="chain-party-grid">
                      <div>
                        <span className="chain-node-label">{isAgreement ? 'EXECUTANT' : leftPartyLabel}</span>
                        {vendors.length ? vendors.map((v, vi) => <PartyRow key={vi} p={v} />) : <div className="chain-party-none">No party listed</div>}
                      </div>
                      <div>
                        <span className="chain-node-label">{isAgreement ? 'CLAIMANT' : rightPartyLabel}</span>
                        {purchasers.length ? purchasers.map((p, pi) => <PartyRow key={pi} p={p} />) : <div className="chain-party-none">No party listed</div>}
                      </div>
                    </div>
                  </div>

                  <div className="chain-node-section alt">
                    <div className="chain-node-section-head">
                      <MapPin size={20} className="chain-section-icon" />
                      <span>Property &amp; Consideration</span>
                    </div>
                    <div className="chain-prop-grid">
                      {survey && (
                        <div>
                          <span className="chain-node-label">SURVEY NO / PLOT</span>
                          <p className="chain-node-value">{survey}</p>
                        </div>
                      )}
                      {marketValue && (
                        <div>
                          <span className="chain-node-label">MARKET VALUE</span>
                          <p className="chain-node-value mono-bold">{marketValue}</p>
                        </div>
                      )}
                      {consideration && (
                        <div>
                          <span className="chain-node-label">CONSIDERATION AMOUNT</span>
                          <p className="chain-node-value mono-bold">{consideration}</p>
                        </div>
                      )}
                      {e.property_location && (
                        <div>
                          <span className="chain-node-label">LOCATION</span>
                          <p className="chain-node-value">{e.property_location}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {!!e.source_doc_ids?.length && (
                  <p className="chain-node-source">Source documents: {e.source_doc_ids.join(', ')}</p>
                )}
                {e.inferred && <p className="chain-node-source chain-node-inferred">Inferred from recital; original document not supplied.</p>}

                <ChainPropertyDropdown
                  schedule={schedule}
                  scheduleLong={scheduleLong}
                  portion={portion}
                  portionLong={portionLong}
                  isAdvisory={isAdvisory}
                  explanation={e.explanation || null}
                  uncertainty={uncertainty || null}
                />
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}

function ChainPropertyDropdown({ schedule, scheduleLong, portion, portionLong, isAdvisory, explanation, uncertainty }: {
  schedule: string | null;
  scheduleLong: boolean;
  portion: string | null;
  portionLong: boolean;
  isAdvisory: boolean;
  explanation: string | null;
  uncertainty: string | null;
}) {
  const [openField, setOpenField] = useState<string | null>(null);
  const hasSchedule = !!schedule;
  const hasPortion = !!portion;
  const hasAdvisory = isAdvisory && !!explanation;
  const hasUncertainty = !!uncertainty;
  if (!hasSchedule && !hasPortion && !hasAdvisory && !hasUncertainty) return null;

  const toggle = (field: string) => setOpenField(prev => prev === field ? null : field);

  return (
    <div className="chain-prop-inline">
      <div className="chain-prop-labels-row">
        {hasSchedule && (
          <button className="chain-prop-text-btn" onClick={() => toggle('schedule')}>
            <span className="chain-node-label">SCHEDULE PROPERTY</span>
            {openField === 'schedule' ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
        {hasPortion && (
          <button className="chain-prop-text-btn" onClick={() => toggle('portion')}>
            <span className="chain-node-label">CONVEYED PORTION</span>
            {openField === 'portion' ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
        {hasAdvisory && (
          <button className="chain-prop-text-btn chain-prop-text-btn-alert" onClick={() => toggle('advisory')}>
            <AlertTriangle size={12} className="chain-alert-icon" />
            <span className="chain-node-label">TITLE EXPOSURE IDENTIFIED</span>
            {openField === 'advisory' ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
        {hasUncertainty && (
          <button className="chain-prop-text-btn" onClick={() => toggle('uncertainty')}>
            <span className="chain-node-label">UNCERTAINTY / NOTES</span>
            {openField === 'uncertainty' ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
      </div>
      {openField === 'schedule' && schedule && (
        <div className="chain-prop-inline-content">
          <p className={scheduleLong ? 'chain-prop-wide-value' : 'chain-node-value'}>{schedule}</p>
        </div>
      )}
      {openField === 'portion' && portion && (
        <div className="chain-prop-inline-content">
          <p className="chain-node-value amber">{portion}</p>
        </div>
      )}
      {openField === 'advisory' && explanation && (
        <div className="chain-prop-inline-content">
          <p className="chain-alert-inline">{explanation}</p>
        </div>
      )}
      {openField === 'uncertainty' && uncertainty && (
        <div className="chain-prop-inline-content">
          <p className="chain-node-value">{uncertainty}</p>
        </div>
      )}
    </div>
  );
}

function GuestReportPreview({ results, onSignIn }: {
  results: CaseResults;
  onSignIn: () => void;
}) {
  const sd = results.documents.find(d =>
    d.document_type === 'SALE_DEED' || d.structured?.document_type === 'SALE_DEED'
  );
  const s = sd?.structured || {};
  const vendors: any[] = s.parties?.vendors || [];
  const purchasers: any[] = s.parties?.purchasers || [];
  const ps = s.property_schedule || {};
  const caseInfo = results.case;
  const scheduleText = String(
    ps.full_schedule_description
      || [ps.cts_number, ps.survey_number].filter(Boolean).join(', ')
      || ''
  ).slice(0, 200);

  return (
    <div className="gp-shell">
      <div className="gp-header">
        <div className="gp-header-left">
          <span className="gp-pulse" />
          <span className="gp-case-id">CASE #{caseInfo?.case_id || '—'}</span>
        </div>
      </div>
      <div className="gp-content">
        <div className="gp-card">
          <div className="gp-card-head"><div className="gp-card-label"><span className="gp-card-label-text">PARTIES IDENTIFIED</span></div></div>
          <div className="gp-parties-grid">
            {vendors.length > 0 && vendors.map((v, i) => <div className="gp-party-cell" key={`v-${i}`}><span className="gp-party-role">VENDORS (SELLER)</span><p className="gp-party-name">{v.entity_name || '—'}</p>{v.address && <p className="gp-party-addr">{v.address}</p>}</div>)}
            {purchasers.length > 0 && purchasers.map((p, i) => <div className="gp-party-cell" key={`p-${i}`}><span className="gp-party-role">PURCHASERS (BUYER)</span><p className="gp-party-name">{p.entity_name || '—'}</p>{p.address && <p className="gp-party-addr">{p.address}</p>}</div>)}
          </div>
        </div>
        {(ps.survey_number || ps.plot_number || ps.project_name || ps.floor_location || ps.dimensions || ps.super_built_up_area) && (
          <div className="gp-card">
            <div className="gp-card-head"><div className="gp-card-label"><span className="gp-card-label-text">PROPERTY DETAILS</span></div>{ps.plot_number && <span className="gp-card-badge">PLOT NO. {ps.plot_number}</span>}</div>
            <div className="gp-props-grid">
              {ps.survey_number && <div className="gp-prop-cell"><span className="gp-prop-label">SURVEY</span><p className="gp-prop-val">{ps.survey_number}</p></div>}
              {ps.project_name && <div className="gp-prop-cell"><span className="gp-prop-label">LOCATION</span><p className="gp-prop-val">{ps.project_name}</p></div>}
              {(ps.floor_location || ps.dimensions || ps.super_built_up_area) && <div className="gp-prop-cell"><span className="gp-prop-label">STRUCTURE</span><p className="gp-prop-val gp-prop-truncate">{[ps.floor_location, ps.dimensions, ps.super_built_up_area].filter(Boolean).join(', ')}</p></div>}
            </div>
          </div>
        )}
        {scheduleText && <div className="gp-card gp-card-blurred"><span className="gp-blur-label">HISTORICAL TITLE DEVOLUTION &amp; ENCUMBRANCES</span><p className="gp-blur-text">{scheduleText}...</p></div>}
        <div className="gp-lock-overlay">
          <div className="gp-lock-box">
            <div className="gp-lock-icon-wrap"><Lock size={24} /></div>
            <div className="gp-lock-text"><h2 className="gp-lock-title">Full Due Diligence Findings Locked</h2><p className="gp-lock-sub">Authenticate your session to inspect the complete title chain, check prior share exposure alerts, and export title scrutiny sheets.</p></div>
            <button className="gp-lock-cta" onClick={onSignIn}><Lock size={14} /><span>Sign in to Unlock Full Findings</span></button>
            <div className="gp-lock-trust"><span>✓ Instant Access</span><span>•</span><span>✓ Zero Setup</span><span>•</span><span>✓ Scrutiny Ready</span></div>
          </div>
        </div>
      </div>
      <div className="gp-footer"><span>Protected by 256-Bit Cryptographic Vault</span><span>Forensic Title Scrutiny Session</span></div>
    </div>
  );
}
function agentStatusColor(rawStatus?: string | null): { bg: string; fg: string; bd: string } {
  const s = String(rawStatus || '').toUpperCase();
  if (s === 'CLEAR' || s === 'VERIFIED' || s === 'CLEAR_TITLE' || s === 'VERIFIED_WITH_AVAILABLE_EVIDENCE') {
    return { bg: '#ecfdf5', fg: '#047857', bd: '#a7f3d0' };
  }
  if (s === 'ATTENTION_REQUIRED' || s === 'NOT_VERIFIED' || s === 'FAILED' || s === 'DEFECT') {
    return { bg: '#fef2f2', fg: '#b91c1c', bd: '#fecaca' };
  }
  if (s === 'PARTIAL' || s === 'IN_PROGRESS' || s === 'PROCESSING' || s === 'PENDING' || s === 'PENDING_NOT_VERIFIED' || s === 'INCONCLUSIVE') {
    return { bg: '#fffbeb', fg: '#b45309', bd: '#fde68a' };
  }
  return { bg: '#f8fafc', fg: '#475569', bd: '#e2e8f0' };
}

export function AgentTransactionCard({ tx }: { tx: any }) {
  const [open, setOpen] = useState(false);
  const status = String(tx.status || 'UNVERIFIED').toUpperCase();
  const c = agentStatusColor(tx.status);
  const missing: any[] = tx.missing_documents || [];
  const findings: any[] = tx.findings || [];
  const rules: string[] = tx.rule_versions || [];
  const supporting: any[] = tx.supporting_evidence || [];
  const contradictory: any[] = tx.contradictory_evidence || [];
  const formatEvidence = (ref: any) => {
    if (!ref) return '';
    if (typeof ref !== 'object') return String(ref);
    return [ref.doc_id, ref.page && `page ${ref.page}`, ref.note, ref.passage].filter(Boolean).join(' — ');
  };
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 14, marginBottom: 12, background: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span className="font-mono" style={{ fontSize: 11, color: '#94a3b8', fontWeight: 700 }}>T{tx.index}</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#1e293b' }}>{tx.type || 'Transaction'}</span>
          {tx.date && <span style={{ fontSize: 12, color: '#64748b' }}>{tx.date}</span>}
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.04em', padding: '4px 10px', borderRadius: 999, background: c.bg, color: c.fg, border: `1px solid ${c.bd}` }}>
          {status.replace(/_/g, ' ')}
        </span>
      </div>
      {tx.parties && <div style={{ fontSize: 13, color: '#475569', marginTop: 8 }}><strong>Parties:</strong> {tx.parties}</div>}
      {tx.finding && <p style={{ fontSize: 13.5, color: '#334155', lineHeight: 1.7, margin: '8px 0 0' }}>{tx.finding}</p>}
      {missing.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 13, color: '#b45309' }}>
          <strong>Missing:</strong> {missing.map((m, i) => <span key={i}>{i > 0 ? ', ' : ''}{m.document_type || 'Document'}</span>)}
        </div>
      )}
      {(findings.length > 0 || rules.length > 0 || supporting.length > 0 || contradictory.length > 0 || tx.reasoning || tx.impact || tx.explanation || tx.unresolved?.length || tx.limitations?.length) && (
        <>
          <button onClick={() => setOpen(o => !o)} style={{ marginTop: 10, padding: 0, border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#2563eb' }}>
            {open ? 'Hide details' : 'View details'} <span style={{ fontSize: 10, display: 'inline-block', transform: open ? 'rotate(180deg)' : 'none' }}>▼</span>
          </button>
          {open && (
            <div style={{ marginTop: 10, borderTop: '1px solid #f1f5f9', paddingTop: 10 }}>
              {tx.reasoning && <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.7, margin: '0 0 10px' }}>{tx.reasoning}</p>}
              {tx.impact && <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.7, margin: '0 0 10px' }}><strong>Impact:</strong> {tx.impact}</p>}
              {tx.explanation && <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.7, margin: '0 0 10px' }}>{tx.explanation}</p>}
              {findings.map((finding, i) => (
                <div key={i} style={{ fontSize: 12.5, color: '#475569', marginBottom: 4 }}>
                  <strong>{finding.description || 'Finding'}</strong>
                  {finding.significance && <div>Significance: {finding.significance}</div>}
                  {finding.explanation && <div>{finding.explanation}</div>}
                  {finding.source_refs?.length > 0 && <div>Sources: {finding.source_refs.map(formatEvidence).filter(Boolean).join('; ')}</div>}
                </div>
              ))}
              {rules.length > 0 && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}><strong>Rules applied:</strong> {rules.join(', ')}</div>}
              {supporting.length > 0 && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}><strong>Supporting evidence:</strong> {supporting.map(formatEvidence).filter(Boolean).join('; ')}</div>}
              {contradictory.length > 0 && <div style={{ fontSize: 12, color: '#b45309', marginTop: 8 }}><strong>Contradictory evidence:</strong> {contradictory.map(formatEvidence).filter(Boolean).join('; ')}</div>}
              {!!tx.unresolved?.length && <div style={{ fontSize: 12, color: '#92400e', marginTop: 8 }}><strong>Unresolved:</strong> {tx.unresolved.join('; ')}</div>}
              {!!tx.limitations?.length && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}><strong>Limitations:</strong> {tx.limitations.join('; ')}</div>}
            </div>
          )}
        </>
      )}
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
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeReportTab, setActiveReportTab] = useState<'verification' | 'title-chain'>('verification');
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [titleStoryOpen, setTitleStoryOpen] = useState(false);
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

  // ── Auto-link guest case on login (no ?link= param) ──
  useEffect(() => {
    if (authLoading || !auth) return;
    const caseId = sessionStorage.getItem("currentCaseId");
    if (!caseId || searchParams.get('link')) return;
    API.link(caseId).catch(() => {});
  }, [auth, authLoading, searchParams]);

  const runAnalysisTask = async () => {
    if (!currentCaseId) return;
    setAnalyzing(true);
    const before = agent?.updated_at || null;
    try {
      await API.analyze(currentCaseId);
      addLog("Agent analysis queued", "log-info");
    } catch (e: any) {
      addLog(`✗ Re-run failed: ${e.message}`, "log-err");
      setAnalyzing(false);
      return;
    }

    const startedAt = Date.now();
    const POLL_MS = 3000;
    const finish = async (fresh: CaseResults | null, done: boolean) => {
      if (fresh) setResults(fresh);
      setAnalyzing(false);
      loadCases();
      addLog(
        done
          ? "✓ Results refreshed with latest output"
          : "⚠ Task still running — showing latest available results",
        done ? "log-ok" : "log-warn"
      );
    };
    const tick = async () => {
      let fresh: CaseResults | null = null;
      try {
        fresh = await API.getResults(currentCaseId);
      } catch (e: any) {
        addLog(`⚠ Checking results failed: ${e.message}`, "log-warn");
      }
      if (Date.now() - startedAt > ANALYSIS_WAIT_MS) {
        await finish(fresh, false);
        return;
      }
      const outcome = fresh?.agent;
      const done = !!outcome &&
        ['done', 'error', 'paused'].includes(outcome.status) &&
        outcome.updated_at && outcome.updated_at !== before;
      if (done) {
        await finish(fresh, true);
        return;
      }
      analysisTimerRef.current = window.setTimeout(tick, POLL_MS);
    };
    await tick();
  };

  // ── Results actions ──
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

const needsActionSource = statusData?.needs_action?.length ? statusData.needs_action : results?.needs_action || [];
const needsAction = needsActionSource.filter(
  (item: any, index: number, items: any[]) => items.findIndex((candidate: any) => candidate.doc_id === item.doc_id) === index,
);
const visibleErrors = (statusData?.errors || []).filter((error: any) => error.step !== 'classify');
  const activeDoc = results?.documents?.find(d => String(d.doc_id) === String(activeDocId));
  const agent = results?.agent;
  const caseInfo = results?.case;
  const allComplete = caseInfo ? COMPLETE_STATUSES.includes(caseInfo.status) : false;

  // Transform agent.transactions to UI format
  const rawTx = agent?.transactions || [];
  const agentTx = rawTx.map((t: any, i: number) => ({
    ...t,
    index: t.sequence ?? t.tx_id?.replace('T', '') ?? i + 1,
    tx_id: t.tx_id,
    type: t.transaction_type || t.document_type || 'Transaction',
    date: t.executed_date || t.execution_date || t.registration_date || null,
    parties: (() => {
      const vList = (t.vendors || []).map((v: any) => typeof v === 'string' ? v : (v?.entity_name || '')).filter(Boolean);
      const pList = (t.purchasers || []).map((p: any) => typeof p === 'string' ? p : (p?.entity_name || '')).filter(Boolean);
      return (vList.join(', ') || '') + (vList.length && pList.length ? ' → ' : '') + (pList.join(', ') || '');
    })(),
    finding: t.conclusion || t.finding || t.reasoning || '',
    status: t.status || 'UNVERIFIED',
    reasoning: t.reasoning || '',
    impact: t.impact || '',
    findings: t.findings || [],
    rule_versions: t.rule_versions || [],
    supporting_evidence: t.supporting_evidence || [],
    contradictory_evidence: t.contradictory_evidence || [],
    missing_documents: t.missing_documents || [],
    explanation: '',
    unresolved: t.unresolved || [],
    limitations: t.limitations || [],
  }));
  const verifiedCount = rawTx.filter((t: any) =>
    String(t.status || '').toUpperCase() === 'VERIFIED_WITH_AVAILABLE_EVIDENCE'
  ).length;

  // Title chain data from agent
  const titleChain = agent?.title_chain;
  const chain = titleChain?.transactions || [];
  const sortedChain = sortChain(chain);
  const titleStory = titleChain?.title_story || '';
  const chainUnresolved = titleChain?.unresolved || [];
  const propertyIdentity = (agent?.property_identity || {}) as Record<string, unknown>;
  const identityEntries = Object.entries(propertyIdentity).filter(([, value]) => value != null && value !== '');

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
                      {verdictBadge(c.verdict)}
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
                      <span className="case-status-done"><CheckCircle2 size={11} style={{ verticalAlign: '-1px' }} /> Title Verification Done</span>
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
              <AIPipeline statusData={statusData || { status: 'processing', files: files.map((f, i) => ({ doc_id: `DOC_${String(i+1).padStart(3,'0')}`, original_name: f.file.name, status: 'uploaded', document_type: '' })) }} />
            </div>
          )}

          {view === 'results' && results && (
            <div className="report-main-wrap">
              {!auth ? (
                <GuestReportPreview
                  results={results}
                  onSignIn={() => openAuth(currentCaseId || undefined)}
                />
              ) : (
              <>
              {/* Action Required Banner (if any errors or unclassified docs) */}
              {(needsAction.length > 0 || visibleErrors.length > 0) && (
                <div className="card" style={{ marginBottom: 24 }}>
                  <div className="card-title">
                    <AlertTriangle size={16} style={{ verticalAlign: '-2px', marginRight: 8 }} /> Action Required
                  </div>
                  {needsAction.map((d: any) => (
                    <div key={d.doc_id} style={{ marginTop: 12, padding: 12, background: 'var(--white)', borderRadius: 8, border: '1px solid var(--border)' }}>
                      <p style={{ fontSize: 14, marginBottom: 10 }}>
                        <strong>{d.filename}</strong>
                        {d.document_type && <span> — detected: {String(d.document_type).replace(/_/g, ' ')}</span>}
                        <br />{d.message || 'This document needs review. Replace it with a property document or skip it.'}
                      </p>
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
                  {visibleErrors.length > 0 && (
                    <>
                      <div style={{ marginTop: 14 }}>
                        {visibleErrors.map((e: any, i: number) => (
                          <div className="error-item" key={i}>
                            <strong>{e.doc_id}</strong> — Step: {e.step}<br />
                            <code style={{ fontSize: 11 }}>{e.error}</code>
                          </div>
                        ))}
                      </div>
                      {visibleErrors.some((e: any) => e.step !== "classify" || !e.action_required) && (
                        <div style={{ marginTop: 12 }}>
                          <button className="btn btn-primary" onClick={retryFailed}><RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} /> Retry Failed</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* TAB 1: VERIFICATION REPORT */}
{activeReportTab === 'verification' && (
                <div className="tab-pane active">
                  {/* Verdict Section */}
                  <div className="verdict-banner">
                    <div className="vr-banner-meta">
                      <div className="vr-banner-meta-row">
                        <div className="vr-banner-meta-lines" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                          <div className="font-mono" style={{ fontSize: 11, color: '#94a3b8' }}>
                            CASE ID: <strong style={{ color: '#1e293b' }}>{currentCaseId || caseInfo?.case_id || '—'}</strong>
                          </div>
                          <div className="font-mono" style={{ fontSize: 11, color: '#94a3b8' }}>
                            {fmtDate(caseInfo?.created_at || new Date().toISOString())}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 14, margin: '14px 0 0' }}>
                        <span className="shimmer-effect" style={{
                          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                          width: 48, height: 48, borderRadius: '50%', flexShrink: 0,
                          background: String(agent?.overall_status || '').toUpperCase().includes('ATTENTION')
                            ? 'radial-gradient(circle at 30% 25%, #fee2e2, #fecaca 60%, #f87171)'
                            : 'radial-gradient(circle at 30% 25%, #d1fae5, #a7f3d0 60%, #34d399)',
                          boxShadow: String(agent?.overall_status || '').toUpperCase().includes('ATTENTION')
                            ? '0 0 18px rgba(239,68,68,.55), inset 0 0 8px rgba(255,255,255,.5)'
                            : '0 0 18px rgba(16,185,129,.55), inset 0 0 8px rgba(255,255,255,.5)',
                        }}>
                          {String(agent?.overall_status || '').toUpperCase().includes('ATTENTION')
                            ? <AlertTriangle size={28} style={{ color: '#dc2626', strokeWidth: 2.25 }} />
                            : <ShieldCheck size={28} style={{ color: '#047857', strokeWidth: 2.25 }} />}
                        </span>
                        <p className="vr-status-line" style={{ fontWeight: 800, letterSpacing: '.01em', lineHeight: 1.3, margin: 0, textTransform: 'uppercase',
                          color: '#1c1917' }}>
                          {agent?.status === "error"
                            ? "VERIFICATION COULD NOT BE COMPLETED, PLEASE RETRY"
                            : agent?.status === "running" || agent?.status === "idle"
                            ? "VERIFICATION IN PROGRESS…"
                            : agent?.overall_status
                            ? `TITLE ${agent.overall_status}`
                            : 'VERIFICATION NOT COMPLETED YET'}
                        </p>
                      </div>
                    </div>
                  </div>

                  {!!identityEntries.length && (
                    <section className="chain-summary-card" aria-label="Target property identity">
                      <div className="chain-summary-heading">
                        <span className="chain-summary-mark">ID</span>
                        <div>
                          <span className="chain-node-label">TARGET PROPERTY</span>
                          <h2>Property identity</h2>
                        </div>
                      </div>
                      <div className="chain-summary-grid">
                        {identityEntries.map(([key, value]) => (
                          <div className="chain-summary-field" key={key}>
                            <span className="chain-node-label">{key.replace(/_/g, ' ')}</span>
                            <span>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                  {!!chainUnresolved.length && (
                    <section className="chain-unresolved-card" aria-label="Unresolved title-chain questions">
                      <div className="chain-summary-heading">
                        <span className="chain-unresolved-mark"><AlertTriangle size={16} /></span>
                        <div>
                          <span className="chain-node-label">REQUIRES REVIEW</span>
                          <h2>Unresolved chain questions</h2>
                        </div>
                      </div>
                      <ul>
                        {chainUnresolved.map((item: string, i: number) => <li key={i}>{item}</li>)}
                      </ul>
                    </section>
                  )}

                  {/* Verification Pipeline Nodes */}
                  <div className="pipeline-container">
                    <div className="pl-controls-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 20, marginBottom: 24 }}>
                      <span className="font-mono" style={{ fontSize: 12, fontWeight: 800, color: '#1e293b' }}>
                        {verifiedCount}/{agent?.transactions?.length || 0} transactions verified
                      </span>
                      <button
                        className="vr-chain-link"
                        onClick={() => setActiveReportTab('title-chain')}
                        title="View the full chronological title chain for this case"
                        aria-label="Open Title Chain"
                      >
                        <GitMerge size={14} />
                        <span className="vr-chain-label">View Title Chain</span>
                        <span className="vr-chain-arrow">{'>'}</span>
                      </button>
                    </div>

                    <div className="pipeline-line"></div>

                    {/* Dynamic Pipeline Items */}
                    {agent?.transactions && agent.transactions.length > 0 ? (
                      agentTx.map((item: any, idx: number) => (
                        <AgentTransactionCard key={item.tx_id || idx} tx={item} />
                      ))
                    ) : (
                      <div className="vr-sheet-empty">
                        {agent?.status === "error"
                          ? "Verification did not complete due to a temporary issue. Please retry — no transactions were evaluated."
                          : "Verification has not run yet. No transactions have been evaluated."}
                      </div>
                    )}
                  </div>

                  {/* Detailed Report — headline + summary preview with expand */}
                  {(agent?.headline || agent?.report) && (
                    <div style={{ marginTop: 24, marginBottom: 28 }}>
                      {agent?.headline && (
                        <p style={{ fontSize: 16, fontWeight: 700, color: '#1e293b', margin: '0 0 8px', lineHeight: 1.55 }}>
                          {agent.headline}
                        </p>
                      )}
                      <p style={{
                        fontSize: 14, color: '#475569', lineHeight: 1.8, margin: 0, whiteSpace: 'pre-line',
                        overflow: 'hidden', display: '-webkit-box', WebkitBoxOrient: 'vertical',
                        WebkitLineClamp: summaryOpen ? undefined : 2,
                      }}>
{agent?.report}
                      </p>
                      <button
                        onClick={() => setSummaryOpen(o => !o)}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          marginTop: 10, padding: 0, border: 'none', background: 'transparent',
                          cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#2563eb',
                        }}
                      >
                        {summaryOpen ? 'Hide' : 'View Full Report'}
                        <span style={{ fontSize: 10, transition: 'transform .15s', transform: summaryOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}>▼</span>
                      </button>
                    </div>
                  )}

                  {!!agent?.findings?.length && (
                    <section style={{ margin: '0 0 24px', padding: 16, border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff' }}>
                      <h2 style={{ margin: '0 0 10px', fontSize: 14 }}>Case-level findings</h2>
                      <ul style={{ margin: 0, paddingLeft: 20, color: '#475569', lineHeight: 1.7 }}>
                        {agent.findings.map((finding, i) => <li key={i}>{finding}</li>)}
                      </ul>
                    </section>
                  )}
                  {agent?.recommendation && (
                    <section style={{ margin: '0 0 24px', padding: 16, border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff' }}>
                      <h2 style={{ margin: '0 0 8px', fontSize: 14 }}>Recommendation</h2>
                      <p style={{ margin: 0, color: '#475569', lineHeight: 1.7 }}>{agent.recommendation}</p>
                    </section>
                  )}

                  {/* Re-run Verification + Download Report Controls */}
                  <div className="pl-actions-row" style={{ marginTop: 24, marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
                    {agent?.status !== "error" && agent?.transactions?.length ? (
                    <button
                      className="btn btn-secondary"
                      disabled={!allComplete}
                      onClick={async () => {
                        const cid = currentCaseId || caseInfo?.case_id;
                        if (!cid) return;
                        try {
                          const headers: Record<string, string> = {};
                          const token = getToken();
                          if (token) headers['Authorization'] = `Bearer ${token}`;
                          const r = await fetch(`/api/results/${cid}/report/pdf`, { headers });
                          if (!r.ok) throw new Error('Failed to generate report');
                          const blob = await r.blob();
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement('a');
                          a.href = url;
                          a.download = `title-report-${cid}.pdf`;
                          document.body.appendChild(a);
                          a.click();
                          a.remove();
                          URL.revokeObjectURL(url);
                        } catch (e: any) {
                          alert('Could not generate report. ' + (e.message || ''));
                        }
                      }}
                    >
                      <Download size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                      Download Report
                    </button>
                    ) : null}
                    <button
                      className="btn btn-primary"
                      disabled={!allComplete || analyzing}
                      onClick={runAnalysisTask}
                      title="Resume the ClearTitle agent for this case"
                    >
                      <RefreshCw size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                      {analyzing ? 'Analyzing…' : 'Resume Analysis'}
                    </button>
                  </div>

                  {/* Document Extractions — bottom of verification report */}
                  <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 24, marginTop: 8 }}>
                    <div style={{ marginBottom: 16 }}>
                      <span className="font-mono" style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                        UPLOADED DOCUMENTS
                      </span>
                    </div>

                    {results.documents && results.documents.length > 0 ? (
                      <div>
                        {results.documents.map(d => {
                          const isExpanded = expandedDocId === String(d.doc_id);
                          return (
                            <div key={String(d.doc_id)} style={{ borderBottom: '1px solid #f1f5f9' }}>
                              <div className="doc-row">
                                {/* Col 1: Document name */}
                                <div className="doc-name">
                                  <FileText size={16} style={{ color: '#6b7280', flexShrink: 0 }} />
                                  <span style={{ fontSize: 13, fontWeight: 600, color: '#292524', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {d.filename || `DOC-${d.doc_id}`}
                                  </span>
                                </div>

                                {/* Col 2 & 3: Buttons */}
                                <div className="doc-actions">
                                  <button
                                    onClick={() => setExpandedDocId(isExpanded ? null : String(d.doc_id))}
                                    style={{
                                      fontSize: 12, fontWeight: 600, color: '#ea580c', background: 'none', border: '1px solid #fed7aa',
                                      borderRadius: 6, padding: '5px 12px', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
                                    }}
                                  >
                                    {isExpanded ? 'Hide Data' : 'View Structured Data'}
                                  </button>

                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const url = `/api/case/${currentCaseId || caseInfo?.case_id}/doc/${d.doc_id}/pdf`;
                                      const token = getToken();
                                      const headers: Record<string, string> = {};
                                      if (token) headers['Authorization'] = `Bearer ${token}`;
                                      fetch(url, { headers })
                                        .then(r => { if (!r.ok) throw new Error('Failed'); return r.blob(); })
                                        .then(blob => {
                                          const blobUrl = URL.createObjectURL(blob);
                                          window.open(blobUrl, '_blank');
                                        })
                                        .catch(() => alert('Could not load PDF. Please try again.'));
                                    }}
                                    style={{
                                      fontSize: 12, fontWeight: 600, color: '#2563eb', background: 'none', border: '1px solid #bfdbfe',
                                      borderRadius: 6, padding: '5px 12px', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0, textDecoration: 'none',
                                    }}
                                  >
                                    View Original PDF
                                  </button>
                                </div>
                              </div>

                              {/* Expanded Structured Data */}
                              {isExpanded && d.status === 'structured' && (
                                <div style={{ paddingBottom: 16 }}>
                                  <div className="doc-details-card">
                                    <DocSummary res={{ ...d, structured: d.structured || d.structured_json }} />
                                  </div>
                                </div>
                              )}

                              {isExpanded && d.status !== 'structured' && (
                                <div style={{ paddingBottom: 16 }}>
                                  <div className="doc-details-card" style={{ padding: 16 }}>
                                    <div className="vr-sheet-empty">
                                      <AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                                      {d.filename} — {d.error || d.status}
                                    </div>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="doc-details-card" style={{ padding: 24 }}>
                        <div className="vr-sheet-empty">No document extractions available yet.</div>
                      </div>
                    )}
                  </div>

                  {/* Required documents — generated by the LLM during title-chain build */}
{(() => {
                      const reqDocs = agent?.missing_documents;
                      if (!Array.isArray(reqDocs) || reqDocs.length === 0) return null;
                      return (
                        <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 24, marginTop: 24 }}>
                          <p style={{ color: '#1c1917', fontSize: 16, fontWeight: 500, marginBottom: 12, textAlign: 'left' }}>
                            The above results are generated only based on the documents uploaded, and the user
                            still needs to verify these documents to ensure clearTitle.
                          </p>
                          <div style={{ marginBottom: 8 }}>
                            <span className="font-mono" style={{ fontSize: 15, fontWeight: 700, color: '#111827', letterSpacing: '0.04em', textTransform: 'none' }}>
                              DOCUMENTS REQUIRED FOR COMPLETE VERIFICATION
                            </span>
                          </div>
                          <div style={{ overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                              <thead>
                                <tr>
                                  {['Transaction', 'Document', 'Required For', 'Reason'].map(h => (
                                    <th key={h} style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #e2e8f0', fontSize: 11, letterSpacing: '0.06em', color: '#6b7280', whiteSpace: 'nowrap' }}>
                                      {h}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {reqDocs.map((r, i) => (
                                  <tr key={`${i}-${r.document_type}`} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                    <td style={{ padding: '8px 10px', whiteSpace: 'nowrap', color: '#44403c', verticalAlign: 'top' }}>{r.for_transaction ? `T${r.for_transaction}` : '—'}</td>
                                    <td style={{ padding: '8px 10px', fontWeight: 600, color: '#292524', verticalAlign: 'top' }}>{r.document_type || '—'}</td>
                                    <td style={{ padding: '8px 10px', color: '#57534e', verticalAlign: 'top' }}>{r.for_transaction ? `Transaction T${r.for_transaction}` : '—'}</td>
                                    <td style={{ padding: '8px 10px', color: '#b45309', verticalAlign: 'top' }}>{r.reason || '—'}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      );
                    })()}
                </div>
              )}

              {/* TAB 2: TITLE CHAIN */}
              {activeReportTab === 'title-chain' && (
                <div className="tab-pane active">
                  <div className="chain-page-head">
                    <div className="chain-page-head-left">
                      <span className="chain-kicker">TITLE CHAIN • CASE {currentCaseId || caseInfo?.case_id || 'A722E83D'}</span>
                      <h1 className="chain-page-title">Chain of title</h1>
                      <p className="chain-page-sub">Chronological property devolution, ownership transitions, and adverse encumbrance tracking.</p>
                    </div>
                    <div className="chain-page-head-right">
                      <button className="chain-back-btn" onClick={() => setActiveReportTab('verification')}>
                        <ArrowLeft size={14} /> Back to Report
                      </button>
                      <span className="chain-milestones">
                        <span className="chain-milestones-dot" />
                        {sortedChain.length} TRANSACTIONS LINKED
                      </span>
                    </div>
                  </div>

                  {titleStory && (
                    <section className="chain-story-card">
                      <button
                        className="chain-story-toggle"
                        onClick={() => setTitleStoryOpen(open => !open)}
                        aria-expanded={titleStoryOpen}
                      >
                        <span>
                          <span className="chain-node-label">CHAIN SUMMARY</span>
                          <strong>Title-chain narrative</strong>
                        </span>
                        {titleStoryOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </button>
                      {titleStoryOpen && <p className="chain-story-text">{titleStory}</p>}
                    </section>
                  )}

                  {/* Connected Chronological Chain Nodes */}
                  <ChainTimeline chain={chain} />
                </div>
              )}

              {/* TAB 3: DOCS EXTRACTIONS */}
              </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
