import { authRequest } from './auth';
import { requestJson } from './api';
import type {
  Citation,
  PulseResponse,
  RewindResponse,
  StorylinesResponse,
  ThinFile,
  WatchlineEntry,
  WatchlineFeed,
} from '../types/atlas';

export function fetchWatchline(window = '24h'): Promise<WatchlineFeed> {
  return requestJson<WatchlineFeed>(`/watchline?window=${encodeURIComponent(window)}`);
}

export function fetchWatchlineEntries(): Promise<{ entries: WatchlineEntry[] }> {
  return requestJson<{ entries: WatchlineEntry[] }>('/watchline/entries');
}

export function fetchWatchlineOptions(): Promise<{
  places: Array<{ name: string; events: number }>;
  generated_at: string | null;
}> {
  return requestJson('/watchline/options');
}

export function addWatchlineEntry(
  kind: 'place' | 'arc',
  key: string,
  label = '',
): Promise<{ status: string; entry: WatchlineEntry; entries: WatchlineEntry[] }> {
  return authRequest('/watchline/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, key, label }),
  });
}

export function removeWatchlineEntry(
  entryId: string,
): Promise<{ status: string; entries: WatchlineEntry[] }> {
  return authRequest(`/watchline/entries/${encodeURIComponent(entryId)}`, {
    method: 'DELETE',
  });
}

export function markWatchlineSeen(): Promise<{ last_seen: string }> {
  return authRequest('/watchline/seen', { method: 'POST', body: '{}' });
}

export function fetchPublicWatchline(keys: string[], window = '24h'): Promise<WatchlineFeed> {
  const params = new URLSearchParams({ window });
  for (const key of keys) params.append('keys', key);
  return requestJson<WatchlineFeed>(`/watchline/public?${params.toString()}`);
}

export function fetchStorylines(window = '24h'): Promise<StorylinesResponse> {
  return requestJson<StorylinesResponse>(`/storylines?window=${encodeURIComponent(window)}`);
}

export function fetchThinFile(window = '24h'): Promise<ThinFile> {
  return requestJson<ThinFile>(`/lenses/thin?window=${encodeURIComponent(window)}`);
}

export function fetchPulse(window = '24h'): Promise<PulseResponse> {
  return requestJson<PulseResponse>(`/pulse?window=${encodeURIComponent(window)}`);
}

export function fetchRewind(): Promise<RewindResponse> {
  return requestJson<RewindResponse>('/rewind');
}

export function fetchCitation(eventId: string): Promise<Citation> {
  return requestJson<Citation>(`/events/${encodeURIComponent(eventId)}/citation`);
}
