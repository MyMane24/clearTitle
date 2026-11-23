import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { CaseResults, VerificationState } from '../../api/backend';
import { LiveFeed } from '../verification/LiveFeed';
import { CaseResultsView } from './CaseResults';
import { ChainTimeline, timelineLinks } from './ChainTimeline';
import { humanizeType, refLabeller } from './labels';
import { shouldPoll } from './useVerification';

const RESULTS: CaseResults = {
  case: { case_id: 'C1', status: 'complete', total_docs: 2, completed_docs: 2, failed_docs: 0 },
  documents: [
    { doc_id: 'DOC_018', filename: 'SaleDeed 2007.pdf', document_type: 'SALE_DEED', status: 'structured' },
    { doc_id: 'DOC_002', filename: 'EC 2010 to 2026.pdf', document_type: 'ENCUMBRANCE_CERTIFICATE', status: 'structured' },
  ],
  agent: {
    status: 'done',
    property_identity: { details: [{ label: 'CTS', value: '1360B/9' }] },
    title_chain: [{
      tx_id: 'PA-TC-0001', continues_previous: false,
      documented_transaction: { transaction_type: 'Sale', executed_date: '06-12-2007', transferors: ['Manohar'], transferees: ['Dinanath'] },
    }],
  },
};

const STATE: VerificationState = {
  case_id: 'C1',
  run: { id: 'r1', kind: 'full', status: 'done', started_at: '' },
  case_file: {
    transfers: [{
      id: 'PA-TC-0001', origin: 'phase_a',
      transaction: { transaction_type: 'Sale', executed_date: '06-12-2007', transferors: ['Manohar'], transferees: ['Dinanath'], source_refs: [{ doc_id: 'DOC_018', filename: 'SaleDeed 2007.pdf' }] },
      property: { type: 'agricultural_land', extent: '2 acres' },
      documents: [
        { name: 'Sale deed of 2007', proves: 'The sale itself.', status: 'found' },
        { name: 'GPA to Girish', proves: 'Authority to sell.', status: 'missing', request_id: 'R1' },
      ],
      concerns: [{ severity: 'high', text: 'GPA authority not shown.' }],
      summary: 'Registered sale by a GPA holder whose authority is not shown.',
      result: 'defective',
      before_root: false,
    }],
    property_today: {
      encumbrances: { note: 'The EC to date shows no charge.', documents: [], concerns: [], ok: true },
      revenue_records: null,
      tax_and_approvals: null,
    },
    requests: [
      { id: 'R1', document: 'Registered GPA to Girish', reason: 'Authority to sell.', needed_for: ['PA-TC-0001'], status: 'open' },
      { id: 'R2', document: 'Release deed', reason: 'Mortgage.', needed_for: [], status: 'settled' },
    ],
    documents: {
      DOC_018: { doc_id: 'DOC_018', filename: 'SaleDeed 2007.pdf', document_type: 'SALE_DEED', examined: true },
      DOC_002: { doc_id: 'DOC_002', filename: 'EC 2010 to 2026.pdf', document_type: 'ENCUMBRANCE_CERTIFICATE', examined: true },
    },
  },
  report: {
    version: 1,
    opinion: 'NOT_CLEAR',
    reasons: ['The 2007 sale lacks GPA authority.'],
    findings: [],
    changes: [],
  },
};

function render(state: VerificationState | null, running = false, page: 'chain' | 'report' = 'report') {
  return renderToStaticMarkup(
    <CaseResultsView
      caseId="C1" results={RESULTS} chainBusy={false} onRebuildChain={() => {}} onOpenPdf={() => {}}
      state={state} events={[]} error={null} running={running} uploadingId={null} start={() => {}} upload={() => {}}
      page={page} onPageChange={() => {}}
    />,
  );
}

function order(html: string, texts: string[]) {
  const positions = texts.map(text => html.indexOf(text));
  positions.forEach((position, i) => assert.ok(position >= 0, `Missing ${texts[i]}`));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
}

