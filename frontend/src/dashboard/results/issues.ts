// The case-level findings: what a buyer must know, most serious first, then what checked out.
import type { DueDiligenceReport, SectionName, VerificationCaseFile } from '../../api/backend';
import { SECTION_LABEL, transferName } from './labels';

export interface CaseIssue {
  title: string;
  text: string;
  severity: 'high' | 'medium' | 'low' | 'clear';
}

const ORDER = { high: 0, medium: 1, low: 2, clear: 3 };

/** Findings from the report when it has them, else built from the Case File the same way
 * the backend builds them: each transfer's break and concerns, then the property today. */
export function caseIssues(report: DueDiligenceReport | null, caseFile: VerificationCaseFile | null): CaseIssue[] {
  if (report?.findings?.length) return report.findings;
  if (!caseFile) return [];
  const issues: CaseIssue[] = [];
  for (const transfer of caseFile.transfers.filter(item => !item.before_root)) {
    const name = transferName(transfer);
    if (transfer.connects && !transfer.connects.ok) {
      const missing = transfer.documents.some(doc => doc.status === 'missing');
      issues.push({
        title: `Break in the title chain before the ${name.toLowerCase()}`,
        text: transfer.connects.note,
        severity: missing ? 'medium' : 'high',
      });
    }
    for (const concern of transfer.concerns) issues.push({ title: name, text: concern.text, severity: concern.severity });
  }
  for (const [name, section] of Object.entries(caseFile.property_today || {})) {
    for (const concern of section?.concerns || []) {
      issues.push({ title: SECTION_LABEL[name as SectionName], text: concern.text, severity: concern.severity });
    }
  }
  return issues.sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
}
