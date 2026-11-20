import React from 'react';
import { AlertTriangle, ChevronDown } from 'lucide-react';
import type { ChainTransaction, VerificationLink } from '../../api/backend';
import { VERDICT, humanizeType } from './labels';

/** One row of the timeline, from the verified chain or, before verification, the draft chain. */
export interface TimelineLink {
  id: string;
  transaction: ChainTransaction;
  continuesPrevious: boolean;
  addedByVerification?: boolean;
  breakNote?: string | null;
  verdict?: VerificationLink['verdict'];
}

/** The verified chain when verification has run, otherwise Phase A's draft chain. */
export function timelineLinks(verified: VerificationLink[] | undefined, draft: unknown): TimelineLink[] {
  if (verified && verified.length) {
    return verified.map(link => ({
      id: link.link_id,
      transaction: link.transaction,
      continuesPrevious: link.continues_previous,
      addedByVerification: link.origin === 'verification',
      breakNote: link.break_note,
      verdict: link.verdict,
    }));
  }
  if (!Array.isArray(draft)) return [];
  return draft
    .filter(item => item && typeof item === 'object' && (item as any).documented_transaction)
    .map((item: any, index) => ({
      id: String(item.tx_id || index + 1),
      transaction: item.documented_transaction as ChainTransaction,
      continuesPrevious: Boolean(item.continues_previous),
    }));
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

type Label = (text: string) => string;

const plain: Label = text => text;

/** The title chain as a compact timeline, earliest first; details open per transfer. */
export function ChainTimeline({ links, label = plain }: { links: TimelineLink[]; label?: Label }) {
  if (!links.length) return <p className="cr-muted">The title chain is not available yet.</p>;
  return (
    <ol className="cr-timeline">
      {links.map((link, index) => {
        const t = link.transaction;
        const verdict = link.verdict ? VERDICT[link.verdict.verdict] : undefined;
        const date = t.executed_date || t.registration_date || 'Undated';
        return (
          <li key={link.id}>
            {index > 0 && !link.continuesPrevious && (
              <div className="cr-break"><AlertTriangle size={13} /> Break in the chain{link.breakNote ? `: ${label(link.breakNote)}` : ''}</div>
            )}
            <details className="cr-link">
              <summary>
                <span className="cr-link-date">{date}</span>
                <span className="cr-link-main">
                  <b>{humanizeType(t.transaction_type)}</b>
                  <span className="cr-muted">{(t.transferors || []).join(', ') || 'Earlier owner'} → {(t.transferees || []).join(', ') || 'Acquirer not recorded'}</span>
                </span>
                <span className="cr-link-tags">
                  {link.addedByVerification && <span className="cr-status cr-tone-neutral">Added by verification</span>}
                  {verdict && <span className={`cr-status cr-tone-${verdict.tone}`}>{verdict.label}</span>}
                </span>
                <ChevronDown size={14} className="cr-chevron" />
              </summary>
              <div className="cr-link-body">
                {link.verdict && <p>{label(link.verdict.summary)}</p>}
                <dl className="cr-facts">
                  <Detail label="Registration no." value={t.transaction_number} />
                  <Detail label="Evidence" value={t.evidence_status ? humanizeType(t.evidence_status) : null} />
                  <Detail label="Sources" value={(t.source_refs || []).map(ref => ref.filename).join(', ')} />
                </dl>
                {link.verdict?.checks && link.verdict.checks.length > 0 && (
                  <ul className="cr-checks">
                    {link.verdict.checks.map((check, i) => (
                      <li key={i}><b>{label(check.check)}</b> <span className={`cr-dot cr-tone-${check.status === 'ok' ? 'good' : check.status === 'failed' ? 'bad' : check.status === 'concern' ? 'warn' : 'neutral'}`} /> {label(check.note)}</li>
                    ))}
                  </ul>
                )}
              </div>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
