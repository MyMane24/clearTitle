import React from 'react';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';
import type { VerificationCaseFile } from '../../api/backend';

/** The agent's own task list and progress counts, like a coding agent's checklist. */
export function AgentPlan({ caseFile }: { caseFile: VerificationCaseFile }) {
  const documents = Object.values(caseFile.documents);
  const examined = documents.filter(d => d.examined).length;
  const verdicts = caseFile.chain.filter(link => link.verdict).length;
  const openLeads = caseFile.leads.filter(lead => lead.status === 'open').length;
  return (
    <div className="vf-plan">
      <div className="vf-metrics">
        <div><strong>{examined}/{documents.length}</strong><span>documents examined</span></div>
        <div><strong>{verdicts}/{caseFile.chain.length}</strong><span>transfers verified</span></div>
        <div><strong>{openLeads}</strong><span>open leads</span></div>
        <div><strong>{caseFile.issues.length}</strong><span>issues</span></div>
      </div>
      {caseFile.tasks.length > 0 && (
        <ul className="vf-tasks">
          {caseFile.tasks.map(task => (
            <li key={task.id} className={`vf-task vf-task-${task.status}`}>
              {task.status === 'done' ? <CheckCircle2 size={14} />
                : task.status === 'in_progress' ? <Loader2 size={14} className="vf-spin" />
                : <Circle size={14} />}
              <span>{task.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
