import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { API, type VerificationEvent, type VerificationState } from '../../api/backend';
import { AgentPlan } from './AgentPlan';
import { DueDiligenceReport } from './DueDiligenceReport';
import { LiveFeed } from './LiveFeed';
import { Requisitions } from './Requisitions';

const POLL_MS = 2000;
const WAIT_FOR_START_MS = 2 * 60 * 1000;

/** True while the dashboard should keep polling: a run is going, or one is about to start. */
export function shouldPoll(state: VerificationState | null, startRequestedAt: number | null, now: number): boolean {
  if (state?.run?.status === 'running') return true;
  if (state?.case_file?.requisitions.some(item => item.status === 'fulfilled')) return true;
  return startRequestedAt !== null && now - startRequestedAt < WAIT_FOR_START_MS;
}

function startLabel(state: VerificationState | null): string {
  if (!state?.case_file) return 'Verify title';
  if (state.run && ['incomplete', 'error'].includes(state.run.status)) return 'Continue verification';
  return 'Run verification again';
}

/** Title verification: start it, watch the agent work, then read the report. */
export function VerificationPanel({ caseId, chainReady }: { caseId: string; chainReady: boolean }) {
  const [state, setState] = useState<VerificationState | null>(null);
  const [events, setEvents] = useState<VerificationEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [startRequestedAt, setStartRequestedAt] = useState<number | null>(null);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const cursorRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const runBeforeStartRef = useRef<string | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    const [fresh, feed] = await Promise.all([
      API.getVerification(caseId),
      API.getVerificationEvents(caseId, cursorRef.current),
    ]);
    if (feed.events.length) {
      cursorRef.current = feed.events[feed.events.length - 1].id;
      setEvents(previous => [...previous, ...feed.events]);
    }
    setState(fresh);
    // The queued start was picked up once a run other than the previous one appears.
    if (fresh.run && fresh.run.id !== runBeforeStartRef.current) setStartRequestedAt(null);
    return fresh;
  }, [caseId]);

  useEffect(() => {
    cursorRef.current = 0;
    setEvents([]);
    setState(null);
    setError(null);
    refresh().catch(e => setError(e.message));
  }, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!shouldPoll(state, startRequestedAt, Date.now())) return;
    timerRef.current = window.setTimeout(() => {
      refresh().catch(e => setError(e.message));
    }, POLL_MS);
    return () => { if (timerRef.current) window.clearTimeout(timerRef.current); };
  }, [state, events, startRequestedAt, refresh]);

  const start = async () => {
    setError(null);
    try {
      runBeforeStartRef.current = state?.run?.id ?? null;
      await API.startVerification(caseId);
      setStartRequestedAt(Date.now());
    } catch (e: any) {
      setError(e.message);
    }
  };

  const upload = async (requisitionId: string, file: File) => {
    setError(null);
    setUploadingId(requisitionId);
    try {
      await API.uploadForRequisition(caseId, requisitionId, file);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploadingId(null);
    }
  };

  const waitingToStart = startRequestedAt !== null && Date.now() - startRequestedAt < WAIT_FOR_START_MS;
  const running = state?.run?.status === 'running' || waitingToStart;
  const caseFile = state?.case_file;

  return (
    <section className="vf-panel" aria-labelledby="vf-panel-title">
      <header className="vf-panel-header">
        <div>
          <span className="vf-kicker"><ShieldCheck size={13} /> TITLE VERIFICATION</span>
          <h2 id="vf-panel-title">Verify the title chain</h2>
          <p className="vf-muted">
            The agent reads every document, checks each transfer against its own evidence, follows up
            anything unexpected, and notes missing documents without stopping.
          </p>
        </div>
        <button
          className="btn btn-primary"
          type="button"
          disabled={!chainReady || running}
          onClick={start}
          title={chainReady ? undefined : 'Build the title chain first'}
        >
          <ShieldCheck size={14} /> {running ? 'Verifying…' : startLabel(state)}
        </button>
      </header>

      {error && <p className="vf-error"><AlertTriangle size={14} /> {error}</p>}
      {state?.run && ['incomplete', 'error'].includes(state.run.status) && !running && (
        <p className="vf-error">
          <AlertTriangle size={14} />
          {state.run.status === 'incomplete'
            ? 'The last run stopped at its model-call budget. Progress is saved; continue to finish.'
            : 'The last run failed. Progress is saved; continue to retry.'}
        </p>
      )}

      {(running || events.length > 0) && (
        <div className="vf-work">
          {caseFile && <AgentPlan caseFile={caseFile} />}
          <LiveFeed events={events} running={running} />
        </div>
      )}

      {caseFile && (
        <Requisitions
          requisitions={caseFile.requisitions}
          busyId={uploadingId}
          disabled={running || uploadingId !== null}
          onUpload={upload}
        />
      )}

      {state?.report && <DueDiligenceReport report={state.report} />}
    </section>
  );
}
