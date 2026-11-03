import assert from 'node:assert/strict';
import test from 'node:test';

import {
  citedDocumentsForTransaction,
  reportSections,
  requiredDocumentsForTransaction,
  requirementsForPausedTransaction,
  transactionStatusLabel,
  transactionTitle,
} from './transactionResults';

test('requirements are read from canonical required_documents and deduplicated', () => {
  const items = requiredDocumentsForTransaction({ required_documents: [
    { document_type: 'Registered deed', reason: 'Verify transfer' },
    { document_type: ' registered deed ', reason: ' verify transfer ' },
    { document_type: 'Mutation entry', reason: 'Verify parcel identity' },
  ] });
  assert.equal(items.length, 2);
  assert.equal(items[0].document_type, 'Registered deed');
});

test('empty or absent canonical requirements remain empty', () => {
  assert.deepEqual(requiredDocumentsForTransaction({ required_documents: [] }), []);
  assert.deepEqual(requiredDocumentsForTransaction({ missing_documents: [{ document_type: 'Legacy' }] }), []);
});

test('paused modal requirements come from the paused transaction, or from earlier links it relies on', () => {
  const transactions = [
    { tx_id: 'PA-TC-0001', required_documents: [{ document_type: 'Sale deed', reason: 'Verify transfer' }] },
    { tx_id: 'PA-TC-0002', required_documents: [{ document_type: 'Mutation', reason: 'Verify entry' }] },
    { tx_id: 'PA-TC-0003', required_documents: [] },
  ];
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-0002').map(item => item.document_type), ['Mutation']);
  // A paused transaction with no request of its own falls back to the
  // outstanding requests of the earlier links it relies on.
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-0003').map(item => item.document_type), ['Sale deed', 'Mutation']);
});

test('own requests take priority over relied-upon earlier requests', () => {
  const transactions = [
    { tx_id: 'PA-TC-0001', required_documents: [{ document_type: 'Sale deed', reason: 'Verify transfer' }] },
    { tx_id: 'PA-TC-0002', required_documents: [{ document_type: 'Khata', reason: 'Verify parcel records' }] },
  ];
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-0002').map(item => item.document_type), ['Khata']);
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-9999'), []);
});

test('canonical verification statuses render with distinct labels', () => {
  assert.equal(transactionStatusLabel('PENDING_NOT_VERIFIED'), 'Pending verification');
  assert.equal(transactionStatusLabel('VERIFIED_WITH_AVAILABLE_EVIDENCE'), 'Verified with available evidence');
  assert.equal(transactionStatusLabel('ISSUES_IDENTIFIED'), 'Issues identified');
  assert.equal(transactionStatusLabel('INCONCLUSIVE'), 'Inconclusive');
});

test('transaction title hides stale Phase A EC provenance wording', () => {
  assert.equal(transactionTitle({
    sequence: 4,
    transaction_metadata: { transaction_type: 'Sale (EC entry; instrument not supplied)' },
  }), 'Transaction 4 — Sale');
});

test('report sections split on markdown headings and keep bodies intact', () => {
  const report = [
    '## Conclusion',
    '',
    'The inspected deed supports the transfer.',
    '',
    '## Earlier transactions',
    '',
    'The earlier sale has not been verified yet; this assessment rests on this transaction\'s own evidence.',
    'It spans two lines.',
  ].join('\n');
  assert.deepEqual(reportSections(report), [
    { heading: 'Conclusion', body: 'The inspected deed supports the transfer.' },
    {
      heading: 'Earlier transactions',
      body: 'The earlier sale has not been verified yet; this assessment rests on this transaction\'s own evidence.\nIt spans two lines.',
    },
  ]);
});

test('report sections tolerate heading-less text, empty input, and non-string values', () => {
  assert.deepEqual(reportSections('Just a paragraph.'), [{ heading: '', body: 'Just a paragraph.' }]);
  assert.deepEqual(reportSections(''), []);
  assert.deepEqual(reportSections(null), []);
  assert.deepEqual(reportSections(42), []);
});

test('cited documents are read from canonical cited_documents and deduplicated', () => {
  const items = citedDocumentsForTransaction({ cited_documents: [
    { doc_id: 'DOC_019', pages: '2-4' },
    { doc_id: 'DOC_019', pages: '2-4' },
    { doc_id: 'DOC_019' },
    { doc_id: ' DOC_020 ' },
    { pages: '3' },
  ] });
  assert.deepEqual(items, [
    { doc_id: 'DOC_019', pages: '2-4' },
    { doc_id: 'DOC_019' },
    { doc_id: 'DOC_020' },
  ]);
  assert.deepEqual(citedDocumentsForTransaction({}), []);
  assert.deepEqual(citedDocumentsForTransaction(null), []);
});
