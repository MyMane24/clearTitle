import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { VerificationReportView } from './VerificationReport';
import type { VerificationReport } from '../api/backend';

const report: VerificationReport = {
  report_type: 'FINAL',
  generated_at: '2026-11-12T10:00:00+00:00',
  schedule: [
    { label: 'Survey number(s)', value: '45/2B' },
    { label: 'Extent / area', value: '6070 square metres' },
  ],
  documents_examined: [
    { filename: 'KUDA_SaleDeed_1996.pdf', document_type: 'sale deed' },
    { filename: 'SaleDeed_2004.pdf', document_type: 'sale deed' },
  ],
  counts: { critical: 1, caution: 2, clear: 1 },
  findings: [
    { severity: 'CRITICAL', title: 'Original deed missing', detail: 'The 1996 conveyance is only recited.' },
    { severity: 'CAUTION', title: 'No encumbrance evidence', detail: 'No encumbrance certificate was examined.' },
    { severity: 'CLEAR', title: 'Parcel identity matches', detail: 'All deeds describe the same parcel.' },
  ],
  cannot_verify: ['possession was not inspected'],
  opinion: {
    verdict_line: 'Chain is verified; one item needs your attention',
    summary: 'The recorded transfers connect the current owner to the earliest supported root.',
    conditions: ['Obtain an encumbrance certificate before you commit.'],
  },
};

function render(overrides: Partial<VerificationReport> = {}): string {
  return renderToStaticMarkup(<VerificationReportView report={{ ...report, ...overrides }} />);
}

test('verification report renders every section like the source layout', () => {
  const html = render();
  assert.match(html, /Title verification report/);
  assert.match(html, /Schedule of property/);
  assert.match(html, /Documents examined/);
  assert.match(html, /Findings/);
  assert.match(html, /What this report could not verify/);
  assert.match(html, /Opinion/);
  assert.match(html, /45\/2B/);
  assert.match(html, /KUDA_SaleDeed_1996\.pdf/);
  assert.match(html, /Chain is verified; one item needs your attention/);
  assert.match(html, /Obtain an encumbrance certificate/);
});

test('count chips reflect the finding tallies', () => {
  const html = render();
  assert.match(html, /1 Critical/);
  assert.match(html, /2 To resolve/);
  assert.match(html, /1 Clear/);
});

test('preliminary reports show the preliminary type chip; final shows final', () => {
  assert.match(render(), /Final report/);
  assert.doesNotMatch(render(), /Preliminary report/);
  assert.match(render({ report_type: 'PRELIMINARY' }), /Preliminary report/);
});

test('finding cards carry their severity labels', () => {
  const html = render();
  assert.match(html, /Critical/);
  assert.match(html, /Caution/);
  assert.match(html, /Clear/);
  assert.match(html, /Original deed missing/);
});
