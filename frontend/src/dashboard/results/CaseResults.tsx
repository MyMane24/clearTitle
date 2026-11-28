import React from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, Download, FileText, GitBranch, MoreHorizontal, ScrollText, ShieldCheck, Upload, X,
} from 'lucide-react';
import { API, type CaseResults as CaseResultsData, type SectionName, type VerificationEvent, type VerificationState } from '../../api/backend';
import { LiveFeed } from '../verification/LiveFeed';
import { ChainTimeline, timelineLinks } from './ChainTimeline';
import { SECTION_LABEL, humanizeType, refLabeller } from './labels';
import { Opinion, Section, TitleReport, opinionLabel, opinionTone } from './ReportView';
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
  queuedUploads: Record<string, File>;
  start: (fresh?: boolean) => void;
  upload: (requisitionId: string, file: File) => void;
  cancelUpload: (requisitionId: string) => void;
  submitUploads: () => void;
  page: CasePage;
  onPageChange: (page: CasePage) => void;
}

/** A one-line name for the property, from the Phase A property identity. */
export function propertyLine(results: CaseResultsData, state: VerificationState | null): string {
  const label = refLabeller(state?.case_file);
  const title = compactProperty(identityDetails(results));
  return title ? label(title) : `Case ${results.case.case_id}`;
}

const PROPERTY_ID = /\b(Survey|Sy|CTS|Plot|Site|Flat|Khata|PID)\s*(?:No\.?|Number)?\s*([A-Za-z0-9][A-Za-z0-9/.\-]*)/i;
const VILLAGE = /\b(?:situated at|at)\s+([^,;.]+?\bVillage)\b/i;
const ID_NAME: Record<string, string> = {
  survey: 'Survey No.', sy: 'Sy. No.', cts: 'CTS No.', plot: 'Plot No.',
  site: 'Site No.', flat: 'Flat No.', khata: 'Khata No.', pid: 'PID No.',
};
const OWNER_LABEL = /\b(owner|holder|purchaser|possessor|transferee)\b/i;

/** A short header title: the first survey, plot, site, flat, khata or CTS number in the
 * identity, with the village when stated. The full identity is shown further down the page. */
function compactProperty(details: { label: string; value: string }[]): string {
  for (const detail of details) {
    const match = detail.value.match(PROPERTY_ID);
    if (!match) continue;
    const name = ID_NAME[match[1].toLowerCase()] || `${match[1]} No.`;
    const village = detail.value.match(VILLAGE)?.[1].trim();
    return `${name} ${match[2]}${village ? ` · ${village}` : ''}`;
  }
  const short = details.find(detail => detail.value.length <= 60 && !OWNER_LABEL.test(detail.label));
  if (short) return `${short.label} ${short.value}`;
  const first = details[0];
  if (!first) return '';
  const cut = first.value.slice(0, 60);
  const end = cut.lastIndexOf(' ');
  return `${first.label} ${end > 0 ? cut.slice(0, end) : cut}…`;
}

function identityDetails(results: CaseResultsData): { label: string; value: string }[] {
  return (results.agent?.property_identity as { details?: { label: string; value: string }[] } | undefined)?.details || [];
}

