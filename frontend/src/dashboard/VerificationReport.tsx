import React from 'react';
import { Download } from 'lucide-react';

import type { VerificationReport, VerificationReportLevel } from '../api/backend';
import { ReportMarkdown } from './ReportMarkdown';

type Props = {
  report: VerificationReport;
  /** ClearTitle logo URL; supplied by the dashboard so tests can omit it. */
  logo?: string;
  onDownloadPdf?: () => void;
  downloadBusy?: boolean;
};

const SEVERITY_META: Record<string, { chip: string; bar: string; bg: string; label: string }> = {
  CRITICAL: { chip: '#b91c1c', bar: '#dc2626', bg: '#fef2f2', label: 'Critical' },
  CAUTION: { chip: '#b45309', bar: '#d97706', bg: '#fffbeb', label: 'Caution' },
  CLEAR: { chip: '#15803d', bar: '#16a34a', bg: '#f0fdf4', label: 'Clear' },
};

const LEVEL_LABEL: Record<VerificationReportLevel, string> = {
  CLEAR: 'No material issues found',
  CAUTION: 'Proceed with caution',
  CRITICAL: 'Serious concerns',
};

function fmtDate(value?: string | null): string {
  const ms = value ? Date.parse(value) : NaN;
  return Number.isNaN(ms) ? '' : new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function ReportHeader({ report, logo, onDownloadPdf, downloadBusy }: Props) {
  const isFinal = String(report.report_type || '').toUpperCase() === 'FINAL';
  return (
    <>
      <header className="verify-report-header">
        {logo ? <img src={logo} alt="ClearTitle" className="verify-report-logo" /> : null}
        <div className="verify-report-headline">
          <div className="verify-report-titlerow">
            <h3 className="verify-report-title">Title verification report</h3>
            <span className={`verify-report-type ${isFinal ? 'is-final' : 'is-preliminary'}`}>
              {isFinal ? 'Final report' : 'Preliminary report'}
            </span>
          </div>
          <p className="verify-report-date">Generated {fmtDate(report.generated_at)}</p>
        </div>
        {onDownloadPdf ? (
          <button className="btn btn-primary" onClick={onDownloadPdf} disabled={downloadBusy}>
            <Download size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
            {downloadBusy ? 'Preparing…' : 'Download PDF'}
          </button>
        ) : null}
      </header>
      {report.stale ? (
        <div className="verify-report-stale">
          Verification results changed after this report was generated — regenerate it for the current state.
        </div>
      ) : null}
    </>
  );
}

function ExaminedDocuments({ report }: { report: VerificationReport }) {
  if (!(report.documents_examined || []).length) return null;
  return (
    <section className="verify-report-section">
      <h4 className="verify-report-heading">Documents examined</h4>
      <ul className="verify-report-docs">
        {report.documents_examined.map((doc, i) => (
          <li key={i}>
            {doc.filename}
            {doc.document_type ? <span className="verify-report-doctype"> · {doc.document_type}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

const DISCLAIMER = 'This report describes the verification recorded in this case on the generation date. It is not a legal opinion or a guarantee of title.';

/** Schema 3.0: the application's facts, then a markdown interpretation written for this case. */
function DueDiligenceReport({ report, ...header }: Props) {
  const level = report.verdict?.level || 'CAUTION';
  const counts = report.counts || {};
  const chain = report.chain || [];
  const withType = chain.some(row => row.property_type);
  const markdown = report.narrative_markdown || '';
  return (
    <div className="verify-report" data-testid="verification-report">
      <ReportHeader report={report} {...header} />

      <div className={`verify-report-banner is-${level.toLowerCase()}`} role="status">
        <span className="verify-report-banner-level">{LEVEL_LABEL[level]}</span>
        <p className="verify-report-banner-headline">{report.verdict?.headline}</p>
        <div className="verify-report-chips">
          <span className="verify-report-chip is-clear">{counts.verified ?? 0} verified</span>
          <span className="verify-report-chip is-critical">{counts.issues ?? 0} with issues</span>
          <span className="verify-report-chip is-caution">{counts.awaiting ?? 0} awaiting documents</span>
        </div>
      </div>

      {(report.property?.rows || []).length > 0 ? (
        <section className="verify-report-section">
          <h4 className="verify-report-heading">The property</h4>
          <dl className="verify-report-schedule">
            {report.property!.rows.map((row, i) => (
              <div className="verify-report-schedule-row" key={i}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {chain.length > 0 ? (
        <section className="verify-report-section">
          <h4 className="verify-report-heading">Title chain at a glance</h4>
          <div className="verify-report-table-wrap">
            <table className="verify-report-chain">
              <thead>
                <tr>
                  <th>#</th><th>Date</th><th>Transfer</th>{withType ? <th>Property</th> : null}<th>Result</th>
                </tr>
              </thead>
              <tbody>
                {chain.map(row => (
                  <tr key={row.sequence}>
                    <td>{row.sequence}</td>
                    <td>{row.date || '—'}</td>
                    <td>
                      <strong>{row.transaction_type}</strong>
                      {row.registration ? <span className="verify-report-doctype"> ({row.registration})</span> : null}
                      {(row.from.length || row.to.length) ? (
                        <div className="verify-report-parties">
                          {[row.from.join(', '), row.to.join(', ')].filter(Boolean).join(' → ')}
                        </div>
                      ) : null}
                    </td>
                    {withType ? <td>{row.property_type || '—'}</td> : null}
                    <td>
                      <span className={`verify-report-result is-${row.result.level.toLowerCase()}`}>{row.result.label}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {markdown ? (
        <section className="verify-report-section">
          {/* The narrative brings its own headings when it starts with one. */}
          {markdown.trimStart().startsWith('#') ? null : <h4 className="verify-report-heading">What this means for you</h4>}
          <ReportMarkdown markdown={markdown} />
        </section>
      ) : null}

      {(report.documents_needed || []).length > 0 ? (
        <section className="verify-report-section">
          <h4 className="verify-report-heading">Documents still needed</h4>
          <div className="verify-report-table-wrap">
            <table className="verify-report-chain">
              <thead><tr><th>Document</th><th>Why it is needed</th><th>For</th></tr></thead>
              <tbody>
                {report.documents_needed!.map((item, i) => (
                  <tr key={i}><td>{item.document}</td><td>{item.reason}</td><td>{item.for}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <ExaminedDocuments report={report} />
      <p className="verify-report-disclaimer">{DISCLAIMER}</p>
    </div>
  );
}

/** Schema 2.0: reports saved before the redesign keep displaying until they are regenerated. */
function LegacyReport({ report, ...header }: Props) {
  return (
    <div className="verify-report" data-testid="verification-report">
      <ReportHeader report={report} {...header} />

      <section className="verify-report-section">
        <h4 className="verify-report-heading">Schedule of property</h4>
        <dl className="verify-report-schedule">
          {(report.schedule || []).filter(row => row.value).map((row, i) => (
            <div className="verify-report-schedule-row" key={i}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <ExaminedDocuments report={report} />

      <section className="verify-report-section">
        <h4 className="verify-report-heading">Findings</h4>
        <div className="verify-report-chips">
          <span className="verify-report-chip is-critical">{report.counts?.critical ?? 0} Critical</span>
          <span className="verify-report-chip is-caution">{report.counts?.caution ?? 0} To resolve</span>
          <span className="verify-report-chip is-clear">{report.counts?.clear ?? 0} Clear</span>
        </div>
        <div className="verify-report-cards">
          {(report.findings || []).map((finding, i) => {
            const meta = SEVERITY_META[finding.severity] || SEVERITY_META.CAUTION;
            return (
              <article className={`verify-report-card is-${finding.severity.toLowerCase()}`} key={i}
                       style={{ borderLeftColor: meta.bar, background: meta.bg }}>
                <span className="verify-report-card-chip" style={{ color: meta.chip }}>{meta.label}</span>
                <h5 className="verify-report-card-title">{finding.title}</h5>
                <p className="verify-report-card-detail">{finding.detail}</p>
              </article>
            );
          })}
          {(report.findings || []).length === 0 ? (
            <p className="verify-report-card-detail">No issues were identified in the completed verifications.</p>
          ) : null}
        </div>
      </section>

      {(report.cannot_verify || []).length > 0 ? (
        <section className="verify-report-section">
          <h4 className="verify-report-heading">What this report could not verify</h4>
          <ul className="verify-report-limits">
            {report.cannot_verify!.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </section>
      ) : null}

      <section className="verify-report-section">
        <h4 className="verify-report-heading">Opinion</h4>
        <p className="verify-report-verdict">{report.opinion?.verdict_line}</p>
        <p className="verify-report-summary">{report.opinion?.summary}</p>
        {(report.opinion?.conditions || []).length > 0 ? (
          <ol className="verify-report-conditions">
            {report.opinion!.conditions.map((condition, i) => <li key={i}>{condition}</li>)}
          </ol>
        ) : null}
        <p className="verify-report-disclaimer">{DISCLAIMER}</p>
      </section>
    </div>
  );
}

export function VerificationReportView(props: Props) {
  return props.report.narrative_markdown !== undefined
    ? <DueDiligenceReport {...props} />
    : <LegacyReport {...props} />;
}
