import { useState, useEffect, useCallback } from 'react';
import type { SnapshotResponse } from '../types/snapshot';
import { fetchSnapshot, isAbortError, subscribeToUpdates } from '../services/api';

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : 'Failed to load snapshot';

export function useSnapshot(timeWindow: string = '24h') {
  const [data, setData] = useState<SnapshotResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [streamError, setStreamError] = useState<boolean>(false);
  const [isOffline, setIsOffline] = useState<boolean>(
    () => typeof navigator !== 'undefined' && navigator.onLine === false,
  );
  const [reloadToken, setReloadToken] = useState<number>(0);

  const refresh = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(
    () =>
      subscribeToUpdates(refresh, (connected) => {
        setStreamError(!connected);
      }),
    [refresh],
  );

  useEffect(() => {
    const handleOnline = () => {
      setIsOffline(false);
      refresh();
    };
    const handleOffline = () => setIsOffline(true);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);

    const load = async (initial: boolean) => {
      if (!navigator.onLine) {
        setIsOffline(true);
        if (initial) setIsLoading(false);
        return;
      }
      try {
        const snapshot = await fetchSnapshot(timeWindow, controller.signal);
        if (!active) return;
        setData(snapshot);
        setError(null);
        setLastUpdated(new Date());
        setIsOffline(false);
      } catch (err: unknown) {
        if (!active || isAbortError(err)) return;
        setError(errorMessage(err));
      } finally {
        if (active && initial) setIsLoading(false);
      }
    };

    load(true);

    // Polling keeps the snapshot honest when the SSE connection is unavailable.
    const interval = window.setInterval(() => {
      if (active) load(false);
    }, 60000);

    return () => {
      active = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [timeWindow, reloadToken]);

  const isStale = Boolean(data) && (Boolean(error) || isOffline);

  return {
    data,
    isLoading,
    error,
    lastUpdated,
    streamError,
    isOffline,
    isStale,
    refresh,
  };
}