test('report page is one page: opinion, findings and documents needed; no per-transfer detail', () => {
  const html = render(STATE);
  order(html, ['Title not clear', 'id="cr-findings-title"', 'id="cr-needed-title"']);
  assert.match(html, /cr-chip cr-tone-bad">1 critical</);
  assert.match(html, /cr-badge cr-tone-bad">Critical<\/span><h4>Sale of 2007<\/h4>/);
  assert.doesNotMatch(html, /cr-limits-title|Limitations/);
  assert.doesNotMatch(html, /cr-timeline|cr-docs|Flow of title|Manohar sold to Dinanath|Scrutiny/);
  // Without saved findings, the page builds them from the transfer's concerns.
  assert.match(html, /GPA authority not shown\./);
  assert.match(html, /<h1>CTS 1360B\/9<\/h1>/);  // no schedule in the report: Phase A identity
  assert.match(html, /cr-tab cr-tab-active"[^>]*>.*Verification report/s);
});

test('chain page: property identity, timeline, property today and documents; no report', () => {
  const html = render(STATE, false, 'chain');
  order(html, ['id="cr-identity-title"', 'id="cr-chain-title"', 'id="cr-today-title"', 'id="cr-docs-title"']);
  order(html, ['Encumbrances', 'In order', 'Revenue records', 'Not checked yet']);
  assert.doesNotMatch(html, /cr-issues-title|Documents needed/);
  assert.match(html, /Defective/);  // verdicts show on the timeline
});

test('report page before verification explains it and offers to start', () => {
  const html = render(null);
  assert.match(html, /No verification report yet/);
  assert.equal((html.match(/Verify title/g) || []).length, 2);  // header and empty state
});

test('each document needed names the transfer it is for, in words, not raw ids', () => {
  const html = render(STATE);
  assert.match(html, /cr-needed-for">For: Sale of 2007</);
  assert.doesNotMatch(html, /PA-TC-\d+|DOC_\d+/);
});

test('requests appear once, with upload only for open ones', () => {
  const html = render(STATE);
  assert.equal((html.match(/type="file"/g) || []).length, 1);
  assert.match(html, /1 already settled/);
});

test('the report page shows the opinion, its reasons and the report findings, nothing else', () => {
  const state: VerificationState = {
    ...STATE,
    report: {
      ...STATE.report!,
      findings: [{ title: 'Bank charge not released', text: 'Canara Bank, 2025.', severity: 'high' }],
      changes: ['The sale of 2019: now defective.'],
    },
  };
  const html = render(state);
  order(html, ['Title not clear', 'The 2007 sale lacks GPA authority.', 'What changed since version 0', 'Bank charge not released']);
  assert.doesNotMatch(html, /cr-lede/);  // no property summary line
});

test('no clutter: no task list, no metric tiles, no structured data viewer', () => {
  const html = render(STATE);
  assert.doesNotMatch(html, /transfers verified|View Structured Data|documents examined</);
});

test('main action depends on the state', () => {
  assert.match(render(null), /Verify title/);
  const unfinished = { ...STATE, report: null, run: { ...STATE.run!, status: 'incomplete' as const } };
  assert.match(render(unfinished), /Continue verification/);
  assert.doesNotMatch(render(STATE), /btn btn-primary/);  // done: no accidental re-run button
  assert.match(render(null, true), /Verifying…/);
});

test('a failed run shows the provider error, not just the notice', () => {
  const failed = {
    ...STATE,
    run: { ...STATE.run!, status: 'error' as const, error: 'ModelTimeoutError: Request timed out.' },
  };
  const html = render(failed);
  assert.match(html, /The last verification failed/);
  assert.match(html, /ModelTimeoutError: Request timed out\./);
});

test('while a run is in progress only this run\u2019s steps show, not the previous report', () => {
  const running: VerificationState = {
    ...STATE,
    run: { ...STATE.run!, id: 'r2', status: 'running' },
  };
  const events = [
    { id: 1, run_id: 'r1', kind: 'verdict', text: 'Old step from the last run', created_at: '' },
    { id: 2, run_id: 'r2', kind: 'read', text: 'Reading SaleDeed 2007.pdf', created_at: '' },
  ];
  const html = renderToStaticMarkup(
    <CaseResultsView
      caseId="C1" results={RESULTS} chainBusy={false} onRebuildChain={() => {}} onOpenPdf={() => {}}
      state={running} events={events} error={null} running uploadingId={null} start={() => {}} upload={() => {}}
      page="report" onPageChange={() => {}}
    />,
  );
  assert.match(html, /id="cr-live-title"/);
  assert.match(html, /Reading SaleDeed 2007\.pdf/);
  assert.doesNotMatch(html, /Old step from the last run/);
  assert.doesNotMatch(html, /cr-issues-title|Title not clear|Documents needed/);
});

test('timeline uses the transfer records with coloured results, else the draft chain', () => {
  const verified = renderToStaticMarkup(<ChainTimeline links={timelineLinks(STATE.case_file!.transfers, [])} />);
  assert.match(verified, /cr-tone-bad">Defective/);
  assert.match(verified, /cr-badge cr-tone-bad">Critical<\/span><span>GPA authority not shown/);
  const draft = renderToStaticMarkup(<ChainTimeline links={timelineLinks(undefined, RESULTS.agent.title_chain)} />);
  assert.match(draft, /Manohar → Dinanath/);
});

test('a draft link saved before transferor fields existed renders instead of crashing', () => {
  const draft = [{
    tx_id: 'PA-TC-0001',
    documented_transaction: { transaction_type: 'Sale', executed_date: '06-12-2007' },
  }];
  const html = renderToStaticMarkup(<ChainTimeline links={timelineLinks(undefined, draft)} />);
  assert.match(html, /Sale/);
  assert.match(html, /Earlier owner/);
  assert.match(html, /Acquirer not recorded/);
});

test('labels and polling helpers', () => {
  assert.equal(humanizeType('PROPERTY_REGISTER_CARD'), 'Property register card');
  assert.equal(refLabeller(STATE.case_file)('DOC_002'), 'EC 2010 to 2026.pdf');
  assert.equal(refLabeller(null)('see PA-TC-0009 and DOC_099'), 'see a transfer and the document');
  assert.equal(refLabeller(STATE.case_file)('Follow up on R1.'), 'Follow up on Registered GPA to Girish.');
  assert.equal(refLabeller(STATE.case_file)('encumbrances'), 'Encumbrances');
  const run = { id: 'r', kind: 'full' as const, started_at: '' };
  assert.equal(shouldPoll(null, null, 0), false);
  assert.equal(shouldPoll({ ...STATE, run: { ...run, status: 'running' } }, null, 0), true);
  assert.equal(shouldPoll(null, 1000, 2000), true);
  assert.equal(shouldPoll(null, 0, 10 * 60 * 1000), false);
});

test('live feed reads in words, even for saved steps that mention ids', () => {
  const label = refLabeller(STATE.case_file);
  const html = renderToStaticMarkup(<LiveFeed running label={label} events={[
    { id: 1, run_id: 'r', kind: 'lead', text: 'Discovered (L1): check PA-TC-0001', created_at: '' },
    { id: 2, run_id: 'r', kind: 'read', text: 'Reading DOC_018 pages 1-2', created_at: '' },
    { id: 3, run_id: 'r', kind: 'chain', text: 'Break before PA-TC-0001: R1 covers it', created_at: '' },
  ]} />);
  assert.match(html, /Reading SaleDeed 2007\.pdf pages 1-2/);
  assert.match(html, /Break before Sale of 2007: Registered GPA to Girish covers it/);
  assert.doesNotMatch(html, /PA-TC-0001|DOC_018|>R1</);
});

test('saved report text written with ids renders in words', () => {
  const state: VerificationState = {
    ...STATE,
    report: {
      ...STATE.report!,
      reasons: ['See PA-TC-0001 and DOC_018; request R1.'],
      changes: ['PA-TC-0001 is now verified; see I1.'],
    },
  };
  const html = render(state);
  assert.match(html, /See Sale of 2007 and SaleDeed 2007\.pdf; request Registered GPA to Girish/);
  assert.doesNotMatch(html, /PA-TC-0001|DOC_018|\bI1\b|\bL1\b|\bR1\b/);
});

test('header names the property from the Phase A identity, and titles drop internal ids', async () => {
  const { propertyLine } = await import('./CaseResults');
  const { cleanTitle } = await import('./ReportView');
  assert.equal(propertyLine(RESULTS, STATE), 'CTS 1360B/9');
  assert.equal(propertyLine(RESULTS, null), 'CTS 1360B/9');
  assert.equal(cleanTitle('PA-TC-0002 — Partition dated 09/06/2008'), 'Partition dated 09/06/2008');
  assert.equal(cleanTitle('I2 — Extent inconsistent'), 'Extent inconsistent');
  assert.equal(cleanTitle('Canara Bank deposit'), 'Canara Bank deposit');
});

test('after verification, a document left unread is shown as not examined', () => {
  const state: VerificationState = {
    ...STATE,
    case_file: {
      ...STATE.case_file!,
      documents: { ...STATE.case_file!.documents, DOC_002: { ...STATE.case_file!.documents.DOC_002, examined: false } },
    },
  };
  const html = render(state, false, 'chain');
  assert.match(html, /EC 2010 to 2026\.pdf.*?Not examined/s);
});

test('chain page shows what each transfer conveyed, the documents that prove it and its concerns', () => {
  const html = render(STATE, false, 'chain');
  assert.match(html, /cr-type">Agricultural land</);
  assert.match(html, /Sale deed of 2007.*?Found.*?GPA to Girish.*?Needed/s);
  assert.match(html, /Registered sale by a GPA holder whose authority is not shown\./);
});

test('a transfer added during verification is shown with why it was added', () => {
  const inserted = {
    ...STATE.case_file!.transfers[0],
    id: 'VL-1', origin: 'verification' as const, added_because: { note: 'The 2010 deed recites it.' },
  };
  const html = renderToStaticMarkup(<ChainTimeline links={timelineLinks([inserted], RESULTS.agent.title_chain)} />);
  assert.match(html, /Added during verification/);
  assert.match(html, /Why it was added: The 2010 deed recites it\./);
});

test('a break shows above the transfer it comes before', () => {
  const broken = { ...STATE.case_file!.transfers[0], connects: { ok: false, note: 'No deed from Manohar.' } };
  const html = renderToStaticMarkup(<ChainTimeline links={timelineLinks([broken], [])} />);
  assert.match(html, /cr-break.*?Break in the chain: No deed from Manohar\./s);
});

test('after a run, the report page shows no agent steps', () => {
  const html = render(STATE);
  assert.doesNotMatch(html, /Agent steps|vf-feed/);
});
