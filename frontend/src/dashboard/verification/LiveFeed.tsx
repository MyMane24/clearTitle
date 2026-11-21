import React, { useEffect, useRef } from 'react';
import {
  AlertTriangle, BookOpen, CheckCircle2, FileSearch, FileText, GitBranch, Lightbulb,
  ListChecks, PlayCircle, Search, Sparkles, type LucideIcon,
} from 'lucide-react';
import type { VerificationEvent } from '../../api/backend';

// Diagnostics for us (refused steps, per-turn tool calls, reopened reports), not steps a buyer follows.
const HIDDEN = new Set(['rejected', 'calls', 'reopen']);

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

/** The agent's steps as they happen, newest at the bottom. `label` replaces any internal id
 * left in a saved step with the name a buyer knows. */
export function LiveFeed({ events, running, label }: {
  events: VerificationEvent[];
  running: boolean;
  label: (text: string) => string;
}) {
  const endRef = useRef<HTMLLIElement | null>(null);
  events = events.filter(event => !HIDDEN.has(event.kind));
  // Follow the newest step while a run is live.
  useEffect(() => {
    if (running) endRef.current?.scrollIntoView({ block: 'nearest' });
  }, [events.length, running]);
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
            <span>{label(event.text)}</span>
          </li>
        );
      })}
      {running && <li ref={endRef} className="vf-feed-item vf-feed-pending"><span className="vf-pulse" /> Working…</li>}
    </ol>
  );
}
