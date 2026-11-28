// Readable labels for ids, types and results shown on the results page.
import type { SectionName, VerificationCaseFile, VerificationTransfer } from '../../api/backend';

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

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "06 Dec" from "06-12-2007", "06.12.2007" or "2007-12-06"; empty when the date is none of those. */
export function dayMonth(date: string | null | undefined): string {
  const text = date || '';
  const dmy = text.match(/\b(\d{1,2})[-/.](\d{1,2})[-/.](?:19|20)\d{2}\b/);
  const ymd = text.match(/\b(?:19|20)\d{2}[-/.](\d{1,2})[-/.](\d{1,2})\b/);
  const day = dmy ? dmy[1] : ymd ? ymd[2] : '';
  const month = dmy ? dmy[2] : ymd ? ymd[1] : '';
  const index = Number(month);
  return day && index >= 1 && index <= 12 && Number(day) >= 1 && Number(day) <= 31
    ? `${day} ${MONTHS[index - 1]}`
    : '';
}

/** "Sale of 2010". */
export function transferName(transfer: Pick<VerificationTransfer, 'transaction'>): string {
  const year = yearOf(transfer.transaction.executed_date || transfer.transaction.registration_date);
  return `${humanizeType(transfer.transaction.transaction_type)}${year ? ` of ${year}` : ''}`;
}

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  verified: { label: 'Verified', tone: 'good' },
  verified_with_concerns: { label: 'Verified with concerns', tone: 'warn' },
  documents_missing: { label: 'Waiting for documents', tone: 'warn' },
  defective: { label: 'Defective', tone: 'bad' },
};

export const SECTION_LABEL: Record<SectionName, string> = {
  encumbrances: 'Encumbrances',
  revenue_records: 'Revenue records',
  tax_and_approvals: 'Tax and approvals',
};

// L (lead) and I (issue) ids only appear in reports and steps saved before schema 5.
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
  for (const transfer of caseFile?.transfers || []) labels.set(transfer.id, transferName(transfer));
  for (const item of caseFile?.requests || []) labels.set(item.id, item.document);
  for (const [name, label] of Object.entries(SECTION_LABEL)) labels.set(name, label);
  const resolve = (text: string): string => text.replace(INTERNAL_ID, id => labels.get(id) || fallbackLabel(id));
  return ref => resolve(labels.get(ref) || ref);
}
