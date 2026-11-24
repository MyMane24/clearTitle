import React from 'react';
import { History } from 'lucide-react';
import type { DueDiligenceReport, ReportOpinion } from '../../api/backend';

const OPINION: Record<ReportOpinion, { label: string; tone: string }> = {
  CLEAR: { label: 'Title clear', tone: 'good' },
  CLEAR_SUBJECT_TO: { label: 'Clear, subject to conditions', tone: 'warn' },
  NOT_CLEAR: { label: 'Title not clear', tone: 'bad' },
};

export function opinionLabel(opinion: ReportOpinion): string {
  return OPINION[opinion].label;
}

export function opinionTone(opinion: ReportOpinion): string {
  return OPINION[opinion].tone;
}

type Label = (ref: string) => string;

/** A titled part of the page: a heading, an optional note, and its content. */
export function Section({ id, title, aside, note, children }: {
  id?: string;
  title: string;
  aside?: React.ReactNode;
  note?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="cr-section" aria-labelledby={id}>
      <header className="cr-section-head">
        <h2 id={id}>{title}</h2>
        {aside && <span className="cr-section-aside">{aside}</span>}
      </header>
      {note && <p className="cr-section-note">{note}</p>}
      {children}
    </section>
  );
}

/** The opinion in one line, its reasons, and what changed since the previous version. */
export function Opinion({ report, label }: { report: DueDiligenceReport; label: Label }) {
  const opinion = OPINION[report.opinion];
  return (
    <section className={`cr-opinion cr-tone-${opinion.tone}`} aria-label="Opinion">
      <p className="cr-opinion-label">Opinion</p>
      <p className="cr-opinion-verdict">{opinion.label}</p>
      {report.reasons.length > 0 && (
        <ul className="cr-reasons">
          {report.reasons.map((reason, i) => <li key={i}>{label(reason)}</li>)}
        </ul>
      )}
      {report.changes.length > 0 && (
        <details className="cr-changes">
          <summary><History size={13} /> What changed since version {report.version - 1}</summary>
          <ul>{report.changes.map((change, i) => <li key={i}>{label(change)}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

const SIDES = ['east', 'west', 'north', 'south'] as const;

/** The Report of Investigation of Title, laid out like the downloadable PDF. */
export function TitleReport({ report, label }: { report: DueDiligenceReport; label: Label }) {
  const documents = report.documents || [];
  if (!documents.length) {
    return (
      <p className="cr-muted">
        This report was written in an older format. Run verification again for the full report.
      </p>
    );
  }
  const bounds = SIDES.filter(side => report.boundaries?.[side]);
  const prepared = report.prepared_on ? new Date(report.prepared_on).toLocaleDateString('en-GB') : '';
  return (
    <article className="cr-report" aria-label="Report of Investigation of Title">
      <h2 className="cr-report-title">Report of Investigation of Title in respect of Immovable Property</h2>

      <h3>I. Particulars of the title holder and the immovable property in respect of which this opinion is given</h3>
      <table>
        <tbody>
          <tr>
            <td>A.</td>
            <td>Name of the person holding title to the immovable property</td>
            <td>{(report.title_holders || []).map(label).join(', ')}</td>
          </tr>
          <tr>
            <td>B.</td>
            <td>Complete description of the immovable property</td>
            <td>
              <p>{label(report.property_description || '')}</p>
              {bounds.length > 0 && (
                <p className="cr-report-bounds">
                  {bounds.map(side => (
                    <span key={side}><b>{side.charAt(0).toUpperCase() + side.slice(1)}</b> : {label(report.boundaries![side]!)}</span>
                  ))}
                </p>
              )}
              <p>(Hereinafter referred to as the Property Under Opinion)</p>
            </td>
          </tr>
        </tbody>
      </table>

      <h3>II. Particulars of the documents scrutinised, serially and chronologically</h3>
      <table>
        <thead>
          <tr><th>Sl. No.</th><th>Date of Document</th><th>Nature of Document</th><th>Original / Certified / Copy</th></tr>
        </thead>
        <tbody>
          {documents.map((row, i) => (
            <tr key={row.doc_id}><td>{i + 1}.</td><td>{row.date}</td><td>{label(row.nature)}</td><td>Scanned copy</td></tr>
          ))}
        </tbody>
      </table>

      <h3>III. Details of documents scrutinised</h3>
      {(report.document_details || []).map(detail => <p key={detail.doc_id} className="cr-report-para">{label(detail.text)}</p>)}

      <h3>IV. History of title</h3>
      {(report.history || []).map((paragraph, i) => <p key={i} className="cr-report-para">{label(paragraph)}</p>)}

      <h3>V. Certificate</h3>
      <p className="cr-report-para">{label(report.certificate || '')}</p>

      <h3>Annexure: documents still required</h3>
      {report.documents_required?.length ? (
        <ol className="cr-report-annexure">
          {report.documents_required.map((item, i) => <li key={i}><b>{label(item.document)}</b>: {label(item.reason)}</li>)}
        </ol>
      ) : <p>None.</p>}

      <footer className="cr-report-sign">
        <div><p>Prepared by ClearTitle</p>{prepared && <p>Date: {prepared}</p>}</div>
        <div><p>To be reviewed and signed by an advocate.</p></div>
      </footer>
    </article>
  );
}
