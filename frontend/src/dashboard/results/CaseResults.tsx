import React from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, FileText, GitBranch, Loader2, MoreHorizontal, ScrollText, ShieldCheck, Upload,
} from 'lucide-react';
import type { CaseResults as CaseResultsData, VerificationEvent, VerificationState } from '../../api/backend';
import { LiveFeed } from '../verification/LiveFeed';
import { ChainTimeline, timelineLinks } from './ChainTimeline';
import { humanizeType, refLabeller } from './labels';
import { caseIssues } from './issues';
import { IssuesList, Opinion, Section, opinionLabel, opinionTone } from './ReportView';
import { useVerification } from './useVerification';

export type CasePage = 'chain' | 'report';

export interface CaseResultsProps {
  caseId: string;
  results: CaseResultsData;
  chainBusy: boolean;
  onRebuildChain: () => void;
  onOpenPdf: (docId: string) => void;
}

/** One case, on two pages: the title chain and the verification report (``?page=chain|report``). */
export function CaseResults(props: CaseResultsProps) {
  const verification = useVerification(props.caseId);
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('page');
  const page: CasePage = requested === 'chain' || requested === 'report'
    ? requested
    : verification.state?.report || verification.running ? 'report' : 'chain';
  const onPageChange = (next: CasePage) => {
    const params = new URLSearchParams(searchParams);
    params.set('page', next);
    setSearchParams(params);
  };
  return <CaseResultsView {...props} {...verification} page={page} onPageChange={onPageChange} />;
}

export interface CaseResultsViewProps extends CaseResultsProps {
  state: VerificationState | null;
  events: VerificationEvent[];
  error: string | null;
  running: boolean;
  uploadingId: string | null;
  start: () => void;
  upload: (requisitionId: string, file: File) => void;
  page: CasePage;
  onPageChange: (page: CasePage) => void;
}

/** A one-line name for the property: report schedule identifiers and location, else Phase A identity. */
export function propertyLine(results: CaseResultsData, state: VerificationState | null): string {
  const label = refLabeller(state?.case_file);
  const schedule = state?.report?.sections.find(section => section.id === 'property_schedule');
  const table = schedule?.blocks.find(block => block.type === 'table');
  if (table && table.type === 'table') {
    const pick = (pattern: RegExp) => table.rows.find(row => pattern.test(row[0] || ''))?.[1];
    const parts = [pick(/identif/i), pick(/location/i)]
      .filter((value): value is string => Boolean(value))
      .map(value => label(value));
    if (parts.length) return parts.join(' · ');
  }
  const details = identityDetails(results);
  const parts = details.slice(0, 3).map(detail => `${detail.label} ${label(detail.value)}`);
  return parts.length ? parts.join(' · ') : `Case ${results.case.case_id}`;
}

function identityDetails(results: CaseResultsData): { label: string; value: string }[] {
  return (results.agent?.property_identity as { details?: { label: string; value: string }[] } | undefined)?.details || [];
}

function status(results: CaseResultsData, state: VerificationState | null, running: boolean): { code: string; label: string; tone: string } {
  if (running) return { code: 'PENDING', label: 'Verifying…', tone: 'neutral' };
  if (state?.report) {
    const tone = opinionTone(state.report.opinion);
    return {
      code: tone === 'good' ? 'PASS' : tone === 'warn' ? 'WARNING' : 'FAIL',
      label: opinionLabel(state.report.opinion),
      tone,
    };
  }
  if (state?.run && ['incomplete', 'error'].includes(state.run.status)) return { code: 'PENDING', label: 'Verification not finished', tone: 'warn' };
  const chain = String(results.agent?.status || '').toLowerCase();
  if (chain === 'done') return { code: 'PENDING', label: 'Not verified yet', tone: 'neutral' };
  if (chain === 'paused') return { code: 'PENDING', label: 'Waiting for documents', tone: 'warn' };
  if (chain === 'error') return { code: 'FAIL', label: 'Title chain failed', tone: 'bad' };
  return { code: 'PENDING', label: 'Building title chain…', tone: 'neutral' };
}

