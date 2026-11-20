// The case-level issue list: what a buyer must know, most serious first.
import type { DueDiligenceReport, VerificationCaseFile, VerificationLink } from '../../api/backend';
import { humanizeType, yearOf } from './labels';

export interface CaseIssue {
  title: string;
  text: string;
  severity: 'high' | 'medium' | 'low';
  refs: string[];
}

function transferName(link: VerificationLink): string {
  const year = yearOf(link.transaction.executed_date || link.transaction.registration_date);
  return `${humanizeType(link.transaction.transaction_type)}${year ? ` of ${year}` : ''}`;
}

const ORDER = { high: 0, medium: 1, low: 2 };

/** Issues from the report when it has them (newer reports), else derived from the Case File
 * the same way the backend builds them: recorded issues plus uncovered defects and breaks. */
export function caseIssues(report: DueDiligenceReport | null, caseFile: VerificationCaseFile | null): CaseIssue[] {
  const section = report?.sections.find(item => item.id === 'issues');
  if (section) {
    return section.blocks.flatMap(block => block.type === 'findings'
      ? block.items.map(item => ({
        title: item.title,
        text: item.text,
        severity: (item.severity as CaseIssue['severity']) || 'low',
        refs: item.refs || [],
      }))
      : []);
  }
  if (!caseFile) return [];
  const issues: CaseIssue[] = caseFile.issues.map(issue => ({
    title: issue.title, text: issue.detail, severity: issue.severity, refs: [issue.id, ...issue.link_ids],
  }));
  const covered = new Set(caseFile.issues.flatMap(issue => issue.link_ids));
  caseFile.chain.forEach((link, index) => {
    if (covered.has(link.link_id)) return;
    if (link.verdict?.verdict === 'defective') {
      issues.push({ title: `${transferName(link)} is defective`, text: link.verdict.summary, severity: 'high', refs: [link.link_id] });
    }
    if (index > 0 && !link.continues_previous) {
      issues.push({
        title: `Break in the title chain before the ${transferName(link).toLowerCase()}`,
        text: link.break_note || 'No document shows how ownership passed.',
        severity: 'high',
        refs: [link.link_id],
      });
    }
  });
  return issues.sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
}
