import React from 'react';
import { Upload } from 'lucide-react';

export interface EvidenceRequest {
  document_type?: string;
  reason?: string;
  for_transaction?: string;
}

interface Props {
  transactionId: string;
  requirements: EvidenceRequest[];
  uploads: Record<number, File | undefined>;
  busy: boolean;
  onPick: (index: number, file: File | undefined) => void;
  onSubmit: () => void;
  onSkip?: () => void;
  title?: string;
  submitLabel?: string;
  skipLabel?: string;
}

// Evidence dialog: one upload slot per requested document, Submit resumes or
// retries verification, Skip (when offered) is an explicit guarded choice.
export function EvidenceRequestDialog({
  transactionId, requirements, uploads, busy, onPick, onSubmit, onSkip,
  title, submitLabel, skipLabel,
}: Props) {
  const slots = requirements.length ? requirements : [
    { document_type: 'Supporting document', reason: 'Upload the PDF that supports this transaction.' },
  ];
  const chosen = slots.filter((_, i) => uploads[i]).length;
  const submitText = submitLabel || 'Submit & resume verification';
  return (
    <div role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 20000, display: 'grid', placeItems: 'center', padding: 20, background: 'rgba(15, 23, 42, 0.56)' }}>
      <section role="dialog" aria-modal="true" aria-labelledby="evidence-upload-title" className="card" style={{ width: 'min(600px, 100%)', maxHeight: 'min(82vh, 740px)', overflowY: 'auto', border: '1px solid #f59e0b', background: '#fffbeb', boxShadow: '0 24px 80px rgba(0,0,0,.28)', padding: 24 }}>
        <h2 id="evidence-upload-title" style={{ margin: '0 0 8px', color: '#78350f' }}>{title || `Documents needed for ${transactionId}`}</h2>
        <p style={{ margin: '0 0 16px', color: '#57534e', lineHeight: 1.55 }}>
          Upload each requested document to its own slot, then press Submit — processing starts and verification resumes automatically with the next transaction.
        </p>
        <ul style={{ margin: '0 0 20px', padding: 0, listStyle: 'none', display: 'grid', gap: 10, maxHeight: '42vh', overflowY: 'auto' }}>
          {slots.map((item, index) => {
            const file = uploads[index];
            return (
              <li key={`${item.document_type}-${item.reason}-${index}`} style={{ padding: '12px 14px', border: `1px solid ${file ? '#34d399' : '#fcd34d'}`, borderRadius: 10, background: '#fff' }}>
                <strong style={{ display: 'block', marginBottom: 4, color: '#292524', lineHeight: 1.4 }}>{item.document_type || 'Required document'}</strong>
                {item.reason && <span style={{ display: 'block', color: '#57534e', fontSize: 13, lineHeight: 1.5 }}>{item.reason}</span>}
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                  <label className="btn" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: busy ? 'wait' : 'pointer', fontSize: 13, padding: '6px 10px' }}>
                    <Upload size={13} />
                    {file ? 'Replace file' : 'Upload PDF'}
                    <input
                      type="file"
                      accept="application/pdf,.pdf"
                      disabled={busy}
                      onChange={(e) => {
                        const picked = e.target.files?.[0];
                        e.target.value = '';
                        onPick(index, picked);
                      }}
                      style={{ display: 'none' }}
                    />
                  </label>
                  {file && (
                    <>
                      <span style={{ color: '#047857', fontSize: 13, fontWeight: 600, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>✓ {file.name}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${file.name}`}
                        title="Remove this file"
                        disabled={busy}
                        onClick={() => onPick(index, undefined)}
                        style={{ border: 'none', background: 'transparent', color: '#b91c1c', cursor: busy ? 'wait' : 'pointer', fontSize: 15, lineHeight: 1, padding: '2px 4px' }}
                      >
                        ✕
                      </button>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            disabled={busy || chosen === 0}
            onClick={onSubmit}
            title={chosen === 0 ? 'Upload at least one document first' : undefined}
          >
            {busy ? 'Working…' : chosen > 0 ? `${submitText} (${chosen})` : submitText}
          </button>
          {onSkip && <button className="btn" disabled={busy} onClick={onSkip}>{skipLabel || 'Skip this transaction'}</button>}
        </div>
      </section>
    </div>
  );
}
