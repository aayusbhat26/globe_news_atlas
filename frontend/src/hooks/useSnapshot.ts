import { useState, useEffect, useCallback } from 'react';
import type { SnapshotResponse } from '../types/snapshot';
import { fetchSnapshot, subscribeToUpdates } from '../services/api';

export function useSnapshot(timeWindow: string = '24h') {
  const [data, setData] = useState<SnapshotResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(() => new Date());
  const [reloadToken, setReloadToken] = useState<number>(0);

  const refresh = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => subscribeToUpdates(refresh), [refresh]);

  useEffect(() => {
    let isMounted = true;
    setIsLoading(true);
    setError(null);

    fetchSnapshot(timeWindow)
      .then((snapshot) => {
        if (isMounted) {
          setData(snapshot);
          setError(null);
          setIsLoading(false);
          setLastUpdated(new Date());
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to load snapshot');
          setIsLoading(false);
        }
      });

    // Optional 60-second polling for live news refresh
    const interval = setInterval(() => {
      fetchSnapshot(timeWindow)
        .then((snapshot) => {
          if (isMounted) {
            setData(snapshot);
            setError(null);
            setLastUpdated(new Date());
          }
        })
        .catch(() => {});
    }, 60000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [timeWindow, reloadToken]);

  return { data, isLoading, error, lastUpdated, refresh };
}
