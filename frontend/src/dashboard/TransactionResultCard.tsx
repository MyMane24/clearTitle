import React from 'react';
import { Upload } from 'lucide-react';

import {
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
  onOpenUpload?: (txId: string) => void;
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

const RISK_PATTERN = /(discrepan|unverifi|unestablish|uncertain|unresolved|mismatch|outstanding|missing|does not|cannot|not independently|not documented|not reconcil|limits confirmation|gap)/i;

function splitFinding(line: string): { title: string; text: string } {
  const match = line.match(/^\*\*([^*]+)\*\*\s*(?:[—–-]|:)?\s*(.*)$/);
  if (match) return { title: match[1].trim(), text: match[2].trim() };
  return { title: '', text: line };
}

function DocRef({ citation, documents }: { citation: CitedDocument; documents: DocumentLabel[] }) {
  const label = evidenceLabel(citation, documents) || 'Cited document';
  return (
    <span
      className="verification-doc-ref"
      title={label}
      aria-label={`Source: ${label}`}
    >
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
      PDF
    </span>
  );
}

function renderInline(text: string, documents: DocumentLabel[], keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(citationPattern)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(...renderBold(text.slice(cursor, start), documents, `${keyPrefix}-t${index}`));
    const citation = parseCitation(match[1]);
    if (citation) {
      nodes.push(<DocRef key={`${keyPrefix}-c${index}`} citation={citation} documents={documents} />);
    } else {
      nodes.push(...renderBold(match[0], documents, `${keyPrefix}-t${index}`));
    }
    index += 1;
    cursor = start + match[0].length;
  }
  if (cursor < text.length) nodes.push(...renderBold(text.slice(cursor), documents, `${keyPrefix}-t${index}`));
  return nodes;
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

function ReportBody({ body, documents }: { body: string; documents: DocumentLabel[] }) {
  const blocks = body.split(/\n{2,}/).map(block => block.trim()).filter(Boolean);
  return (
    <>
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').map(line => line.trim());
        if (lines.length > 0 && lines.every(line => line.startsWith('-'))) {
          return (
            <ul key={blockIndex} className="verification-report-list verification-findings-list">
              {lines.map((line, lineIndex) => {
                const { title, text } = splitFinding(line.replace(/^-\s*/, ''));
                const risky = RISK_PATTERN.test(title) || RISK_PATTERN.test(text);
                return (
                  <li key={lineIndex} className={`verification-finding-item${risky ? ' verification-finding-risk' : ''}`}>
                    {title && <strong>{title}</strong>}
                    {text && <p>{renderInline(text, documents, `${blockIndex}-${lineIndex}`)}</p>}
                  </li>
                );
              })}
            </ul>
          );
        }
        return (
          <div key={blockIndex} className="verification-report-paragraph">
            <p>{renderInline(block, documents, `p${blockIndex}`)}</p>
          </div>
        );
      })}
    </>
  );
}

export function TransactionResultCard({
  transaction,
  documents = [],
  skipped = false,
  onOpenUpload,
  evidenceUploadBusy = false,
}: Props) {
  const requirements = requiredDocumentsForTransaction(transaction);
  const metadata = transaction.transaction_metadata || {};
  const metadataItems = transactionMetadataItems(metadata);
  const skippedStatus = skipped || ['SKIPPED', 'SKIPPED_BY_USER'].includes(String(transaction.status).toUpperCase());
  const issuesStatus = String(transaction.status).toUpperCase() === 'ISSUES_IDENTIFIED';
  // The button exists to fill this link's own agent-listed slots; a link with
  // no own requests (its evidence was asked on an earlier link) offers none.
  const canUpload = Boolean(onOpenUpload && transaction.tx_id) && (skippedStatus || issuesStatus) && requirements.length > 0;
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
              {section.heading && (
                <h4 className={RISK_PATTERN.test(section.heading) ? 'verification-report-heading-risk' : undefined}>
                  {section.heading}
                </h4>
              )}
              <ReportBody body={section.body} documents={documents} />
            </div>
          ))}
        </section>
      ) : (
        <p className="verification-result-summary">No report was recorded for this transaction.</p>
      )}

      {requirements.length > 0 && (
        <section className="verification-evidence-needed" aria-label="Evidence still needed">
          <h4>Evidence needed</h4>
          <ul>
            {requirements.map((item, index) => (
              <li key={`${item.document_type}-${index}`}>
                <strong style={{ lineHeight: 1.4 }}>{item.document_type}</strong>
                {item.reason && <p>{resolveDocumentRefs(item.reason, documents)}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {canUpload && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
          <button
            className="verification-upload-btn"
            disabled={evidenceUploadBusy}
            onClick={() => onOpenUpload!(transaction.tx_id!)}
          >
            <Upload size={13} />
            {evidenceUploadBusy ? 'Uploading…' : 'Upload evidence'}
          </button>
        </div>
      )}
    </article>
  );
}
