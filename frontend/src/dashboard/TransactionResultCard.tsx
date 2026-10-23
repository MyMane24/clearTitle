import React from 'react';

import {
  requiredDocumentsForTransaction,
  transactionMetadataItems,
  transactionStatusLabel,
  transactionTitle,
  type TransactionVerificationResult,
} from './transactionResults';

type DocumentLabel = { doc_id: string; filename?: string };

type Props = {
  transaction: TransactionVerificationResult;
  documents?: DocumentLabel[];
  skipped?: boolean;
};

const documentIdPattern = /DOC_\d+/g;

function resolveDocumentRefs(text: string, documents: DocumentLabel[]): string {
  return text.replace(documentIdPattern, id => {
    const document = documents.find(item => item.doc_id === id);
    return document?.filename && !/^DOC_\d+\.pdf$/i.test(document.filename)
      ? `${id} (${document.filename})`
      : id;
  });
}

function evidenceLabel(ref: { doc_id: string; pages?: string | null }, documents: DocumentLabel[]): string {
  const document = documents.find(item => item.doc_id === ref.doc_id);
  const filename = document?.filename && !/^DOC_\d+\.pdf$/i.test(document.filename)
    ? ` (${document.filename})`
    : '';
  return `${ref.doc_id}${filename}${ref.pages ? ` · page${ref.pages.includes('-') ? 's' : ''} ${ref.pages}` : ''}`;
}

export function TransactionResultCard({ transaction, documents = [], skipped = false }: Props) {
  const requirements = requiredDocumentsForTransaction(transaction);
  const findings = Array.isArray(transaction.findings)
    ? transaction.findings.filter(finding => finding && typeof finding === 'object')
    : [];
  const metadata = transaction.transaction_metadata || {};
  const metadataItems = transactionMetadataItems(metadata);
  const skippedStatus = skipped || ['SKIPPED', 'SKIPPED_BY_USER'].includes(String(transaction.status).toUpperCase());
  const status = skippedStatus ? transactionStatusLabel('SKIPPED') : transactionStatusLabel(transaction.status);
  const statusClass = skippedStatus ? 'status-skipped' : `status-${String(transaction.status || 'PENDING').toLowerCase()}`;
  const summary = typeof transaction.summary === 'string' ? transaction.summary.trim() : '';

  return (
    <article className="verification-result-entry" data-testid="transaction-result-card">
      <header className="verification-result-header">
        <div className="verification-result-heading-copy">
          <h3>{transactionTitle(transaction)}</h3>
          {metadataItems.length > 0 && (
            <dl className="verification-result-metadata">
              {metadataItems.map(item => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <span
          className={`verification-status-badge ${statusClass}`}
          role="status"
          aria-label={`Verification status: ${status}`}
        >
          {status}
        </span>
      </header>

      <p className="verification-result-summary">
        {summary ? resolveDocumentRefs(summary, documents) : 'No summary was recorded for this transaction.'}
      </p>

      {findings.length > 0 && (
        <section aria-labelledby={`findings-heading-${transaction.tx_id}`} className="verification-findings">
          <h4 id={`findings-heading-${transaction.tx_id}`}>Key findings</h4>
          <ul className="verification-findings-list">
            {findings.map((finding, index) => (
              <li className="verification-finding-item" key={`${finding.title || 'finding'}-${index}`}>
                {finding.title && <strong>{finding.title}</strong>}
                {finding.details && <p>{resolveDocumentRefs(finding.details, documents)}</p>}
                {Array.isArray(finding.evidence) && finding.evidence.length > 0 && (
                  <ul className="verification-finding-evidence" aria-label={`Evidence for ${finding.title || 'finding'}`}>
                    {finding.evidence.filter(reference => reference && reference.doc_id).map((reference, refIndex) => (
                    <li key={`${reference.doc_id}-${reference.pages || ''}-${refIndex}`}>
                      {evidenceLabel(reference, documents)}
                    </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {requirements.length > 0 && (
        <section className="verification-evidence-needed" aria-label="Evidence still needed">
          <h4>Evidence needed</h4>
          <ul>
            {requirements.map((item, index) => (
              <li key={`${item.document_type}-${index}`}>
                <strong>{item.document_type}</strong>
                {item.reason && <p>{resolveDocumentRefs(item.reason, documents)}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