/** The day a verification run finished, in report style; empty when unknown. */
function reportDate(state: VerificationState | null): string {
  const value = state?.run?.finished_at;
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function CaseResultsView(props: CaseResultsViewProps) {
  const { results, state, running, chainBusy, start, onRebuildChain, page, onPageChange } = props;
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const prepared = reportDate(state);
  const chainReady = String(results.agent?.status || '').toLowerCase() === 'done';
  const unfinished = Boolean(state?.run && ['incomplete', 'error'].includes(state.run.status));
  const badge = status(results, state, running);
  const primary = !chainReady || running ? null : !caseFile ? 'Verify title' : unfinished ? 'Continue verification' : null;

  return (
    <div className="cr-page">
      <header className="cr-header">
        <div className="cr-header-text">
          <span className="cr-kicker">Property title verification</span>
          <h1>{propertyLine(results, state)}</h1>
          <div className="cr-meta">
            <span className={`cr-meta-item cr-verdict cr-tone-${badge.tone}`}>
              <span className="cr-verdict-code">{badge.code}</span>
              <span className="cr-verdict-label">{badge.label}</span>
            </span>
            {report && <span className="cr-meta-item">Report v{report.version}</span>}
            {prepared && <span className="cr-meta-item">{prepared}</span>}
            <span className="cr-meta-item">Case {results.case.case_id}</span>
          </div>
        </div>
        <div className="cr-header-actions">
          {primary && (
            <button className="btn btn-primary" type="button" onClick={start}>
              <ShieldCheck size={14} /> {primary}
            </button>
          )}
          <details className="cr-menu">
            <summary aria-label="More actions"><MoreHorizontal size={16} /></summary>
            <div className="cr-menu-items">
              {caseFile && !running && <button type="button" onClick={start}>Run verification again</button>}
              <button type="button" disabled={chainBusy} onClick={onRebuildChain}>
                {chainBusy ? 'Rebuilding title chain…' : 'Rebuild title chain'}
              </button>
            </div>
          </details>
        </div>
      </header>

      <nav className="cr-tabs" aria-label="Case pages">
        <button type="button" className={page === 'chain' ? 'cr-tab cr-tab-active' : 'cr-tab'} aria-current={page === 'chain' ? 'page' : undefined} onClick={() => onPageChange('chain')}>
          <GitBranch size={14} /> Title chain
        </button>
        <button type="button" className={page === 'report' ? 'cr-tab cr-tab-active' : 'cr-tab'} aria-current={page === 'report' ? 'page' : undefined} onClick={() => onPageChange('report')}>
          <ScrollText size={14} /> Verification report
        </button>
      </nav>

      {page === 'chain' ? <ChainPage {...props} /> : <ReportPage {...props} primary={primary} />}
    </div>
  );
}

/** How ownership passed: property identity, the chain timeline and the uploaded documents. */
function ChainPage({ results, state, onOpenPdf }: CaseResultsViewProps) {
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const identity = identityDetails(results);
  const label = refLabeller(caseFile);
  return (
    <>
      {identity.length > 0 && (
        <Section id="cr-identity-title" title="Property identity">
          <dl className="cr-facts">
            {identity.map((detail, i) => <div key={i}><dt>{detail.label}</dt><dd>{detail.value}</dd></div>)}
          </dl>
        </Section>
      )}

      <Section
        id="cr-chain-title"
        title="Title chain"
        note={`Earliest transfer first. Open a transfer to see its details${caseFile ? ' and verdict' : ''}.`}
      >
        <ChainTimeline links={timelineLinks(caseFile?.chain, results.agent?.title_chain)} label={label} />
      </Section>

      <Section id="cr-docs-title" title="Documents" aside={`${results.documents.length} uploaded`}>
        <ul className="cr-docs">
          {results.documents.map((doc: any) => {
            const examined = caseFile?.documents?.[doc.doc_id];
            const docState = examined?.examined ? 'Examined' : examined?.examination_error ? 'Could not be read'
              : doc.status === 'classification_failed' || doc.status === 'failed' ? 'Needs attention'
              : doc.status !== 'structured' ? 'Processing'
              : examined && report ? 'Not needed' : 'Ready';
            const tone = docState === 'Examined' || docState === 'Ready' ? 'good'
              : docState === 'Could not be read' ? 'bad'
              : docState === 'Processing' || docState === 'Not needed' ? 'neutral' : 'warn';
            return (
              <li key={doc.doc_id}>
                <button type="button" className="cr-doc-name" onClick={() => onOpenPdf(String(doc.doc_id))} title="Open the original PDF">
                  <FileText size={14} /> {doc.filename || 'Untitled document'}
                </button>
                <span className="cr-doc-type">{humanizeType(doc.document_type)}</span>
                <span className={`cr-status cr-tone-${tone}`}>{docState}</span>
              </li>
            );
          })}
        </ul>
      </Section>
    </>
  );
}

/** Is the title clear: opinion, documents needed, the report and the agent's steps. */
function ReportPage({ state, events, error, running, uploadingId, start, upload, primary }: CaseResultsViewProps & { primary: string | null }) {
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const label = refLabeller(caseFile);
  const unfinished = Boolean(state?.run && ['incomplete', 'error'].includes(state.run.status));
  const requisitions = caseFile?.requisitions || [];
  const pending = requisitions.filter(item => item.status !== 'resolved');
  const settled = requisitions.length - pending.length;
  const lastStep = events.length ? events[events.length - 1].text : 'Starting…';

  return (
    <>
      {error && <p className="cr-alert"><AlertTriangle size={14} /> {error}</p>}
      {unfinished && !running && (
        <p className="cr-alert">
          <AlertTriangle size={14} />
          {state?.run?.status === 'incomplete'
            ? 'The last verification stopped at its limit. Progress is saved; continue to finish.'
            : 'The last verification failed. Progress is saved; continue to retry.'}
        </p>
      )}
      {running && <div className="cr-progress"><Loader2 size={14} className="cr-spin" /> {lastStep}</div>}

      {!report && !running && (
        <section className="cr-empty" aria-label="No report yet">
          <h2>No verification report yet</h2>
          <p>
            The verification agent checks each transfer in the title chain against its own documents,
            follows up anything unexpected, lists the documents still needed, and writes a due diligence
            report with an opinion on whether the title is clear.
          </p>
          {primary && (
            <div className="cr-empty-action"><button className="btn btn-primary" type="button" onClick={start}><ShieldCheck size={14} /> {primary}</button></div>
          )}
        </section>
      )}

      {report && (
        <>
          <p className="cr-lede">{label(report.property_summary)}</p>
          <Opinion report={report} label={label} />
          <IssuesList issues={caseIssues(report, caseFile)} label={label} />
        </>
      )}

      {pending.length > 0 && (
        <Section
          id="cr-needed-title"
          title="Documents needed"
          aside={pending.length === 1 ? '1 open item' : `${pending.length} open items`}
          note="Verification continued without these. Upload one and only what it affects is checked again."
        >
          <ul className="cr-needed">
            {pending.map(item => (
              <li key={item.id}>
                <div className="cr-needed-main">
                  <b>{label(item.document)}</b>
                  <span>{label(item.reason)}</span>
                </div>
                <span className={`cr-status cr-tone-${item.status === 'open' ? 'warn' : 'good'}`}>
                  {item.status === 'open' ? 'Open' : 'Received'}
                </span>
                {item.status === 'open' ? (
                  <label className={`cr-action${running || uploadingId ? ' cr-disabled' : ''}`}>
                    <Upload size={13} /> {uploadingId === item.id ? 'Uploading…' : 'Upload'}
                    <input
                      type="file"
                      accept="application/pdf"
                      hidden
                      disabled={running || uploadingId !== null}
                      onChange={event => {
                        const file = event.target.files?.[0];
                        if (file) upload(item.id, file);
                        event.target.value = '';
                      }}
                    />
                  </label>
                ) : (
                  <span className="cr-needed-note">Being checked</span>
                )}
              </li>
            ))}
          </ul>
          {settled > 0 && <p className="cr-settled"><CheckCircle2 size={13} /> {settled} already settled</p>}
        </Section>
      )}

      {events.length > 0 && (
        <details className="cr-steps">
          <summary>Agent steps ({events.length})</summary>
          <LiveFeed events={events} running={running} label={label} />
        </details>
      )}
    </>
  );
}