function status(results: CaseResultsData, state: VerificationState | null, running: boolean): { label: string; tone: string } {
  if (running) return { label: 'Verifying…', tone: 'neutral' };
  if (state?.report) return { label: opinionLabel(state.report.opinion), tone: opinionTone(state.report.opinion) };
  if (state?.run && ['incomplete', 'error'].includes(state.run.status)) return { label: 'Verification not finished', tone: 'warn' };
  if (String(results.case?.status || '').toLowerCase() === 'failed') return { label: 'Documents failed', tone: 'bad' };
  const chain = String(results.agent?.status || '').toLowerCase();
  if (chain === 'done') return { label: 'Not verified yet', tone: 'neutral' };
  if (chain === 'paused') return { label: 'Waiting for documents', tone: 'warn' };
  if (chain === 'error') return { label: 'Title chain failed', tone: 'bad' };
  return { label: 'Building title chain…', tone: 'neutral' };
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
  const { results, state, events, error, running, chainBusy, start, onRebuildChain, page, onPageChange } = props;
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const prepared = reportDate(state);
  const chainReady = String(results.agent?.status || '').toLowerCase() === 'done';
  const unfinished = Boolean(state?.run && ['incomplete', 'error'].includes(state.run.status));
  const badge = status(results, state, running);
  const primary = !chainReady || running ? null : !caseFile ? 'Verify title' : unfinished ? 'Continue verification' : null;
  // While a run is going, the previous report is stale: show this run's steps only.
  const liveRunId = state?.run?.status === 'running' ? state.run.id : null;
  const liveEvents = liveRunId ? events.filter(event => event.run_id === liveRunId) : [];
  const [downloading, setDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState<string | null>(null);
  const download = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await API.downloadReport(props.caseId);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Could not download the report.');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="cr-page">
      <header className="cr-header">
        <div className="cr-header-text">
          <h1>{propertyLine(results, state)}</h1>
          <div className="cr-meta">
            <span className={`cr-meta-item cr-verdict cr-tone-${badge.tone}`}>{badge.label}</span>
            {report && !running && <span className="cr-meta-item">Report v{report.version}</span>}
            {prepared && !running && <span className="cr-meta-item">{prepared}</span>}
            <span className="cr-meta-item">Case {results.case.case_id}</span>
          </div>
        </div>
        <div className="cr-header-actions">
          {report && !running && (
            <button className="btn btn-secondary" type="button" disabled={downloading} onClick={download}>
              <Download size={14} /> {downloading ? 'Preparing PDF…' : 'Download PDF'}
            </button>
          )}
          {primary && (
            <button className="btn btn-primary" type="button" onClick={() => start(false)}>
              <ShieldCheck size={14} /> {primary}
            </button>
          )}
          <details className="cr-menu">
            <summary aria-label="More actions"><MoreHorizontal size={16} /></summary>
            <div className="cr-menu-items">
              {caseFile && !running && <button type="button" onClick={() => start(true)}>Run verification again</button>}
              <button type="button" disabled={chainBusy} onClick={onRebuildChain}>
                {chainBusy ? 'Rebuilding title chain…' : 'Rebuild title chain'}
              </button>
            </div>
          </details>
        </div>
      </header>
      {downloadError && <p className="cr-alert"><AlertTriangle size={14} /> {downloadError}</p>}
      {error && <p className="cr-alert"><AlertTriangle size={14} /> {error}</p>}

      {running ? (
        <Section
          id="cr-live-title"
          title="Verifying the title"
          aside={<span className="cr-live"><span className="vf-pulse" /> Live</span>}
          note="The agent checks each transfer from the oldest to the newest. Steps appear as they happen."
        >
          <LiveFeed events={liveEvents} running label={refLabeller(state?.case_file)} />
        </Section>
      ) : (
        <>
          <nav className="cr-tabs" aria-label="Case pages">
            <button type="button" className={page === 'chain' ? 'cr-tab cr-tab-active' : 'cr-tab'} aria-current={page === 'chain' ? 'page' : undefined} onClick={() => onPageChange('chain')}>
              <GitBranch size={14} /> Title chain
            </button>
            <button type="button" className={page === 'report' ? 'cr-tab cr-tab-active' : 'cr-tab'} aria-current={page === 'report' ? 'page' : undefined} onClick={() => onPageChange('report')}>
              <ScrollText size={14} /> Verification report
            </button>
          </nav>

          {page === 'chain' ? <ChainPage {...props} /> : <ReportPage {...props} primary={primary} />}
        </>
      )}
    </div>
  );
}

/** How ownership passed: property identity, the chain timeline, the property today and the
 * uploaded documents. */
