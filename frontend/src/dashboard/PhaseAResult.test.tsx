import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PhaseAChainView } from './PhaseAResult';

test('detailed chain shows structured evidence alongside notes without using internal IDs as order', () => {
  const html = renderToStaticMarkup(<PhaseAChainView onBack={() => {}} result={{
    title_chain: [{
      chain_position: 1,
      tx_id: 'PA-TC-0019',
      continues_previous: false,
      documented_transaction: {
        transaction_type: 'Sale',
        transaction_number: '1415/1990-91',
        executed_date: '18 August 1990',
        registration_date: '19 August 1990',
        transferors: ['Meena'],
        transferees: ['Anant'],
        property_schedule: 'Southern half of Plot 40',
        survey_number: '191/4',
        consideration: 'Rs 66,000',
        evidence_status: 'recital_reported',
        summary_points: ['Purchaser identity reconciled using the endorsement.'],
        source_refs: [{ doc_id: 'DOC_009', filename: 'deed.pdf' }],
      },
      related_events: [{
        type: 'Mortgage', summary_points: ['Deposit of title deeds.'],
        source_refs: [{ doc_id: 'DOC_020', filename: 'mortgage.pdf' }],
      }],
    }],
  }} />);
  for (const text of ['Transaction 1', 'Meena', 'Anant', 'Southern half of Plot 40',
    '191/4', 'Rs 66,000', '19 August 1990', 'Reported in a later deed',
    'Purchaser identity reconciled', 'deed.pdf', 'Mortgage', 'mortgage.pdf']) {
    assert.ok(html.includes(text), `Missing ${text}`);
  }
  assert.doesNotMatch(html, /PA-TC-0019|Unresolved continuity/);
});

test('gaps are explicit and missing values do not imply verification', () => {
  const html = renderToStaticMarkup(<PhaseAChainView onBack={() => {}} result={{
    title_chain: [{ chain_position: 1 }, {
      chain_position: 2, continues_previous: false,
      documented_transaction: {
        transaction_type: 'Succession', executed_date: null,
        registration_date: 'Not stated', consideration: 'null',
        property_schedule: '  ', transferors: [], transferees: ['Known heir', null],
      },
    }],
  }} />);
  assert.match(html, /Unresolved continuity with the previous link/);
  assert.doesNotMatch(html, /Not stated|Execution date|registration date|consideration|property schedule|From · Transferors/);
  assert.match(html, /Known heir/);
  assert.match(html, /verification is a separate stage/);
});
