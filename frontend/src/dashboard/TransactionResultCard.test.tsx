import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { TransactionResultCard } from './TransactionResultCard';
import { transactionMetadataItems, type TransactionVerificationResult } from './transactionResults';

const base: TransactionVerificationResult = {
  tx_id: 'PA-TC-0005',
  sequence: 5,
  status: 'VERIFIED_WITH_AVAILABLE_EVIDENCE',
  report: [
    '## Conclusion',
    '',
    'The inspected deed supports the transfer within the scope reviewed [DOC_019 p.2-4].',
  ].join('\n'),
  cited_documents: [{ doc_id: 'DOC_019', pages: '2-4' }],
  required_documents: [],
  reviewed_document_ids: ['DOC_019'],
  verified_at: '2026-10-22T10:00:00Z',
  schema_version: '3.0',
  transaction_metadata: {
    transaction_type: 'Sale deed',
    executed_date: '15 December 2009',
    registration_date: '16 December 2009',
    transaction_number: 'BEL-1-07403-2009-10',
    vendors: ['Anant Mankikar'],
    purchasers: ['Ankur Patel'],
  },
};

function render(transaction: TransactionVerificationResult, skipped = false): string {
  return renderToStaticMarkup(
    <TransactionResultCard transaction={transaction} documents={[{ doc_id: 'DOC_019', filename: 'sale-2009.pdf', document_type: 'SALE_DEED' }]} skipped={skipped} />,
  );
}

test('report renders as titled sections with resolved citation chips and no raw document IDs', () => {
  const html = render(base);
  assert.match(html, /Transaction 5 — Sale Deed/);
  assert.match(html, /Reported parties.*Anant Mankikar → Ankur Patel/);
  assert.match(html, /Verified with available evidence/);
  assert.match(html, /Conclusion/);
  assert.match(html, /The inspected deed supports the transfer/);
  assert.match(html, /Sale Deed — sale-2009\.pdf · pages 2-4/);
  assert.match(html, /Documents cited/);
  assert.doesNotMatch(html, /DOC_019/);
  assert.doesNotMatch(html, /Evidence needed/);
});

test('report bullets render as list items and bold labels stay intact', () => {
  const html = render({
    ...base,
    report: [
      '## Findings',
      '',
      '- **Preceding title link supported** — The registered deed names the recorded parties [DOC_019 p.2-4].',
      '- **Schedule matches** — Extent and boundaries agree.',
    ].join('\n'),
  });
  assert.match(html, /<ul class="verification-report-list"/);
  assert.match(html, /<strong>Preceding title link supported<\/strong>/);
  assert.match(html, /Extent and boundaries agree/);
});

test('legacy summary and findings fields are not rendered', () => {
  const legacyResult = {
    ...base,
    summary: 'Legacy summary text.',
    findings: [{ title: 'Legacy finding', details: 'Legacy details.', evidence: [] }],
    historical_dependencies: [{
      origin_tx_id: 'PA-TC-0002',
      origin_finding_id: 'PA-TC-0002:F-a1b2',
      relevance: 'affects the seller interest',
    }],
  } as unknown as TransactionVerificationResult;
  const html = render(legacyResult);
  assert.match(html, /The inspected deed supports the transfer/);
  assert.doesNotMatch(html, /Legacy summary text|Legacy finding|Historical dependencies|affects the seller interest/);
});

test('pending result renders each actionable requirement and never claims verification', () => {
  const html = render({
    ...base,
    status: 'PENDING_NOT_VERIFIED',
    report: '## Conclusion\n\nThe recital is available, but the original conveyance remains unverified.',
    cited_documents: [],
    verified_at: null,
    required_documents: [{ document_type: 'Original registered deed', reason: 'Verify the conveyance and registration particulars.' }],
  });
  assert.match(html, /Pending verification/);
  assert.match(html, /Evidence needed/);
  assert.match(html, /Original registered deed/);
  assert.match(html, /Verify the conveyance and registration particulars/);
  assert.doesNotMatch(html, />Verified with available evidence</);
  assert.doesNotMatch(html, /Documents cited/);
});

test('only skipped transactions show a targeted evidence upload action', () => {
  const skippedHtml = renderToStaticMarkup(
    <TransactionResultCard
      transaction={{ ...base, status: 'PENDING_NOT_VERIFIED' }}
      skipped
      onUploadEvidence={() => {}}
    />,
  );
  const completedHtml = renderToStaticMarkup(
    <TransactionResultCard transaction={base} onUploadEvidence={() => {}} />,
  );

  assert.match(skippedHtml, /Add evidence and retry this transaction/);
  assert.match(skippedHtml, /Upload evidence for Transaction 5/);
  assert.doesNotMatch(completedHtml, /Add evidence and retry this transaction/);
});

