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
  summary: 'The inspected deed supports the transfer within the scope reviewed.',
  findings: [{
    title: 'Preceding title link supported',
    details: 'The registered deed names Anant Mankikar as seller and Ankur Patel as purchaser.',
    evidence: [{ doc_id: 'DOC_019', pages: '2-4' }],
  }],
  required_documents: [],
  reviewed_document_ids: ['DOC_019'],
  verified_at: '2026-10-22T10:00:00Z',
  schema_version: '2.1',
  transaction_metadata: {
    transaction_type: 'Sale deed',
    vendors: ['Anant Mankikar'],
    purchasers: ['Ankur Patel'],
  },
};

function render(transaction: TransactionVerificationResult, skipped = false): string {
  return renderToStaticMarkup(
    <TransactionResultCard transaction={transaction} documents={[{ doc_id: 'DOC_019', filename: 'sale-2009.pdf' }]} skipped={skipped} />,
  );
}

test('fully supported result renders summary and cited evidence without an empty evidence-needed section', () => {
  const html = render(base);
  assert.match(html, /Transaction 5 — Sale Deed/);
  assert.match(html, /Anant Mankikar → Ankur Patel/);
  assert.match(html, /Verified with available evidence/);
  assert.match(html, /The inspected deed supports the transfer/);
  assert.match(html, /DOC_019 \(sale-2009\.pdf\) · pages 2-4/);
  assert.doesNotMatch(html, /Evidence needed/);
});

test('pending result renders each actionable requirement and never claims verification', () => {
  const html = render({
    ...base,
    status: 'PENDING_NOT_VERIFIED',
    summary: 'The recital is available, but the original conveyance remains unverified.',
    verified_at: null,
    required_documents: [{ document_type: 'Original registered deed', reason: 'Verify the conveyance and registration particulars.' }],
  });
  assert.match(html, /Pending verification/);
  assert.match(html, /Evidence needed/);
  assert.match(html, /Original registered deed/);
  assert.match(html, /Verify the conveyance and registration particulars/);
  assert.doesNotMatch(html, />Verified with available evidence</);
});

test('conflicting purchaser evidence appears together in one finding', () => {
  const html = render({
    ...base,
    status: 'ISSUES_IDENTIFIED',
    findings: [{
      title: 'Conflicting purchaser names',
      details: 'The inspected deed and later recital identify different purchasers.',
      evidence: [{ doc_id: 'DOC_019', pages: '2' }, { doc_id: 'DOC_017', pages: '4' }],
    }],
  });
  assert.match(html, /Conflicting purchaser names/);
  assert.match(html, /DOC_019.*page 2/);
  assert.match(html, /DOC_017.*page 4/);
});

test('empty findings and requirements render safely; skipped results never show verified', () => {
  const empty = render({ ...base, findings: [], required_documents: [] });
  assert.doesNotMatch(empty, /Key findings|Evidence needed/);
  const skipped = render(base, true);
  assert.match(skipped, /Skipped · not verified/);
  assert.doesNotMatch(skipped, />Verified with available evidence</);
});

test('skipped result retains its actual summary, findings, citations, and outstanding requirements', () => {
  const html = render({
    ...base,
    status: 'PENDING_NOT_VERIFIED',
    summary: 'The transfer remains unverified because the original deed was not supplied.',
    verified_at: null,
    findings: [{
      title: 'Historical transfer not independently verified',
      details: 'A later instrument recites the transfer; the primary deed is unavailable. The registered schedule and extent conveyed therefore remain unconfirmed.',
      evidence: [
        { doc_id: 'DOC_019', pages: '2-4' },
        { doc_id: 'DOC_020', pages: '1' },
      ],
    }, {
      title: 'Property identity needs reconciliation',
      details: 'The records refer to distinct parcel identifiers.',
      evidence: [{ doc_id: 'DOC_020', pages: '5' }],
    }],
    required_documents: [
      { document_type: 'Original registered deed', reason: 'Verify the transfer and property schedule.' },
      { document_type: 'Survey subdivision map', reason: 'Reconcile the parcel identifiers.' },
    ],
  }, true);
  assert.match(html, /Skipped · not verified/);
  assert.match(html, /The transfer remains unverified/);
  assert.match(html, /Historical transfer not independently verified/);
  assert.match(html, /Property identity needs reconciliation/);
  assert.match(html, /remain unconfirmed/);
  assert.match(html, /DOC_019.*pages 2-4/);
  assert.match(html, /DOC_020.*page 1/);
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
    { label: 'Parties', value: 'A very long vendor name that should wrap naturally → Purchaser' },
  ]);
  assert.deepEqual(transactionMetadataItems({ transaction_type: 'SALE' }), []);
});
