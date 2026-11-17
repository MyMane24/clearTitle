import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { DueDiligenceReport as Report, VerificationState } from '../../api/backend';
import { DueDiligenceReport } from './DueDiligenceReport';
import { LiveFeed } from './LiveFeed';
import { Requisitions } from './Requisitions';
import { shouldPoll } from './VerificationPanel';

const REPORT: Report = {
  version: 2,
  property_summary: 'Sy.No.45, Hosahalli, 2 acres 10 guntas, owned by Deepa.',
  opinion: 'NOT_CLEAR',
  opinion_reasons: [{ text: "Minor's share sold without court permission.", refs: ['I1'] }],
  changes_since_previous: ['Requisition R1: open -> resolved.'],
  sections: [
    { id: 'documents_examined', title: 'Documents examined', blocks: [
      { type: 'table', columns: ['Document', 'Status'], rows: [['EC', 'Examined in full']] },
    ] },
    { id: 'transaction_scrutiny', title: 'Scrutiny of each transaction', blocks: [
      { type: 'findings', items: [{ title: 'Sale 2010', text: 'Defective.', status: 'defective', refs: ['PA-TC-0002'] }] },
    ] },
    { id: 'red_flags', title: 'Red flags', blocks: [
      { type: 'findings', items: [{ title: 'Minor share', text: 'No permission.', severity: 'high', refs: ['I1'] }] },
    ] },
    { id: 'a_new_section', title: 'A section the UI has never seen', blocks: [
      { type: 'list', items: [{ text: 'Rendered generically.' }] },
    ] },
  ],
};

test('report shows opinion, changes and every section, including unknown ones', () => {
  const html = renderToStaticMarkup(<DueDiligenceReport report={REPORT} />);
  for (const text of ['VERSION 2', 'Title not clear', "Minor&#x27;s share sold", 'Changes since version 1',
    'Requisition R1: open -&gt; resolved.', '1. Documents examined', 'Examined in full', 'defective',
    'PA-TC-0002', 'vf-sev-high', '4. A section the UI has never seen', 'Rendered generically.']) {
    assert.ok(html.includes(text), `Missing ${text}`);
  }
});

test('live feed lists steps and shows work in progress', () => {
  const html = renderToStaticMarkup(<LiveFeed running events={[
    { id: 1, run_id: 'r', kind: 'lead', text: 'Discovered (L1): 2005 partition', created_at: '' },
  ]} />);
  assert.match(html, /Discovered \(L1\): 2005 partition/);
  assert.match(html, /Working…/);
  assert.match(renderToStaticMarkup(<LiveFeed running={false} events={[]} />), /No verification steps yet/);
});

test('only open requisitions can be uploaded', () => {
  const html = renderToStaticMarkup(<Requisitions busyId={null} disabled={false} onUpload={() => {}} requisitions={[
    { id: 'R1', document: 'Partition deed', reason: 'Title', affects: ['VL-1'], status: 'open' },
    { id: 'R2', document: 'Release deed', reason: 'Mortgage', affects: ['I2'], status: 'resolved' },
  ]} />);
  assert.equal((html.match(/type="file"/g) || []).length, 1);
  assert.match(html, /Settled/);
});

test('polling continues only while there is something to wait for', () => {
  const base: VerificationState = { case_id: 'C', run: null, case_file: null, report: null };
  const run = { id: 'r', kind: 'full' as const, started_at: '' };
  assert.equal(shouldPoll(base, null, 0), false);
  assert.equal(shouldPoll({ ...base, run: { ...run, status: 'running' } }, null, 0), true);
  assert.equal(shouldPoll({ ...base, run: { ...run, status: 'done' } }, null, 0), false);
  assert.equal(shouldPoll(base, 1000, 2000), true);
  assert.equal(shouldPoll(base, 0, 10 * 60 * 1000), false);
});
