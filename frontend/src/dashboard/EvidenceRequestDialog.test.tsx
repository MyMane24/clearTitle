import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { EvidenceRequestDialog } from './EvidenceRequestDialog';

const requirements = [
  {
    document_type: 'Sale deed dated 25-03-2021, BEL-1-21142-2020-21',
    reason: 'Establishes the operative conveyance, parties, complete property schedule and registration particulars.',
  },
  {
    document_type: 'Approved layout plan — Plot 9, CTS 1360B/9',
    reason: 'Establishes that the conveyed CTS plot is within the land allotted to the vendor.',
  },
];

function render(uploads: Record<number, File | undefined> = {}, busy = false): string {
  return renderToStaticMarkup(
    <EvidenceRequestDialog
      transactionId="PA-TC-0005"
      requirements={requirements}
      uploads={uploads}
      busy={busy}
      onPick={() => {}}
      onSubmit={() => {}}
      onSkip={() => {}}
    />,
  );
}

test('each requested document renders its own upload slot plus Submit and Skip', () => {
  const html = render();
  assert.match(html, /Sale deed dated 25-03-2021/);
  assert.match(html, /Approved layout plan/);
  assert.equal((html.match(/type="file"/g) || []).length, requirements.length);
  assert.match(html, /Submit &amp; resume verification/);
  assert.match(html, /Skip this transaction/);
  // No legacy bulk control.
  assert.doesNotMatch(html, /Upload requested evidence/);
});

test('submit is disabled until a document is chosen, then names the file, enables submit, and offers remove', () => {
  const empty = render();
  assert.match(empty, /title="Upload at least one document first"/);
  const file = new File(['x'], 'sale-deed-2021.pdf', { type: 'application/pdf' });
  const withFile = render({ 0: file });
  assert.match(withFile, /sale-deed-2021\.pdf/);
  assert.match(withFile, /Submit &amp; resume verification \(1\)/);
  assert.match(withFile, /Remove sale-deed-2021\.pdf/);
  assert.doesNotMatch(withFile, /disabled/);
});

test('busy state disables every control', () => {
  const file = new File(['x'], 'deed.pdf', { type: 'application/pdf' });
  const html = render({ 0: file }, true);
  assert.match(html, /Working…/);
  assert.equal((html.match(/disabled=/g) || []).length, 5);
});

test('retry variant uses its own title, submit and cancel labels, and shows a fallback slot when no requirements', () => {
  const retryHtml = renderToStaticMarkup(
    <EvidenceRequestDialog
      transactionId="PA-TC-0005"
      requirements={requirements}
      uploads={{}}
      busy={false}
      onPick={() => {}}
      onSubmit={() => {}}
      onSkip={() => {}}
      title="Evidence needed for PA-TC-0005"
      submitLabel="Submit & retry verification"
      skipLabel="Cancel"
    />,
  );
  assert.match(retryHtml, /Evidence needed for PA-TC-0005/);
  assert.match(retryHtml, /Submit &amp; retry verification/);
  assert.match(retryHtml, /Cancel/);
  assert.doesNotMatch(retryHtml, /Skip this transaction/);
  assert.doesNotMatch(retryHtml, /resume verification/);
  const fallbackHtml = renderToStaticMarkup(
    <EvidenceRequestDialog
      transactionId="PA-TC-0005"
      requirements={[]}
      uploads={{}}
      busy={false}
      onPick={() => {}}
      onSubmit={() => {}}
    />,
  );
  assert.match(fallbackHtml, /Supporting document/);
  assert.doesNotMatch(fallbackHtml, /Skip this transaction/);
});