function ChainPage({ results, state, onOpenPdf }: CaseResultsViewProps) {
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const identity = identityDetails(results);
  const label = refLabeller(caseFile);
  const links = timelineLinks(caseFile?.transfers, results.agent?.title_chain);
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
        aside={links.length ? `${links.length} ${links.length === 1 ? 'transfer' : 'transfers'}` : undefined}
        note={links.length ? `Earliest transfer first. Open a transfer to see its details${caseFile ? ' and verdict' : ''}.` : undefined}
      >
        <ChainTimeline links={links} label={label} />
      </Section>

      {caseFile && <PropertyToday caseFile={caseFile} label={label} />}

      <Section id="cr-docs-title" title="Documents" aside={results.documents.length ? `${results.documents.length} uploaded` : undefined}>
        {results.documents.length === 0 ? (
          <p className="cr-muted">No documents uploaded.</p>
        ) : (
          <ul className="cr-docs">
            {results.documents.map((doc: any) => {
              const examined = caseFile?.documents?.[doc.doc_id];
              const docState = examined?.examined ? 'Examined' : examined?.examination_error ? 'Could not be read'
                : doc.status === 'classification_failed' || doc.status === 'failed' ? 'Needs attention'
                : doc.status !== 'structured' ? 'Processing'
                : examined && report ? 'Not examined' : 'Ready';
              const tone = docState === 'Examined' || docState === 'Ready' ? 'good'
                : docState === 'Could not be read' ? 'bad'
                : docState === 'Processing' ? 'neutral' : 'warn';
              return (
                <li key={doc.doc_id}>
                  <button type="button" className="cr-doc-name" onClick={() => onOpenPdf(String(doc.doc_id))} title={doc.filename || 'Untitled document'}>
                    <FileText size={14} /> <span className="cr-doc-file">{doc.filename || 'Untitled document'}</span>
                  </button>
                  <span className="cr-doc-type">{humanizeType(doc.document_type)}</span>
                  <span className={`cr-status cr-tone-${tone}`}>{docState}</span>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </>
  );
}

/** The property as it stands today: encumbrances, revenue records, tax and approvals. */
function PropertyToday({ caseFile, label }: { caseFile: NonNullable<VerificationState['case_file']>; label: (text: string) => string }) {
  const sections = Object.entries(caseFile.property_today || {}) as [SectionName, NonNullable<VerificationState['case_file']>['property_today'][SectionName]][];
  return (
    <Section id="cr-today-title" title="The property today" note="Checked after the last transfer.">
      <ul className="cr-docs cr-today">
        {sections.map(([name, section]) => {
          const state = !section ? 'Not checked yet' : section.ok ? 'In order' : 'See findings';
          const tone = !section ? 'neutral' : section.ok ? 'good' : 'warn';
          return (
            <li key={name}>
              <span className="cr-doc-name">{SECTION_LABEL[name]}</span>
              <span className="cr-doc-type">{section ? label(section.note) : ''}</span>
              <span className={`cr-status cr-tone-${tone}`}>{state}</span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/** Is the title clear: opinion, documents needed, the report and the agent's steps. */
function ReportPage({ state, uploadingId, queuedUploads, start, upload, cancelUpload, submitUploads, primary }: CaseResultsViewProps & { primary: string | null }) {
  const caseFile = state?.case_file || null;
  const report = state?.report || null;
  const label = refLabeller(caseFile);
  const unfinished = Boolean(state?.run && ['incomplete', 'error'].includes(state.run.status));
  // The provider's own message, trimmed: it is the only explanation of a failed run.
  const runError = (state?.run?.error || '').split('\n')[0].slice(0, 200);
  const requests = caseFile?.requests || [];
  const pending = requests.filter(item => item.status === 'open' || item.status === 'received');
  const settled = requests.filter(item => item.status === 'settled').length;

  return (
    <>
      {unfinished && (
        <p className="cr-alert">
          <AlertTriangle size={14} />
          <span>
            {state?.run?.status === 'incomplete'
              ? 'The last verification stopped at its limit. Progress is saved; continue to finish.'
              : 'The last verification failed. Progress is saved; continue to retry.'}
            {runError && <span className="cr-alert-detail">{runError}</span>}
          </span>
        </p>
      )}

      {!report && (
        <section className="cr-empty" aria-label="No report yet">
          <h2>No verification report yet</h2>
          <p>
            The verification agent checks each transfer in the title chain against its own documents,
            follows up anything unexpected, lists the documents still needed, and writes a due diligence
            report with an opinion on whether the title is clear.
          </p>
          {primary && (
            <div className="cr-empty-action"><button className="btn btn-primary" type="button" onClick={() => start(false)}><ShieldCheck size={14} /> {primary}</button></div>
          )}
        </section>
      )}

      {report && (
        <>
          <Opinion report={report} label={label} />
          <TitleReport report={report} label={label} />
        </>
      )}

      {pending.length > 0 && (
        <Section
          id="cr-needed-title"
          title="Documents needed"
          aside={pending.length === 1 ? '1 open item' : `${pending.length} open items`}
          note="Choose the documents you have, then process them together; one verification updates the report."
        >
          <ul className="cr-needed">
            {pending.map(item => (
              <li key={item.id}>
                <div className="cr-needed-main">
                  <b>{label(item.document)}</b>
                  <span>{label(item.reason)}</span>
                  {item.needed_for.length > 0 && <span className="cr-needed-for">For: {item.needed_for.map(label).join(', ')}</span>}
                </div>
                {queuedUploads[item.id] ? (
                  <>
                    <span className="cr-needed-file" title={queuedUploads[item.id].name}>{queuedUploads[item.id].name}</span>
                    <button type="button" className="cr-cancel" onClick={() => cancelUpload(item.id)} disabled={uploadingId !== null} aria-label="Cancel upload"><X size={15} /></button>
                  </>
                ) : (
                  <>
                    <span className={`cr-status cr-tone-${item.status === 'open' ? 'warn' : 'good'}`}>
                      {item.status === 'open' ? 'Open' : 'Received'}
                    </span>
                    {item.status === 'open' ? (
                      <label className={`cr-action${uploadingId ? ' cr-disabled' : ''}`}>
                        <Upload size={13} /> Choose PDF
                        <input
                          type="file"
                          accept="application/pdf"
                          hidden
                          disabled={uploadingId !== null}
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
                  </>
                )}
              </li>
            ))}
          </ul>
          {Object.keys(queuedUploads).length > 0 && (
            <button className="btn btn-primary" type="button" onClick={submitUploads} disabled={uploadingId !== null}>
              {uploadingId === 'batch' ? 'Processing documents…' : `Process ${Object.keys(queuedUploads).length} document${Object.keys(queuedUploads).length === 1 ? '' : 's'}`}
            </button>
          )}
          {settled > 0 && <p className="cr-settled"><CheckCircle2 size={13} /> {settled} already settled</p>}
        </Section>
      )}

    </>
  );
}
