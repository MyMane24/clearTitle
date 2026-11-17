import React from 'react';
import { CheckCircle2, Clock, Upload } from 'lucide-react';
import type { VerificationRequisition } from '../../api/backend';

/** Documents the agent needs. Each open one can be uploaded on its own. */
export function Requisitions({
  requisitions,
  busyId,
  disabled,
  onUpload,
}: {
  requisitions: VerificationRequisition[];
  busyId: string | null;
  disabled: boolean;
  onUpload: (requisitionId: string, file: File) => void;
}) {
  if (!requisitions.length) return null;
  return (
    <div className="vf-requisitions">
      <h3>Documents needed</h3>
      <p className="vf-muted">
        Verification continued without these. Upload one and only the checks it affects are re-run.
      </p>
      <ul>
        {requisitions.map(item => (
          <li key={item.id} className={`vf-requisition vf-req-${item.status}`}>
            <div>
              <strong>{item.id} · {item.document}</strong>
              <span className="vf-muted">{item.reason}</span>
            </div>
            {item.status === 'open' && (
              <label className={`btn btn-secondary${disabled ? ' vf-disabled' : ''}`}>
                <Upload size={14} /> {busyId === item.id ? 'Uploading…' : 'Upload'}
                <input
                  type="file"
                  accept="application/pdf"
                  hidden
                  disabled={disabled}
                  onChange={event => {
                    const file = event.target.files?.[0];
                    if (file) onUpload(item.id, file);
                    event.target.value = '';
                  }}
                />
              </label>
            )}
            {item.status === 'fulfilled' && <span className="vf-badge"><Clock size={12} /> Received, being verified</span>}
            {item.status === 'resolved' && <span className="vf-badge vf-ok"><CheckCircle2 size={12} /> Settled</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
