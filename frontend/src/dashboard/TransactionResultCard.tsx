import React from 'react';

import {
  citedDocumentsForTransaction,
  reportSections,
  requiredDocumentsForTransaction,
  transactionMetadataItems,
  transactionStatusLabel,
  transactionTitle,
  type CitedDocument,
  type TransactionVerificationResult,
} from './transactionResults';

type DocumentLabel = { doc_id: string; filename?: string | null; document_type?: string | null };

type Props = {
  transaction: TransactionVerificationResult;
  documents?: DocumentLabel[];
  skipped?: boolean;
  onUploadEvidence?: (txId: string, files: File[]) => void;
  evidenceUploadBusy?: boolean;
};

const documentIdPattern = /DOC_\d+/g;
const citationPattern = /\[([^\[\]\n]+)\]/g;
const boldPattern = /\*\*([^*]+)\*\*/g;

function displayDocumentName(document?: DocumentLabel): string {
  const filename = document?.filename?.trim();
  const usableFilename = filename && !/^DOC[_-]?\d+(\.pdf)?$/i.test(filename);
  const type = document?.document_type?.trim().replace(/[_-]+/g, ' ').toLocaleLowerCase();
  const displayType = type?.replace(/(^|\s)\p{L}/gu, letter => letter.toLocaleUpperCase());
  if (usableFilename && displayType) return `${displayType} — ${filename}`;
  if (usableFilename) return filename;
  return displayType || '';
}

function resolveDocumentRefs(text: string, documents: DocumentLabel[]): string {
  return text.replace(documentIdPattern, id => {
    const document = documents.find(item => item.doc_id === id);
    return displayDocumentName(document) || 'the cited document';
  });
}

function evidenceLabel(ref: { doc_id: string; pages?: string | null }, documents: DocumentLabel[]): string {
  const document = documents.find(item => item.doc_id === ref.doc_id);
  return [
    displayDocumentName(document) || 'the cited document',
    ref.pages ? `page${ref.pages.includes('-') ? 's' : ''} ${ref.pages}` : '',
  ].filter(Boolean).join(' · ');
}

function parseCitation(inner: string): CitedDocument | null {
  const match = inner.trim().match(/^(DOC_\d+)(?:\s+pp?\.?\s*(.+))?$/i);
  if (!match) return null;
  return { doc_id: match[1].toUpperCase(), pages: match[2]?.trim() || undefined };
}

function renderBold(text: string, documents: DocumentLabel[], keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(boldPattern)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(resolveDocumentRefs(text.slice(cursor, start), documents));
    nodes.push(<strong key={`${keyPrefix}-b${index++}`}>{match[1]}</strong>);
    cursor = start + match[0].length;
  }
  if (cursor < text.length) nodes.push(resolveDocumentRefs(text.slice(cursor), documents));
  return nodes;
}

function renderInlineText(text: string, documents: DocumentLabel[], keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(citationPattern)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(...renderBold(text.slice(cursor, start), documents, `${keyPrefix}-t${index}`));
    const citation = parseCitation(match[1]);
    if (citation) {
      nodes.push(
        <span className="verification-citation" key={`${keyPrefix}-c${index++}`}>
          {evidenceLabel(citation, documents) || match[1]}
        </span>,
      );
    } else {
      nodes.push(...renderBold(match[0], documents, `${keyPrefix}-t${index}`));
    }
    index += 1;
    cursor = start + match[0].length;
  }
  if (cursor < text.length) nodes.push(...renderBold(text.slice(cursor), documents, `${keyPrefix}-t${index}`));
  return nodes;
}

function ReportBody({ body, documents }: { body: string; documents: DocumentLabel[] }) {
  const blocks = body.split(/\n{2,}/).map(block => block.trim()).filter(Boolean);
  return (
    <>
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').map(line => line.trim());
        if (lines.length > 0 && lines.every(line => line.startsWith('-'))) {
          return (
            <ul key={blockIndex} className="verification-report-list">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInlineText(line.replace(/^-\s*/, ''), documents, `${blockIndex}-${lineIndex}`)}
                </li>
              ))}
            </ul>
          );
        }
        return <p key={blockIndex}>{renderInlineText(block, documents, `p${blockIndex}`)}</p>;
      })}
    </>
  );
}

export function TransactionResultCard({
  transaction,
  documents = [],
  skipped = false,
  onUploadEvidence,
  evidenceUploadBusy = false,
}: Props) {
  const requirements = requiredDocumentsForTransaction(transaction);
  const citations = citedDocumentsForTransaction(transaction);
  const metadata = transaction.transaction_metadata || {};
  const metadataItems = transactionMetadataItems(metadata);
  const skippedStatus = skipped || ['SKIPPED', 'SKIPPED_BY_USER'].includes(String(transaction.status).toUpperCase());
  const status = skippedStatus ? transactionStatusLabel('SKIPPED') : transactionStatusLabel(transaction.status);
  const statusClass = skippedStatus ? 'status-skipped' : `status-${String(transaction.status || 'PENDING').toLowerCase()}`;
  const report = typeof transaction.report === 'string' ? transaction.report.trim() : '';
  const sections = reportSections(report);

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

      {report ? (
        <section aria-label="Verification report" className="verification-report">
          {sections.map((section, index) => (
            <div className="verification-report-block" key={index}>
              {section.heading && <h4>{section.heading}</h4>}
              <ReportBody body={section.body} documents={documents} />
            </div>
          ))}
        </section>
      ) : (
        <p className="verification-result-summary">No report was recorded for this transaction.</p>
      )}

      {citations.length > 0 && (
        <section className="verification-cited-documents" aria-label="Documents cited">
          <h4>Documents cited</h4>
          <ul className="verification-finding-evidence">
            {citations.map((reference, index) => (
              <li key={`${reference.doc_id}-${reference.pages || ''}-${index}`}>
                {evidenceLabel(reference, documents)}
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

      {skippedStatus && onUploadEvidence && transaction.tx_id && (
        <label className="btn btn-secondary" style={{ display: 'inline-block', cursor: evidenceUploadBusy ? 'wait' : 'pointer' }}>
          {evidenceUploadBusy ? 'Uploading…' : 'Add evidence and retry this transaction'}
          <input
            type="file"
            accept="application/pdf,.pdf"
            multiple
            disabled={evidenceUploadBusy}
            aria-label={`Upload evidence for ${transactionTitle(transaction)}`}
            onChange={event => {
              const input = event.currentTarget;
              const files = Array.from(input.files || []);
              input.value = '';
              if (files.length) onUploadEvidence(transaction.tx_id, files);
            }}
            style={{ display: 'none' }}
          />
        </label>
      )}
    </article>
  );
}
