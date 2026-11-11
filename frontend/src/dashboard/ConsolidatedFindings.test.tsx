import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { ConsolidatedFindings } from './ConsolidatedFindings';
import type { CaseFindingsResponse } from '../api/backend';

const populated: CaseFindingsResponse = {
  case_id: 'CASE1',
  container_version: '1.0',
  input_hash: 'abc123',
  findings: [{
    finding_id: 'PF-001',
    category: 'ENCUMBRANCE',
    title: 'Undischarged mortgage on the parent parcel',
    description: 'A recorded memorandum stands undischarged.',
    severity: 'CRITICAL',
    affected_tx_ids: ['PA-TC-0007'],
    documents: [{ doc_id: 'DOC14', pages: '2-3' }],
    evidence_gaps: ['Discharge confirmation not supplied'],
    implication: 'The recorded charge must be resolved before title transfers.',
  }],
  contradictions: [{
    description: 'Survey number differs between the deed schedule and the CTS record.',
    sides: [{ tx_id: 'PA-TC-0002' }, { tx_id: 'PA-TC-0003' }],
    severity: 'CAUTION',
    resolution_guidance: 'Obtain a certified survey record.',
  }],
  unresolved_dependencies: ['REQ-0002'],
  provenance: { contract_version: '1.0', phase_a_hash: 'pa' },
};

function render(data: CaseFindingsResponse | null): string {
  return renderToStaticMarkup(<ConsolidatedFindings data={data} />);
}

test('a populated container renders findings with ids, severity, transactions and gaps', () => {
  const html = render(populated);
  assert.match(html, /CONSOLIDATED PROPERTY FINDINGS/);
  assert.match(html, /PF-001/);
  assert.match(html, /Undischarged mortgage on the parent parcel/);
  assert.match(html, /critical/);
  assert.match(html, /PA-TC-0007/);
  assert.match(html, /Discharge confirmation not supplied/);
  assert.match(html, /Conflicting records/);
  assert.match(html, /Still unresolved/);
});

test('a case without a container states that findings appear after verification', () => {
  const html = render({ ...populated, container_version: null, findings: [], contradictions: [], unresolved_dependencies: [] });
  assert.match(html, /after transaction verification completes/);
  assert.doesNotMatch(html, /PF-001/);
});

test('a generated container with zero findings says so honestly', () => {
  const html = render({ ...populated, findings: [], contradictions: [], unresolved_dependencies: [] });
  assert.match(html, /No consolidated findings are recorded/);
});

test('no data renders nothing at all', () => {
  assert.equal(render(null), '');
});
