// Readable labels for ids, types and verdicts shown on the results page.
import type { VerificationCaseFile } from '../../api/backend';

/** "SALE_DEED" -> "Sale deed". */
export function humanizeType(type: string | null | undefined): string {
  if (!type) return 'Document';
  const text = type.replace(/_/g, ' ').toLowerCase().trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The year in a date such as "06-12-2007" or "2007-12-06", if any. */
export function yearOf(date: string | null | undefined): string {
  const match = (date || '').match(/(19|20)\d{2}/);
  return match ? match[0] : '';
}

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  verified: { label: 'Verified', tone: 'good' },
  verified_with_concerns: { label: 'Verified with concerns', tone: 'warn' },
  unverified_missing_document: { label: 'Document missing', tone: 'neutral' },
  defective: { label: 'Defective', tone: 'bad' },
};

const INTERNAL_ID = /\b(?:PA-TC-\d+|VL-\d+|DOC_\d+|[RLI]\d{1,3})\b/g;

function fallbackLabel(id: string): string {
  if (id.startsWith('DOC_')) return 'the document';
  if (/^(?:PA-TC|VL)-/.test(id)) return 'a transfer';
  if (id.startsWith('R')) return 'a document request';
  if (id.startsWith('L')) return 'a follow-up';
  return 'an issue';
}

/** Maps Case File ids to labels people recognise, and also replaces any id found inside a
 * longer text: the page reads in words even when a saved report or step mentions an id. */
export function refLabeller(caseFile: VerificationCaseFile | null | undefined): (ref: string) => string {
  const labels = new Map<string, string>();
  for (const doc of Object.values(caseFile?.documents || {})) labels.set(doc.doc_id, doc.filename || 'the document');
  for (const link of caseFile?.chain || []) {
    const year = yearOf(link.transaction.executed_date || link.transaction.registration_date);
    labels.set(link.link_id, `${humanizeType(link.transaction.transaction_type)}${year ? ` ${year}` : ''}`);
  }
  for (const issue of caseFile?.issues || []) labels.set(issue.id, issue.title);
  for (const item of caseFile?.requisitions || []) labels.set(item.id, item.document);
  for (const lead of caseFile?.leads || []) labels.set(lead.id, lead.text);
  // Repeat so a label that itself mentions another id ("Follow up on R1") is also resolved.
  const resolve = (text: string): string => {
    let out = text;
    for (let pass = 0; pass < 3; pass++) {
      const next = out.replace(INTERNAL_ID, id => labels.get(id) || fallbackLabel(id));
      if (next === out) break;
      out = next;
    }
    return out;
  };
  return ref => resolve(labels.get(ref) || ref);
}
