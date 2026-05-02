import { useEffect, useState } from 'react';

/**
 * Repeatedly invokes ``fn`` and stores its result, refreshing every
 * ``intervalMs`` milliseconds. Errors are surfaced via ``state.error``;
 * the loop keeps running so transient API hiccups don't kill the page.
 *
 * SPEC §5.4 / Fase 7: realtime updates of tunnel status. We picked
 * polling over websockets because the consultant population is small
 * (≤ 100) and polling integrates cleanly with the existing JWT auth.
 */
export interface PollResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => Promise<void>;
}

export function usePoll<T>(fn: () => Promise<T>, intervalMs = 5_000): PollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const tick = async () => {
    try {
      const v = await fn();
      setData(v);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = async () => {
      if (!alive) return;
      await tick();
      timer = setTimeout(run, intervalMs);
    };
    void run();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // ``fn`` identity changes per render — but we want to lock onto the first
    // closure, refreshing only when ``intervalMs`` changes. Components that
    // need re-binding should bump their dependency via key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { data, error, loading, refetch: tick };
}