test('action section renders the saved model rationale without UI-side rewriting', () => {
  const repeated = 'The purchaser identity remains unresolved.';
  const html = render({
    ...base,
    status: 'PENDING_NOT_VERIFIED',
    report: `## What is needed next\n\n${repeated}`,
    required_documents: [{
      document_type: 'Official identity or rectification evidence',
      reason: repeated,
    }],
  });
  assert.equal(html.match(/The purchaser identity remains unresolved/g)?.length, 2);
  assert.match(html, /Official identity or rectification evidence/);
});

test('citations inside report text resolve to document names and pages', () => {
  const html = render({
    ...base,
    status: 'ISSUES_IDENTIFIED',
    report: '## Problems and gaps\n\nThe inspected deed and later recital identify different purchasers [DOC_019 p.2] [DOC_017 p.4].',
    cited_documents: [{ doc_id: 'DOC_019', pages: '2' }, { doc_id: 'DOC_017', pages: '4' }],
  },);
  assert.match(html, /Sale Deed — sale-2009\.pdf · page 2/);
  assert.match(html, /page 4/);
  assert.doesNotMatch(html, /DOC_019|DOC_017/);
});

test('unresolvable citations keep readable text and never expose raw IDs', () => {
  const html = renderToStaticMarkup(
    <TransactionResultCard
      transaction={{ ...base, report: '## Conclusion\n\nDOC_021 supports the reported conveyance [DOC_999 p.1].' }}
      documents={[{ doc_id: 'DOC_021', filename: 'DOC_021.pdf', document_type: 'SALE_DEED' }]}
    />,
  );
  assert.match(html, /Sale Deed supports the reported conveyance/);
  assert.match(html, /the cited document/);
  assert.doesNotMatch(html, /DOC_\d+/);
});

test('empty report and requirements render safely; skipped results never show verified', () => {
  const empty = render({ ...base, report: '', cited_documents: [], required_documents: [] });
  assert.match(empty, /No report was recorded/);
  assert.doesNotMatch(empty, /Evidence needed|Documents cited/);
  const skipped = render(base, true);
  assert.match(skipped, /Skipped · not verified/);
  assert.doesNotMatch(skipped, />Verified with available evidence</);
});

test('skipped result retains its actual report, citations, and outstanding requirements', () => {
  const html = render({
    ...base,
    status: 'PENDING_NOT_VERIFIED',
    verified_at: null,
    report: [
      '## Conclusion',
      '',
      'The transfer remains unverified because the original deed was not supplied.',
      '',
      '## Upstream dependency',
      '',
      'PA-TC-0002 is unverified; this assessment rests on this transaction\'s own evidence.',
    ].join('\n'),
    cited_documents: [{ doc_id: 'DOC_019', pages: '2-4' }, { doc_id: 'DOC_020', pages: '1' }],
    required_documents: [
      { document_type: 'Original registered deed', reason: 'Verify the transfer and property schedule.' },
      { document_type: 'Survey subdivision map', reason: 'Reconcile the parcel identifiers.' },
    ],
  }, true);
  assert.match(html, /Skipped · not verified/);
  assert.match(html, /The transfer remains unverified/);
  assert.match(html, /Upstream dependency/);
  assert.match(html, /Sale Deed — sale-2009\.pdf · pages 2-4/);
  assert.match(html, /page 1/);
  assert.doesNotMatch(html, /DOC_019|DOC_020/);
  assert.match(html, /Original registered deed/);
  assert.match(html, /Survey subdivision map/);
  assert.doesNotMatch(html, />Pending verification</);
});

test('issue, inconclusive, and in-progress results receive distinct readable status classes', () => {
  assert.match(render({ ...base, status: 'ISSUES_IDENTIFIED' }), /status-issues_identified/);
  assert.match(render({ ...base, status: 'INCONCLUSIVE' }), /status-inconclusive/);
  assert.match(render({ ...base, status: 'IN_PROGRESS' }), /status-in_progress/);
});

test('metadata omits unavailable values and includes traceable transaction context', () => {
  assert.deepEqual(transactionMetadataItems({
    transaction_type: 'SALE',
    registration_number: 'BLG-5-123456-2012-13',
    executed_date: '4 September 2012',
    survey_number: '191/4',
    plot_number: '40',
    vendors: ['A very long vendor name that should wrap naturally'],
    purchasers: ['Purchaser'],
  }), [
    { label: 'Registration no.', value: 'BLG-5-123456-2012-13' },
    { label: 'Execution date', value: '4 September 2012' },
    { label: 'Property', value: 'Survey 191/4 · Plot 40' },
    { label: 'Reported parties', value: 'A very long vendor name that should wrap naturally → Purchaser' },
  ]);
  assert.deepEqual(transactionMetadataItems({ transaction_type: 'SALE' }), []);
});
