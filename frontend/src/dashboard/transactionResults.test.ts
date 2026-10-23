import assert from 'node:assert/strict';
import test from 'node:test';

import { requiredDocumentsForTransaction, requirementsForPausedTransaction, transactionStatusLabel } from './transactionResults';

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

test('paused modal requirements come only from the matching persisted transaction result', () => {
  const transactions = [
    { tx_id: 'PA-TC-0001', required_documents: [{ document_type: 'Sale deed', reason: 'Verify transfer' }] },
    { tx_id: 'PA-TC-0002', required_documents: [{ document_type: 'Mutation', reason: 'Verify entry' }] },
  ];
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-0002').map(item => item.document_type), ['Mutation']);
  assert.deepEqual(requirementsForPausedTransaction(transactions, 'PA-TC-0003'), []);
});

test('canonical verification statuses render with distinct labels', () => {
  assert.equal(transactionStatusLabel('PENDING_NOT_VERIFIED'), 'Pending verification');
  assert.equal(transactionStatusLabel('VERIFIED_WITH_AVAILABLE_EVIDENCE'), 'Verified with available evidence');
  assert.equal(transactionStatusLabel('ISSUES_IDENTIFIED'), 'Issues identified');
  assert.equal(transactionStatusLabel('INCONCLUSIVE'), 'Inconclusive');
});
