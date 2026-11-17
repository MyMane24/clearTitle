import React from 'react';
import { AlertTriangle, CheckCircle2, FileText, History, XCircle } from 'lucide-react';
import type { DueDiligenceReport as Report, ReportBlock, ReportOpinion } from '../../api/backend';

const OPINION: Record<ReportOpinion, { label: string; tone: string; Icon: typeof CheckCircle2 }> = {
  CLEAR: { label: 'Title clear', tone: 'clear', Icon: CheckCircle2 },
  CLEAR_SUBJECT_TO: { label: 'Clear, subject to conditions', tone: 'subject', Icon: AlertTriangle },
  NOT_CLEAR: { label: 'Title not clear', tone: 'not-clear', Icon: XCircle },
};

function Refs({ refs }: { refs?: string[] }) {
  if (!refs || !refs.length) return null;
  return <span className="vf-refs">{refs.join(' · ')}</span>;
}

function Block({ block }: { block: ReportBlock }) {
  switch (block.type) {
    case 'paragraph':
      return <p className="vf-report-paragraph">{block.text} <Refs refs={block.refs} /></p>;
    case 'list':
      return (
        <ul className="vf-report-list">
          {block.items.map((item, i) => <li key={i}>{item.text} <Refs refs={item.refs} /></li>)}
        </ul>
      );
    case 'table':
      return (
        <div className="vf-table-wrap">
          <table className="vf-report-table">
            <thead><tr>{block.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'findings':
      return (
        <div className="vf-findings">
          {block.items.map((item, i) => (
            <article key={i} className={`vf-finding${item.severity ? ` vf-sev-${item.severity}` : ''}`}>
              <header>
                <h4>{item.title}</h4>
                {item.severity && <span className={`vf-badge vf-sev-${item.severity}`}>{item.severity}</span>}
                {item.status && <span className="vf-badge">{item.status.replace(/_/g, ' ')}</span>}
              </header>
              <p>{item.text} <Refs refs={item.refs} /></p>
            </article>
          ))}
        </div>
      );
    default:
      return null;
  }
}

/** The lawyer-style due diligence report. Renders any section the backend sends. */
export function DueDiligenceReport({ report }: { report: Report }) {
  const opinion = OPINION[report.opinion];
  return (
    <section className="vf-report" aria-labelledby="vf-report-title">
      <header className="vf-report-header">
        <div>
          <span className="vf-kicker"><FileText size={13} /> DUE DILIGENCE REPORT · VERSION {report.version}</span>
          <h2 id="vf-report-title">Title verification report</h2>
          <p>{report.property_summary}</p>
        </div>
      </header>
      <div className={`vf-opinion vf-opinion-${opinion.tone}`}>
        <opinion.Icon size={20} />
        <div>
          <strong>Opinion: {opinion.label}</strong>
          <ul>
            {report.opinion_reasons.map((reason, i) => <li key={i}>{reason.text} <Refs refs={reason.refs} /></li>)}
          </ul>
        </div>
      </div>
      {report.changes_since_previous.length > 0 && (
        <div className="vf-changes">
          <h3><History size={15} /> Changes since version {report.version - 1}</h3>
          <ul>{report.changes_since_previous.map((change, i) => <li key={i}>{change}</li>)}</ul>
        </div>
      )}
      {report.sections.map((section, index) => (
        <section key={section.id} className="vf-report-section" aria-labelledby={`vf-section-${section.id}`}>
          <h3 id={`vf-section-${section.id}`}>{index + 1}. {section.title}</h3>
          {section.blocks.map((block, i) => <Block key={i} block={block} />)}
        </section>
      ))}
      <p className="vf-disclaimer">
        Prepared by an automated verification agent from the documents provided. Every finding
        cites its source; review the cited documents before relying on this report.
      </p>
    </section>
  );
}
