import React from 'react';
import {
  AlertTriangle, BookOpen, CheckCircle2, FileSearch, FileText, GitBranch, Lightbulb,
  ListChecks, PlayCircle, Search, Sparkles, type LucideIcon,
} from 'lucide-react';
import type { VerificationEvent } from '../../api/backend';

const ICONS: Record<string, LucideIcon> = {
  run: PlayCircle,
  plan: ListChecks,
  examine: FileSearch,
  read: Search,
  skill: BookOpen,
  lead: Lightbulb,
  chain: GitBranch,
  verdict: CheckCircle2,
  issue: AlertTriangle,
  requisition: FileText,
  report: FileText,
  thinking: Sparkles,
};

/** The agent's steps as they happen, newest at the bottom. */
export function LiveFeed({ events, running }: { events: VerificationEvent[]; running: boolean }) {
  if (!events.length) {
    return <p className="vf-empty">{running ? 'Starting…' : 'No verification steps yet.'}</p>;
  }
  return (
    <ol className="vf-feed" aria-live="polite">
      {events.map(event => {
        const Icon = ICONS[event.kind] || Sparkles;
        return (
          <li key={event.id} className={`vf-feed-item vf-feed-${event.kind}`}>
            <Icon size={14} />
            <span>{event.text}</span>
          </li>
        );
      })}
      {running && <li className="vf-feed-item vf-feed-pending"><span className="vf-pulse" /> Working…</li>}
    </ol>
  );
}
