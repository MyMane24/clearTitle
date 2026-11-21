// Verification state for one case: loads it, polls while a run is active, starts runs, uploads.
import { useCallback, useEffect, useRef, useState } from 'react';
import { API, type VerificationEvent, type VerificationState } from '../../api/backend';

const POLL_MS = 2000;
const WAIT_FOR_START_MS = 2 * 60 * 1000;

/** True while the page should keep polling: a run is going, or one is about to start. */
export function shouldPoll(state: VerificationState | null, startRequestedAt: number | null, now: number): boolean {
  if (state?.run?.status === 'running') return true;
  if (state?.case_file?.requisitions.some(item => item.status === 'fulfilled')) return true;
  return startRequestedAt !== null && now - startRequestedAt < WAIT_FOR_START_MS;
}

export function useVerification(caseId: string) {
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
  }, [caseId, refresh]);

  useEffect(() => {
    if (!shouldPoll(state, startRequestedAt, Date.now())) return;
    timerRef.current = window.setTimeout(() => {
      refresh().catch(e => setError(e.message));
    }, POLL_MS);
    return () => { if (timerRef.current) window.clearTimeout(timerRef.current); };
  }, [state, events, startRequestedAt, refresh]);

  const start = async (fresh = false) => {
    setError(null);
    try {
      runBeforeStartRef.current = state?.run?.id ?? null;
      await API.startVerification(caseId, fresh);
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
  return { state, events, error, running, uploadingId, start, upload };
}
