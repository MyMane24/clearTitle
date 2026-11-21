import React from 'react';
import { History } from 'lucide-react';
import type { DueDiligenceReport, ReportOpinion } from '../../api/backend';
import type { CaseIssue } from './issues';

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

/** Drops a leading internal id ("PA-TC-0002 — ", "I2 — ") the writer may put in a title. */
export function cleanTitle(title: string): string {
  return title.replace(/^(?:[A-Z]{2}-TC-\d+|VL-\d+|DOC_\d+|[ILR]\d+)\s*[—–:-]\s*/, '');
}

/** A titled part of the report: a heading, an optional note, and its content. */
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

const BADGE: Record<CaseIssue['severity'], { badge: string; tone: string }> = {
  high: { badge: 'Critical', tone: 'bad' },
  medium: { badge: 'Caution', tone: 'warn' },
  low: { badge: 'Note', tone: 'neutral' },
  clear: { badge: 'Clear', tone: 'good' },
};

/** The opinion and at most two short reasons, shown at the top of the page. */
export function Opinion({ report, label }: { report: DueDiligenceReport; label: Label }) {
  const opinion = OPINION[report.opinion];
  return (
    <section className={`cr-opinion cr-tone-${opinion.tone}`} aria-label="Opinion">
      <p className="cr-opinion-label">Opinion</p>
      <p className="cr-opinion-verdict">{opinion.label}</p>
      {report.opinion_reasons.length > 0 && (
        <ul className="cr-reasons">
          {report.opinion_reasons.map((reason, i) => <li key={i}>{label(reason.text)}</li>)}
        </ul>
      )}
      {report.changes_since_previous.length > 0 && (
        <details className="cr-changes">
          <summary><History size={13} /> What changed since version {report.version - 1}</summary>
          <ul>{report.changes_since_previous.map((change, i) => <li key={i}>{label(change)}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

/** Findings on one page: count chips, then one short card per finding, problems first. */
export function FindingsList({ issues, label }: { issues: CaseIssue[]; label: Label }) {
  const count = (severity: CaseIssue['severity']) => issues.filter(issue => issue.severity === severity).length;
  const chips = [
    { n: count('high'), text: 'critical', tone: 'bad' },
    { n: count('medium'), text: 'to resolve', tone: 'warn' },
    { n: count('low'), text: count('low') === 1 ? 'note' : 'notes', tone: 'neutral' },
    { n: count('clear'), text: 'clear', tone: 'good' },
  ].filter(chip => chip.n > 0);
  return (
    <Section id="cr-findings-title" title="Findings">
      {issues.length === 0 ? (
        <p className="cr-muted">No findings were recorded for the documents examined.</p>
      ) : (
        <>
          <p className="cr-chips">
            {chips.map(chip => <span key={chip.text} className={`cr-chip cr-tone-${chip.tone}`}>{chip.n} {chip.text}</span>)}
          </p>
          <div className="cr-cards">
            {issues.map((issue, i) => {
              const badge = BADGE[issue.severity] || BADGE.low;
              return (
                <article key={i} className={`cr-card cr-tone-${badge.tone}`}>
                  <header>
                    <span className={`cr-badge cr-tone-${badge.tone}`}>{badge.badge}</span>
                    <h4>{label(cleanTitle(issue.title))}</h4>
                  </header>
                  <p>{label(issue.text)}</p>
                </article>
              );
            })}
          </div>
        </>
      )}
    </Section>
  );
}
