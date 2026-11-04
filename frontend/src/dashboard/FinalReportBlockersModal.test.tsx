import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { FinalReportBlockersModal, } from './FinalReportBlockersModal';
import type { FinalReportBlocker } from '../api/backend';

const blockers: FinalReportBlocker[] = [
  {
    tx_id: 'PA-TC-0002',
    sequence: 2,
    transaction_type: 'Sale deed 2011',
    status: 'PENDING_NOT_VERIFIED',
    required_documents: [
      { document_type: 'Encumbrance certificate 2005-2010', reason: 'Confirm no pending charges' },
      { document_type: 'Family settlement deed', reason: 'Trace inheritance' },
    ],
  },
  {
    tx_id: 'PA-TC-0006',
    sequence: 6,
    transaction_type: 'Release deed 2018',
    status: 'PENDING_NOT_VERIFIED',
    required_documents: [],
    note: 'No verification result is recorded for this transaction yet.',
  },
];

function render(items: FinalReportBlocker[] = blockers): string {
  return renderToStaticMarkup(<FinalReportBlockersModal blockers={items} onClose={() => {}} />);
}

test('lists every blocking transaction with its status and required documents', () => {
  const html = render();
  assert.match(html, /Transaction verification incomplete/);
  assert.match(html, /Transaction 2 — Sale deed 2011/);
  assert.match(html, /Encumbrance certificate 2005-2010/);
  assert.match(html, /Confirm no pending charges/);
  assert.match(html, /Transaction 6 — Release deed 2018/);
  assert.match(html, /No verification result is recorded for this transaction yet\./);
  assert.match(html, /Back to case/);
});

test('documents-reason and status text do not leak raw enum underscores to the user', () => {
  const html = render();
  assert.match(html, /pending not verified/);
  assert.doesNotMatch(html, /PENDING_NOT_VERIFIED/);
});

test('an empty blocker list still renders the dialog with the closing action', () => {
  const html = render([]);
  assert.match(html, /Transaction verification incomplete/);
  assert.match(html, /Back to case/);
});
