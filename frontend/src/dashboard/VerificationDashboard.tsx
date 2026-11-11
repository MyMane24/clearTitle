import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import './dashboard.css';
import clearTitleLogo from '../assets/clearTitle.png';
import {
  API, AuthResponse, AuthUser, CaseFindingsResponse, CaseListItem, CaseResults, FinalReportBlocker,
  FinalReportState, HealthStatus, StatusResponse, TitleChainEntry, getToken, setToken,
} from '../api/backend';
import { DocSummary } from './utils';
import { PhaseAChainView } from './PhaseAResult';
import { requirementsForPausedTransaction } from './transactionResults';
import { TransactionResultCard } from './TransactionResultCard';
import { EvidenceRequestDialog } from './EvidenceRequestDialog';
import { FinalReportBlockersModal } from './FinalReportBlockersModal';
import { ConsolidatedFindings } from './ConsolidatedFindings';
import {
  AlertTriangle, ArrowLeft, Check, CheckCircle2,
  ChevronDown, ChevronUp, FileText, FileUp, FileWarning,
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

function documentErrorMessage(error = ''): string {
  if (error.toLowerCase().includes('insufficient credits')) {
    return 'OCR stopped: Sarvam has insufficient credits. Add credits to the Sarvam account, then retry this document.';
  }
  return error;
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
          const rawTransactionType = String(e.transaction_type || '');
          const transactionType = rawTransactionType.replace(/\s*\(EC entry; instrument not supplied\)/i, '');
          const typeKey = transactionType.toUpperCase();
          const docType = e.document_type || transactionType || 'Transaction';
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
                    </p>
                    {transactionType && transactionType !== docType && (
                      <p className="chain-node-classification">Transaction class: {transactionType}</p>
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
  const [finalReport, setFinalReport] = useState<FinalReportState | null>(null);
  const [caseFindings, setCaseFindings] = useState<CaseFindingsResponse | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportBlockers, setReportBlockers] = useState<FinalReportBlocker[] | null>(null);
  const [reportMessage, setReportMessage] = useState<string | null>(null);
  const [evidenceUploadBusy, setEvidenceUploadBusy] = useState(false);
  const [manualUploadTxId, setManualUploadTxId] = useState<string | null>(null);
  const [evidenceUploads, setEvidenceUploads] = useState<Record<number, File | undefined>>({});
  const [dismissedPauseKey, setDismissedPauseKey] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pipelineStartError, setPipelineStartError] = useState<string | null>(null);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeReportTab, setActiveReportTab] = useState<'verification' | 'title-chain'>('verification');
  const [titleStoryOpen, setTitleStoryOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const analysisTimerRef = useRef<number | null>(null);
  const uploadedForPausedTxRef = useRef<{ txId: string; updatedAt: string | null } | null>(null);

  // A new pause (next transaction, or the same one re-pausing after a resume)
  // starts with empty upload slots. Must live above the authLoading early
  // return so the hook count never changes between renders.
  const pausedTxKey = `${String(results?.agent?.paused_transaction || '')}:${String(results?.agent?.updated_at || '')}`;
  useEffect(() => { setEvidenceUploads({}); }, [pausedTxKey]);

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

  // A verification run can be resumed outside this page (for example after
  // requested evidence is processed). Refresh an open results view so a newly
  // paused transaction and its upload/skip dialog do not remain invisible.
  useEffect(() => {
    if (view === 'upload' || !currentCaseId) return;
    let cancelled = false;
    const refreshResults = async () => {
      if (document.visibilityState === 'hidden') return;
      try {
        const fresh = await API.getResults(currentCaseId);
        if (cancelled) return;
        setResults(previous => {
          if (
            previous?.agent?.status === fresh.agent?.status &&
            previous?.agent?.updated_at === fresh.agent?.updated_at &&
            previous?.agent?.paused_transaction === fresh.agent?.paused_transaction
          ) return previous;
          return fresh;
        });
        const freshAgent = fresh.agent;
        const freshPausedRequirements = requirementsForPausedTransaction(
          freshAgent?.transactions,
          freshAgent?.paused_transaction,
        );
        if (
          fresh.case.case_id === currentCaseId &&
          COMPLETE_STATUSES.includes(String(fresh.case.status || '').toLowerCase()) &&
          String(freshAgent?.status || '').toLowerCase() === 'paused' &&
          freshAgent?.paused_transaction &&
          freshPausedRequirements.length > 0
        ) setView('results');
      } catch { /* transient result reads are retried on the next refresh */ }
    };
    void refreshResults();
    const timer = window.setInterval(() => void refreshResults(), 5000);
    window.addEventListener('focus', refreshResults);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('focus', refreshResults);
    };
  }, [view, currentCaseId]);

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
        const pausedTx = uploadedForPausedTxRef.current;
        if (pausedTx) {
          uploadedForPausedTxRef.current = null;
          void waitForEvidenceResume(caseId, pausedTx.txId, pausedTx.updatedAt);
        }
        loadCases();
      }
    } catch (e: any) {
      addLog(`⚠ Polling error: ${e.message}`, "log-warn");
    }
  };

  // -- Final report (generated only on explicit user request; backend is the
  // source of truth for readiness — the UI never decides it itself) --
  const refreshFinalReport = async (caseId: string) => {
    try {
      setFinalReport(await API.getFinalReportState(caseId));
    } catch {
      setFinalReport(null); // no generated report yet / nothing ready
    }
  };

  // Consolidated Phase C findings: rendered from the persisted container only;
  // read failures hide the section but never fake content.
  const refreshFindings = async (caseId: string) => {
    try {
      setCaseFindings(await API.getCaseFindings(caseId));
    } catch {
      setCaseFindings(null);
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
      void refreshFinalReport(caseId);
      void refreshFindings(caseId);
    } catch (e: any) {
      addLog(`✗ Failed to load results: ${e.message}`, "log-err");
    }
  };

  const loadResultsFor = async (caseId: string) => {
    setCurrentCaseId(caseId);
    setActiveCaseId(caseId);
    sessionStorage.setItem("currentCaseId", caseId);
    setFinalReport(null);
    setCaseFindings(null);
    setReportMessage(null);
    try {
      const data = await API.getResults(caseId);
      setResults(data);
      const docs = data.documents.filter(d => d.status === "structured");
      if (docs.length > 0) setActiveDocId(String(docs[0].doc_id));
      void refreshFinalReport(caseId);
      void refreshFindings(caseId);
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
      if (currentCaseId) void refreshFindings(currentCaseId);
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

  const handleGenerateFinalReport = async (reportType: 'FINAL' | 'PRELIMINARY' = 'FINAL') => {
    const cid = currentCaseId || caseInfo?.case_id;
    if (!cid || reportBusy) return;
    setReportBusy(true);
    setReportMessage(null);
    try {
      const outcome = await API.generateFinalReport(cid, reportType);
      if (outcome.status === 'blocked') {
        setReportBlockers(outcome.blockers || []);
      } else if (outcome.status === 'generated') {
        setFinalReport({ case_id: cid, ready: true, blockers: [], report: outcome.report || null });
      }
    } catch (e: any) {
      setReportMessage('Could not generate report: ' + (e?.message || 'unexpected error'));
    } finally {
      setReportBusy(false);
    }
  };

  // Blocked-FINAL dialog shortcut: the same PRELIMINARY flow, dialog dismissed.
  const handleGeneratePreliminaryFromModal = () => {
    setReportBlockers(null);
    void handleGenerateFinalReport('PRELIMINARY');
  };

  const fetchFinalReportPdf = async (): Promise<Blob> => {
    const cid = currentCaseId || caseInfo?.case_id;
    if (!cid) throw new Error('No case selected');
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(`/api/results/${cid}/final-report/pdf`, { headers });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `Request failed (${response.status})`);
    }
    return await response.blob();
  };

  const previewFinalReportPdf = async () => {
    try {
      const blobUrl = URL.createObjectURL(await fetchFinalReportPdf());
      window.open(blobUrl, '_blank');
    } catch (error: any) {
      alert('Could not open the final report. ' + (error?.message || ''));
    }
  };

  const downloadFinalReportPdf = async () => {
    try {
      const url = URL.createObjectURL(await fetchFinalReportPdf());
      const link = document.createElement('a');
      link.href = url;
      link.download = 'final-title-audit-report.pdf';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error: any) {
      alert('Could not download the final report. ' + (error?.message || ''));
    }
  };

  // -- Results actions --
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

  const waitForEvidenceResume = async (caseId: string, previousPausedTx: string, previousUpdatedAt: string | null) => {
    const startedAt = Date.now();
    while (Date.now() - startedAt < ANALYSIS_WAIT_MS) {
      await new Promise(resolve => window.setTimeout(resolve, 2500));
      try {
        const fresh = await API.getResults(caseId);
        setResults(fresh);
        const state = fresh.agent;
        if (state?.status === 'done' || state?.status === 'error') return;
        if (state?.status === 'paused' && state.paused_transaction &&
            (state.paused_transaction !== previousPausedTx || (!!previousUpdatedAt && state.updated_at !== previousUpdatedAt))) return;
      } catch { /* retry transient result reads */ }
    }
    addLog('⚠ Verification is taking longer than expected; refresh results to check its status.', 'log-warn');
  };

  const submitEvidence = async () => {
    const txId = manualUploadTxId || pausedTransactionId;
    const reqs = manualUploadTxId
      ? requirementsForPausedTransaction(rawTx, manualUploadTxId)
      : pausedRequirements;
    const slots = reqs;
    const selected = slots
      .map((_: unknown, i: number) => evidenceUploads[i])
      .filter((f): f is File => !!f);
    if (!currentCaseId || !txId || !selected.length) return;
    setEvidenceUploadBusy(true);
    try {
      if (txId === pausedTransactionId) {
        uploadedForPausedTxRef.current = { txId, updatedAt: results?.agent?.updated_at || null };
        setDismissedPauseKey(`${txId}:${String(results?.agent?.updated_at || '')}`);
        await API.uploadMore(currentCaseId, selected);
        addLog(`Submitted ${selected.length} document(s); OCR processing started. Verification resumes automatically when processing finishes.`, "log-info");
      } else {
        await API.uploadMore(currentCaseId, selected, txId);
        addLog(`Submitted ${selected.length} document(s) for ${txId}; OCR processing started. Verification will retry only this transaction when processing finishes.`, "log-info");
      }
      setManualUploadTxId(null);
      setEvidenceUploads({});
      setView('processing');
      startPolling(currentCaseId);
    } catch (e: any) {
      addLog(`✗ Evidence upload failed: ${e.message}`, "log-err");
      if (txId !== pausedTransactionId) setDismissedPauseKey(null);
    } finally {
      setEvidenceUploadBusy(false);
    }
  };

  const skipPausedTransaction = async () => {
    const txId = results?.agent?.paused_transaction;
    if (!currentCaseId || !txId) return;
    if (!window.confirm(`Skip ${txId} without verifying? It stays pending and verification continues with the next transaction.`)) return;
    const previousUpdatedAt = results?.agent?.updated_at || null;
    setEvidenceUploadBusy(true);
    setDismissedPauseKey(`${txId}:${String(previousUpdatedAt)}`);
    try {
      await API.skipAgentTransaction(currentCaseId, txId);
      addLog(`Skipped ${txId}; it remains pending and verification will continue with the next transaction.`, "log-warn");
      setAnalyzing(true);
      const poll = async (startedAt: number) => {
        try {
          const fresh = await API.getResults(currentCaseId);
          setResults(fresh);
          const state = fresh.agent;
          const hasNewState = !!state?.updated_at && state.updated_at !== previousUpdatedAt;
          if ((hasNewState && ['done', 'paused', 'error'].includes(state?.status || '')) || Date.now() - startedAt > ANALYSIS_WAIT_MS) {
            setAnalyzing(false);
            return;
          }
        } catch { /* continue polling until completion or timeout */ }
        window.setTimeout(() => void poll(startedAt), 2500);
      };
      void poll(Date.now());
    } catch (e: any) {
      addLog(`✗ Skip failed: ${e.message}`, "log-err");
      setDismissedPauseKey(null);
    } finally {
      setEvidenceUploadBusy(false);
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
const visibleErrors = (statusData?.errors || []).filter((error: any) => error.step !== 'classify');
  const activeDoc = results?.documents?.find(d => String(d.doc_id) === String(activeDocId));
  const agent = results?.agent;
  const caseInfo = results?.case;
  const allComplete = caseInfo ? COMPLETE_STATUSES.includes(caseInfo.status) : false;

  // Transform agent.transactions to UI format
  const rawTx = agent?.transactions || [];
  const requiredDocumentCount = rawTx.reduce(
    (count: number, transaction: any) => count + (Array.isArray(transaction.required_documents) ? transaction.required_documents.length : 0),
    0,
  );
  const agentTx = rawTx.map((t: any, i: number) => ({
    ...t,
    index: t.sequence ?? i + 1,
  }));
  const verifiedCount = rawTx.filter((t: any) =>
    String(t.status || '').toUpperCase() === 'VERIFIED_WITH_AVAILABLE_EVIDENCE'
  ).length;
  const issueCount = rawTx.filter((t: any) => String(t.status || '').toUpperCase() === 'ISSUES_IDENTIFIED').length;
  const skippedTxIds = new Set<string>(agent?.skipped_tx_ids || []);
  const skippedCount = agentTx.filter((t: any) =>
    skippedTxIds.has(t.tx_id)
    || ['SKIPPED', 'SKIPPED_BY_USER'].includes(String(t.status || '').toUpperCase())
    || t.legacy_fields?.workflow_action === 'SKIPPED_BY_USER'
  ).length;
  const pendingCount = Math.max(0, rawTx.length - verifiedCount - issueCount - skippedCount);
  const pausedRequirements = requirementsForPausedTransaction(rawTx, agent?.paused_transaction);
  const pausedTransactionId = String(agent?.paused_transaction || '').trim();
  const pauseKey = `${pausedTransactionId}:${String(agent?.updated_at || '')}`;
  const showPausedEvidenceDialog = Boolean(
    results && currentCaseId && results.case.case_id === currentCaseId &&
    String(agent?.status || '').toLowerCase() === 'paused' &&
    pausedTransactionId && pausedRequirements.length > 0 &&
    dismissedPauseKey !== pauseKey,
  );
  // One dialog serves both flows: the automatic pause dialog and an upload
  // opened from any eligible transaction card. Manual open wins.
  const dialogTxId = manualUploadTxId || (showPausedEvidenceDialog ? pausedTransactionId : '');
  const dialogRequirements = dialogTxId
    ? requirementsForPausedTransaction(rawTx, dialogTxId)
    : [];

  // Title chain data from agent
  const titleChain = agent?.title_chain;
  const legacyTitleChain = titleChain && !Array.isArray(titleChain)
    ? titleChain as { transactions?: any[]; title_story?: string; unresolved?: string[] }
    : {};
  const chain = legacyTitleChain.transactions || [];
  const sortedChain = sortChain(chain);
  const titleStory = legacyTitleChain.title_story || '';
  const chainUnresolved = legacyTitleChain.unresolved || [];
  const propertyIdentity = (agent?.property_identity || {}) as Record<string, unknown>;
  const identityDetails = Array.isArray(propertyIdentity.details)
    ? propertyIdentity.details.map((detail, index) => {
      const record: Record<string, unknown> = detail && typeof detail === 'object' && !Array.isArray(detail)
        ? detail as Record<string, unknown>
        : { value: detail };
      return {
        label: typeof record.label === 'string' ? record.label : `Property detail ${index + 1}`,
        value: record.value,
      };
    }).filter(detail => detail.value != null && detail.value !== '')
    : [];
  const identityEntries = Object.entries(propertyIdentity).filter(([key, value]) =>
    key !== 'details' && value != null && value !== ''
  );

  return (
    <div className="ctd-root">
      {dialogTxId && (
        <EvidenceRequestDialog
          transactionId={dialogTxId}
          requirements={dialogRequirements}
          uploads={evidenceUploads}
          busy={evidenceUploadBusy}
          onPick={(index, file) => setEvidenceUploads((prev) => ({ ...prev, [index]: file }))}
          onSubmit={() => void submitEvidence()}
          onSkip={
            manualUploadTxId
              ? () => { setManualUploadTxId(null); setEvidenceUploads({}); }
              : () => void skipPausedTransaction()
          }
          skipLabel={manualUploadTxId ? 'Close' : undefined}
          submitLabel={manualUploadTxId ? 'Submit & retry verification' : undefined}
        />
      )}
      {reportBlockers && (
        <FinalReportBlockersModal
          blockers={reportBlockers}
          onClose={() => setReportBlockers(null)}
          onGeneratePreliminary={handleGeneratePreliminaryFromModal}
        />
      )}
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
                      <div className="verification-verdict-line">
                        <p className="vr-status-line" style={{ fontWeight: 800, letterSpacing: '.01em', lineHeight: 1.3, margin: 0, textTransform: 'uppercase',
                          color: '#1c1917' }}>
                          {agent?.status === "error"
                            ? "VERIFICATION COULD NOT BE COMPLETED, PLEASE RETRY"
                            : agent?.status === "running" || agent?.status === "idle"
                            ? "VERIFICATION IN PROGRESS…"
                            : null}
                        </p>
                      </div>
                    </div>
                  </div>

                  {(identityDetails.length > 0 || identityEntries.length > 0) && (
                    <section className="verification-property-identity" aria-labelledby="verification-property-identity-title">
                      <div className="verification-property-identity-heading">
                        <span className="verification-property-identity-kicker">TARGET PROPERTY</span>
                        <h2 id="verification-property-identity-title">Property identity</h2>
                        <p>Recorded identifiers and descriptions for the property under verification.</p>
                      </div>
                      <dl className="verification-property-identity-list">
                        {identityDetails.map((detail, index) => (
                          <div className="verification-property-identity-item" key={`${detail.label}-${index}`}>
                            <dt>{detail.label}</dt>
                            <dd>{typeof detail.value === 'object' ? JSON.stringify(detail.value) : String(detail.value)}</dd>
                          </div>
                        ))}
                        {identityEntries.map(([key, value]) => (
                          <div className="verification-property-identity-item" key={key}>
                            <dt>{key.replace(/[_-]+/g, ' ')}</dt>
                            <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
                          </div>
                        ))}
                      </dl>
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
                    <div className="pipeline-container phase-a-chain-list verification-results-list">
                    <div className="pl-controls-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 20, marginBottom: 24 }}>
                      <span className="verification-progress-copy">
                        <strong>Transaction outcomes</strong>
                        <span>{verifiedCount} verified · {skippedCount} skipped and unverified · {pendingCount} pending · {issueCount} with issues identified</span>
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

                    {/* Dynamic Pipeline Items */}
                    {agent?.transactions && agent.transactions.length > 0 ? (
                      agentTx.map((item: any, idx: number) => (
                        <TransactionResultCard
                          key={item.tx_id || idx}
                          transaction={item}
                          documents={results.documents}
                          skipped={skippedTxIds.has(item.tx_id)}
                          onOpenUpload={
                            skippedTxIds.has(item.tx_id)
                            || String(item.status || '').toUpperCase() === 'ISSUES_IDENTIFIED'
                              ? (txId) => { setEvidenceUploads({}); setManualUploadTxId(txId); }
                              : undefined}
                          evidenceUploadBusy={evidenceUploadBusy}
                        />
                      ))
                    ) : (
                      <div className="vr-sheet-empty">
                        {agent?.status === "error"
                          ? "Verification did not complete due to a temporary issue. Please retry — no transactions were evaluated."
                          : "Verification has not run yet. No transactions have been evaluated."}
                      </div>
                    )}
                  </div>

                  {/* Re-run Verification + Actions Controls */}
                  <div className="pl-actions-row" style={{ marginTop: 24, marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
                    {requiredDocumentCount > 0 ? (
                    <button
                      className="btn btn-secondary"
                      onClick={async () => {
                        const cid = currentCaseId || caseInfo?.case_id;
                        if (!cid) return;
                        try {
                          const headers: Record<string, string> = {};
                          const token = getToken();
                          if (token) headers['Authorization'] = `Bearer ${token}`;
                          const response = await fetch(`/api/results/${cid}/required-documents/pdf`, { headers });
                          if (!response.ok) {
                            const body = await response.json().catch(() => null);
                            throw new Error(body?.detail || `Request failed (${response.status})`);
                          }
                          const url = URL.createObjectURL(await response.blob());
                          const link = document.createElement('a');
                          link.href = url;
                          link.download = 'required-documents-checklist.pdf';
                          document.body.appendChild(link);
                          link.click();
                          link.remove();
                          URL.revokeObjectURL(url);
                        } catch (error: any) {
                          alert('Could not generate required-documents checklist. ' + (error?.message || ''));
                        }
                      }}
                    >
                      <Download size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                      Download Required Documents
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

                  {/* Final report — generated only on explicit request; the backend
                      decides readiness and returns blockers when work remains. */}
                  <div style={{ marginTop: 0, marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <button
                      className="btn btn-secondary"
                      disabled={reportBusy}
                      onClick={() => handleGenerateFinalReport('FINAL')}
                      title="Create the final property title audit report PDF (requires every transaction verified)"
                    >
                      <ScrollText size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                      {reportBusy ? 'Generating…' : finalReport?.report ? 'Regenerate Final Report' : 'Generate Final Report'}
                    </button>
                    {finalReport && !finalReport.ready && !reportBusy && (
                      <button
                        className="btn btn-secondary"
                        onClick={() => handleGenerateFinalReport('PRELIMINARY')}
                        title="An incomplete, clearly-labeled PRELIMINARY audit — lists exactly what remains outstanding"
                      >
                        <FileWarning size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                        Generate Preliminary Report
                      </button>
                    )}
                    {finalReport?.report?.pdf_available && (
                      <>
                        {finalReport?.report?.report_type && (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: '#4338ca', background: '#e0e7ff', border: '1px solid #a5b4fc', borderRadius: 999, padding: '4px 12px' }}>
                            {finalReport.report.report_type === 'PRELIMINARY' ? 'PRELIMINARY' : 'FINAL'}
                            {typeof finalReport.report.version === 'number' && ` · v${finalReport.report.version}`}
                          </span>
                        )}
                        <button className="btn btn-secondary" disabled={reportBusy} onClick={previewFinalReportPdf}>
                          <FileText size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                          Preview Report
                        </button>
                        <button className="btn btn-secondary" disabled={reportBusy} onClick={downloadFinalReportPdf}>
                          <Download size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
                          Download Report PDF
                        </button>
                      </>
                    )}
                    {(finalReport?.report?.superseded ?? finalReport?.report?.stale) && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: '#b45309', background: '#fffbeb', border: '1px solid #f59e0b', borderRadius: 999, padding: '4px 12px' }}>
                        <AlertTriangle size={12} />
                        Report superseded — verification results changed; regenerate
                      </span>
                    )}
                    {reportMessage && (
                      <span style={{ fontSize: 12, color: '#b91c1c' }}>{reportMessage}</span>
                    )}
                  </div>

                  {/* Consolidated property findings (Phase C container). */}
                  {caseFindings && (
                    <ConsolidatedFindings data={caseFindings} />
                  )}

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

                </div>
              )}

              {/* TAB 2: TITLE CHAIN */}
              {activeReportTab === 'title-chain' && (
                <div className="tab-pane active">
                  <PhaseAChainView
                    result={agent || {}}
                    onBack={() => setActiveReportTab('verification')}
                  />
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
