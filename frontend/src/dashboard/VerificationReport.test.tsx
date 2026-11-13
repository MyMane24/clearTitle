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

const dueDiligence: VerificationReport = {
  schema_version: '3.0',
  report_type: 'PRELIMINARY',
  generated_at: '2026-11-12T10:00:00+00:00',
  verdict: { level: 'CAUTION', headline: 'Pause before committing: earlier links and a bank charge are unresolved.' },
  property: {
    type: 'Open plot',
    rows: [
      { label: 'Property type', value: 'Open plot' },
      { label: 'Schedule', value: 'Plot 9, CTS 1360B/9, 30 ft x 40 ft' },
    ],
  },
  chain: [
    { sequence: 1, label: 'the 2007 sale', transaction_type: 'Sale', date: '06 December 2007', registration: 'BEL-1-07200-2007-08',
      from: ['Manohar Kalkundrikar'], to: ['Dinanath Revankar'], property_type: 'Agricultural land',
      result: { level: 'CAUTION', label: 'Awaiting documents' } },
    { sequence: 2, label: 'the 2019 sale', transaction_type: 'Sale', date: '17 July 2019', registration: null,
      from: ['Heirs'], to: ['Arjun Patil'], property_type: 'Open plot',
      result: { level: 'CRITICAL', label: 'Issues found' } },
  ],
  narrative_markdown: [
    '## Main issues',
    '',
    '- **Bank charge** — No release is shown.',
    '',
    '| Deed | Extent |',
    '| --- | --- |',
    '| 2019 | 1,200 sq ft |',
    '',
    '1. Ask the bank for a discharge letter.',
  ].join('\n'),
  documents_needed: [{ document: 'Will — Parvatibai to Manohar, 26-11-1996', reason: 'Root title', for: 'the 2007 sale' }],
  documents_examined: [{ filename: 'SaleDeed 2024.pdf', document_type: 'SALE DEED' }],
  counts: { verified: 0, issues: 1, awaiting: 1 },
};

function renderDueDiligence(overrides: Partial<VerificationReport> = {}): string {
  return renderToStaticMarkup(<VerificationReportView report={{ ...dueDiligence, ...overrides }} />);
}

test('due-diligence report shows the verdict banner, property, chain table, narrative and documents needed', () => {
  const html = renderDueDiligence();
  assert.match(html, /verify-report-banner is-caution/);
  assert.match(html, /Proceed with caution/);
  assert.match(html, /Pause before committing/);
  assert.match(html, /0 verified/);
  assert.match(html, /1 with issues/);
  assert.match(html, /1 awaiting documents/);
  assert.match(html, /Plot 9, CTS 1360B\/9, 30 ft x 40 ft/);
  assert.match(html, /Title chain at a glance/);
  assert.match(html, /BEL-1-07200-2007-08/);
  assert.match(html, /Manohar Kalkundrikar → Dinanath Revankar/);
  assert.match(html, /verify-report-result is-critical">Issues found/);
  assert.match(html, /Documents still needed/);
  assert.match(html, /Will — Parvatibai to Manohar/);
  assert.match(html, /SaleDeed 2024\.pdf/);
});

test('the markdown narrative renders its own headings, bullets, tables and steps', () => {
  const html = renderDueDiligence();
  assert.match(html, /<h5 class="report-md-heading">Main issues<\/h5>/);
  assert.match(html, /<strong>Bank charge<\/strong>/);
  assert.match(html, /<table class="report-md-table"/);
  assert.match(html, /<ol class="report-md-list">/);
  // The narrative starts with its own heading, so no umbrella heading is added.
  assert.doesNotMatch(html, /What this means for you/);
});

test('a narrative without headings gets the umbrella heading', () => {
  const html = renderDueDiligence({ narrative_markdown: 'The records support the latest deed.' });
  assert.match(html, /What this means for you/);
});

test('the property column appears only when some link has a property type', () => {
  assert.match(renderDueDiligence(), /<th>Property<\/th>/);
  const noTypes = dueDiligence.chain!.map(row => ({ ...row, property_type: null }));
  assert.doesNotMatch(renderDueDiligence({ chain: noTypes }), /<th>Property<\/th>/);
});

test('reports saved in the old format still render until they are regenerated', () => {
  const html = render();
  assert.match(html, /Schedule of property/);
  assert.doesNotMatch(html, /verify-report-banner/);
});

test('a critical verdict is styled and labelled as serious', () => {
  const html = renderDueDiligence({ verdict: { level: 'CRITICAL', headline: 'Title is contradicted.' } });
  assert.match(html, /verify-report-banner is-critical/);
  assert.match(html, /Serious concerns/);
});
