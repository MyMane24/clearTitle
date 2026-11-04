import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type { FinalReportBlocker } from '../api/backend';

interface Props {
  blockers: FinalReportBlocker[];
  onClose: () => void;
}

// Blockers dialog: explains which transaction verifications are incomplete and
// exactly which documents each one still needs before a final report can be
// generated. Read-only — it points the user back to the case workflow.
export function FinalReportBlockersModal({ blockers, onClose }: Props) {
  return (
    <div role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 20000, display: 'grid', placeItems: 'center', padding: 20, background: 'rgba(15, 23, 42, 0.56)' }}>
      <section role="dialog" aria-modal="true" aria-labelledby="final-report-blockers-title" className="card" style={{ width: 'min(600px, 100%)', maxHeight: 'min(82vh, 740px)', overflowY: 'auto', border: '1px solid #fca5a5', background: '#fef2f2', boxShadow: '0 24px 80px rgba(0,0,0,.28)', padding: 24 }}>
        <h2 id="final-report-blockers-title" style={{ margin: '0 0 8px', color: '#991b1b', display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertTriangle size={18} /> Transaction verification incomplete
        </h2>
        <p style={{ margin: '0 0 16px', color: '#57534e', lineHeight: 1.55 }}>
          A final report cannot be generated yet because some transaction verifications are
          still incomplete or need additional evidence. Complete them on the case page, then
          try again.
        </p>
        <ul style={{ margin: '0 0 20px', padding: 0, listStyle: 'none', display: 'grid', gap: 10, maxHeight: '42vh', overflowY: 'auto' }}>
          {blockers.map((blocker, index) => (
            <li key={`${blocker.tx_id || blocker.sequence}-${index}`} style={{ padding: '12px 14px', border: '1px solid #fecaca', borderRadius: 10, background: '#fff' }}>
              <strong style={{ display: 'block', marginBottom: 4, color: '#292524', lineHeight: 1.4 }}>
                Transaction {blocker.sequence ?? '—'} — {blocker.transaction_type}
                <span style={{ display: 'inline-block', marginLeft: 8, padding: '1px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: '#fee2e2', color: '#b91c1c', verticalAlign: 'middle' }}>
                  {(blocker.status || '').replace(/_/g, ' ').toLowerCase() || 'pending'}
                </span>
              </strong>
              {blocker.note && <span style={{ display: 'block', color: '#57534e', fontSize: 13, lineHeight: 1.5, marginBottom: 4 }}>{blocker.note}</span>}
              {blocker.required_documents.length > 0 ? (
                <span style={{ display: 'block', color: '#57534e', fontSize: 13, lineHeight: 1.5 }}>
                  {blocker.required_documents.length === 1 ? 'Required document:' : 'Required documents:'}
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, listStyle: 'disc' }}>
                    {blocker.required_documents.map((doc, docIndex) => (
                      <li key={`${doc.document_type}-${docIndex}`} style={{ marginBottom: 2 }}>
                        {doc.document_type}{doc.reason ? ` — ${doc.reason}` : ''}
                      </li>
                    ))}
                  </ul>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={onClose}>Back to case</button>
        </div>
      </section>
    </div>
  );
}
