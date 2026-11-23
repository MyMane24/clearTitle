import React from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, XCircle } from 'lucide-react';
import type { ChainTransaction, VerificationLink } from '../../api/backend';
import { VERDICT, humanizeType, yearOf } from './labels';

/** One row of the timeline: a transfer of the Phase A chain, with its verification verdict. */
export interface TimelineLink {
  id: string;
  transaction: ChainTransaction;
  continuesPrevious: boolean;
  breakNote?: string | null;
  verdict?: VerificationLink['verdict'];
}

/** The title chain as Phase A built it, each transfer carrying its verification result when
 * there is one. Without a Phase A chain, the verified chain is shown instead. */
export function timelineLinks(verified: VerificationLink[] | undefined, draft: unknown): TimelineLink[] {
  const byId = new Map((verified || []).map(link => [link.link_id, link]));
  const phaseA = Array.isArray(draft)
    ? draft.filter(item => item && typeof item === 'object' && (item as any).documented_transaction)
    : [];
  if (!phaseA.length) {
    return (verified || []).map(link => ({
      id: link.link_id,
      transaction: link.transaction,
      continuesPrevious: link.continues_previous,
      breakNote: link.break_note,
      verdict: link.verdict,
    }));
  }
  return phaseA.map((item: any, index) => {
    const id = String(item.tx_id || index + 1);
    const checked = byId.get(id);
    return {
      id,
      transaction: item.documented_transaction as ChainTransaction,
      continuesPrevious: Boolean(item.continues_previous),
      breakNote: checked?.break_note,
      verdict: checked?.verdict,
    };
  });
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

type Label = (text: string) => string;

const plain: Label = text => text;

/** The title chain as a vertical timeline, earliest first; each transfer opens for detail. */
export function ChainTimeline({ links, label = plain }: { links: TimelineLink[]; label?: Label }) {
  if (!links.length) return <p className="cr-muted">The title chain is not available yet.</p>;
  return (
    <ol className="cr-timeline">
      {links.map((link, index) => {
        const t = link.transaction;
        const verdict = link.verdict ? VERDICT[link.verdict.verdict] : undefined;
        const date = t.executed_date || t.registration_date || '';
        const year = yearOf(date);
        return (
          <li key={link.id} className={`cr-tl-item cr-tone-${verdict?.tone || 'neutral'}`}>
            {index > 0 && !link.continuesPrevious && (
              <div className="cr-break"><AlertTriangle size={13} /> Break in the chain{link.breakNote ? `: ${label(link.breakNote)}` : ''}</div>
            )}
            <details className="cr-link">
              <summary>
                <span className="cr-tl-dot" aria-hidden="true" />
                <span className="cr-link-date">
                  <b>{year || 'Undated'}</b>
                  {date && date !== year && <small>{date}</small>}
                </span>
                <span className="cr-link-main">
                  <b>{humanizeType(t.transaction_type)}</b>
                  <span className="cr-muted">{(t.transferors || []).join(', ') || 'Earlier owner'} → {(t.transferees || []).join(', ') || 'Acquirer not recorded'}</span>
                </span>
                <span className="cr-link-tags">
                  {link.verdict?.property_type && <span className="cr-type">{humanizeType(link.verdict.property_type)}</span>}
                  {verdict && <span className={`cr-status cr-tone-${verdict.tone}`}>{verdict.label}</span>}
                </span>
                <ChevronDown size={15} className="cr-chevron" />
              </summary>
              <div className="cr-link-body">
                {link.verdict && <p>{label(link.verdict.summary)}</p>}
                <dl className="cr-facts">
                  <Detail label="Extent" value={link.verdict?.extent ? label(link.verdict.extent) : null} />
                  <Detail label="Registration no." value={t.transaction_number} />
                  <Detail label="Evidence" value={t.evidence_status ? humanizeType(t.evidence_status) : null} />
                  <Detail label="Sources" value={(t.source_refs || []).map(ref => ref.filename).join(', ')} />
                </dl>
                {link.verdict?.needed_documents && link.verdict.needed_documents.length > 0 && (
                  <ul className="cr-proof" aria-label="Documents that prove this transfer">
                    {link.verdict.needed_documents.map((doc, i) => (
                      <li key={i}>
                        {doc.status === 'found' ? <CheckCircle2 size={14} className="cr-proof-found" /> : <XCircle size={14} className="cr-proof-missing" />}
                        <span><b>{label(doc.document)}</b> {label(doc.proves)}</span>
                        <span className={`cr-status cr-tone-${doc.status === 'found' ? 'good' : 'warn'}`}>{doc.status === 'found' ? 'Found' : 'Needed'}</span>
                      </li>
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
