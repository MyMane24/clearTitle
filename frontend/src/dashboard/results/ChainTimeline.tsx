import React from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, XCircle } from 'lucide-react';
import type { ChainTransaction, VerificationTransfer } from '../../api/backend';
import { VERDICT, humanizeType, yearOf } from './labels';

/** One row of the timeline: a transfer, with its verification record when there is one. */
export interface TimelineLink {
  id: string;
  transaction: ChainTransaction;
  record?: VerificationTransfer;
}

/** The transfers being verified, each with its record. Before verification starts, the
 * Phase A chain is shown instead. */
export function timelineLinks(transfers: VerificationTransfer[] | undefined, draft: unknown): TimelineLink[] {
  if (transfers?.length) {
    return transfers.map(transfer => ({ id: transfer.id, transaction: transfer.transaction, record: transfer }));
  }
  const phaseA = Array.isArray(draft)
    ? draft.filter(item => item && typeof item === 'object' && (item as any).documented_transaction)
    : [];
  return phaseA.map((item: any, index) => ({
    id: String(item.tx_id || index + 1),
    transaction: item.documented_transaction as ChainTransaction,
  }));
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

type Label = (text: string) => string;

const plain: Label = text => text;

const SEVERITY: Record<string, { badge: string; tone: string }> = {
  high: { badge: 'Critical', tone: 'bad' },
  medium: { badge: 'Caution', tone: 'warn' },
  low: { badge: 'Note', tone: 'neutral' },
};

/** The title chain as a vertical timeline, earliest first; each transfer opens for its record. */
export function ChainTimeline({ links, label = plain }: { links: TimelineLink[]; label?: Label }) {
  if (!links.length) return <p className="cr-muted">The title chain is not available yet.</p>;
  return (
    <ol className="cr-timeline">
      {links.map(link => {
        const t = link.transaction;
        const record = link.record;
        const verdict = record?.result ? VERDICT[record.result] : undefined;
        const date = t.executed_date || t.registration_date || '';
        const year = yearOf(date);
        const broken = record?.connects && !record.connects.ok;
        return (
          <li key={link.id} className={`cr-tl-item cr-tone-${verdict?.tone || 'neutral'}`}>
            {broken && (
              <div className="cr-break"><AlertTriangle size={13} /> Break in the chain: {label(record!.connects!.note)}</div>
            )}
            <details className="cr-link">
              <summary>
                <span className="cr-tl-dot" aria-hidden="true" />
                <span className="cr-link-date">
                  <b>{year}</b>
                  {date && date !== year && <small>{date}</small>}
                </span>
                <span className="cr-link-main">
                  <b>{humanizeType(t.transaction_type)}</b>
                  <span className="cr-muted">{(t.transferors || []).join(', ') || 'Earlier owner'} → {(t.transferees || []).join(', ') || 'Acquirer not recorded'}</span>
                </span>
                <span className="cr-link-tags">
                  {record?.origin === 'verification' && <span className="cr-type">Added during verification</span>}
                  {record?.property?.type && <span className="cr-type">{humanizeType(record.property.type)}</span>}
                  {record?.before_root && <span className="cr-type">Before the 30-year search</span>}
                  {verdict && <span className={`cr-status cr-tone-${verdict.tone}`}>{verdict.label}</span>}
                </span>
                <ChevronDown size={15} className="cr-chevron" />
              </summary>
              <div className="cr-link-body">
                {record?.summary && <p>{label(record.summary)}</p>}
                {record?.added_because && <p className="cr-muted">Why it was added: {label(record.added_because.note)}</p>}
                <dl className="cr-facts">
                  <Detail label="Survey" value={record?.property?.survey || t.survey_number} />
                  <Detail label="Extent" value={record?.property?.extent ? label(record.property.extent) : null} />
                  <Detail label="Registration no." value={t.transaction_number} />
                  <Detail label="Sources" value={(t.source_refs || []).map(ref => ref.filename).join(', ')} />
                </dl>
                {record && record.documents.length > 0 && (
                  <ul className="cr-proof" aria-label="Documents that prove this transfer">
                    {record.documents.map((doc, i) => (
                      <li key={i}>
                        {doc.status === 'found' ? <CheckCircle2 size={14} className="cr-proof-found" /> : <XCircle size={14} className="cr-proof-missing" />}
                        <span><b>{label(doc.name)}</b> {label(doc.proves)}</span>
                        <span className={`cr-status cr-tone-${doc.status === 'found' ? 'good' : 'warn'}`}>{doc.status === 'found' ? 'Found' : 'Needed'}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {record && record.concerns.length > 0 && (
                  <ul className="cr-concerns" aria-label="Concerns">
                    {record.concerns.map((concern, i) => {
                      const severity = SEVERITY[concern.severity] || SEVERITY.low;
                      return (
                        <li key={i}>
                          <span className={`cr-badge cr-tone-${severity.tone}`}>{severity.badge}</span>
                          <span>{label(concern.text)}</span>
                        </li>
                      );
                    })}
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
