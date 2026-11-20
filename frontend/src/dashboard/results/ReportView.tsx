import React from 'react';
import { History } from 'lucide-react';
import type { DueDiligenceReport, ReportOpinion } from '../../api/backend';
import type { CaseIssue } from './issues';
import { verdictTone } from './labels';

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

const MAX_REFS = 6;

function Refs({ refs, label }: { refs?: string[]; label: Label }) {
  if (!refs || !refs.length) return null;
  const shown = refs.slice(0, MAX_REFS);
  return (
    <span className="cr-refs" title={refs.map(label).join(', ')}>
      {shown.map(ref => <span key={ref} className="cr-ref">{label(ref)}</span>)}
      {refs.length > MAX_REFS && <span className="cr-ref">+{refs.length - MAX_REFS} more</span>}
    </span>
  );
}

/** Drops a leading internal id ("PA-TC-0002 — ", "I2 — ") the writer may put in a title. */
export function cleanTitle(title: string): string {
  return title.replace(/^(?:[A-Z]{2}-TC-\d+|VL-\d+|DOC_\d+|[ILR]\d+)\s*[—–:-]\s*/, '');
}

function sentenceCase(text: string): string {
  const plain = text.replace(/_/g, ' ').toLowerCase();
  return plain.charAt(0).toUpperCase() + plain.slice(1);
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

/** One finding: a number, its title and status, and the reasoning behind it. */
function Finding({ index, title, text, tone, tags, refs, label }: {
  index?: string;
  title: string;
  text: string;
  tone: string;
  tags: string[];
  refs?: string[];
  label: Label;
}) {
  return (
    <article className="cr-finding">
      {index && <span className="cr-finding-index">{index}</span>}
      <div className="cr-finding-main">
        <header>
          <h4>{label(cleanTitle(title))}</h4>
          <span className="cr-finding-tags">
            {tags.map(tag => <span key={tag} className={`cr-status cr-tone-${tone}`}>{tag}</span>)}
          </span>
        </header>
        <p>{label(text)} <Refs refs={refs} label={label} /></p>
      </div>
    </article>
  );
}

/** The opinion and its reasons, shown at the top of the page. */
export function Opinion({ report, label }: { report: DueDiligenceReport; label: Label }) {
  const opinion = OPINION[report.opinion];
  return (
    <section className={`cr-opinion cr-tone-${opinion.tone}`} aria-label="Opinion">
      <p className="cr-opinion-label">Opinion</p>
      <p className="cr-opinion-verdict">{opinion.label}</p>
      {report.opinion_reasons.length > 0 && (
        <ol className="cr-reasons">
          {report.opinion_reasons.map((reason, i) => (
            <li key={i}>{label(reason.text)} <Refs refs={reason.refs} label={label} /></li>
          ))}
        </ol>
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

/** Every problem a buyer must know about, most serious first. */
export function IssuesList({ issues, label }: { issues: CaseIssue[]; label: Label }) {
  return (
    <Section
      id="cr-issues-title"
      title="Issues identified"
      aside={issues.length ? `${issues.length} ${issues.length === 1 ? 'finding' : 'findings'}` : 'None'}
    >
      {issues.length === 0 ? (
        <p className="cr-muted">No issues were found in the documents examined.</p>
      ) : (
        <div className="cr-findings">
          {issues.map((issue, i) => (
            <Finding
              key={i}
              index={String(i + 1).padStart(2, '0')}
              title={issue.title}
              text={issue.text}
              tone={verdictTone(issue.severity)}
              tags={[sentenceCase(issue.severity)]}
              refs={issue.refs.filter(ref => !/^I\d+$/.test(ref))}
              label={label}
            />
          ))}
        </div>
      )}
    </Section>
  );
}
