import React from 'react';
import { Download } from 'lucide-react';

import type { VerificationReport } from '../api/backend';

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

function fmtDate(value?: string | null): string {
  const ms = value ? Date.parse(value) : NaN;
  return Number.isNaN(ms) ? '' : new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function VerificationReportView({ report, logo, onDownloadPdf, downloadBusy }: Props) {
  const isFinal = String(report.report_type || '').toUpperCase() === 'FINAL';
  return (
    <div className="verify-report" data-testid="verification-report">
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

      {(report.documents_examined || []).length > 0 ? (
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
      ) : null}

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
            {report.cannot_verify.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </section>
      ) : null}

      <section className="verify-report-section">
        <h4 className="verify-report-heading">Opinion</h4>
        <p className="verify-report-verdict">{report.opinion?.verdict_line}</p>
        <p className="verify-report-summary">{report.opinion?.summary}</p>
        {(report.opinion?.conditions || []).length > 0 ? (
          <ol className="verify-report-conditions">
            {report.opinion.conditions.map((condition, i) => <li key={i}>{condition}</li>)}
          </ol>
        ) : null}
        <p className="verify-report-disclaimer">
          This report describes the verification recorded in this case on the generation date. It is not a legal
          opinion or a guarantee of title.
        </p>
      </section>
    </div>
  );
}
