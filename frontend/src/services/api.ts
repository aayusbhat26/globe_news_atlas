import type { SnapshotResponse } from '../types/snapshot';
import type { HoverCardData, EventDetailData, SearchApiResult } from '../types/event';
import type { CountryBriefResponse } from '../types/country';

export const API_BASE = import.meta.env.VITE_API_URL
  || (import.meta.env.DEV && typeof window !== 'undefined'
    ? `http://${window.location.hostname}:8000/v1`
    : '/v1');

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

interface ApiDetail {
  code?: string;
  message?: string;
  msg?: string;
}

function readErrorPayload(payload: unknown, status: number): { code: string; message: string } {
  let code = 'request_failed';
  let message = `Request failed (${status}).`;
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') {
      message = detail;
    } else if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as ApiDetail;
      message = first?.msg || message;
    } else if (detail && typeof detail === 'object') {
      const structured = detail as ApiDetail;
      code = structured.code || code;
      message = structured.message || message;
    }
  }
  return { code, message };
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      signal: init?.signal || AbortSignal.timeout(20000),
      headers: { Accept: 'application/json', ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new ApiError(0, 'timeout', 'The server took too long to respond. Try again.');
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.');
  }
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const { code, message } = readErrorPayload(payload, response.status);
    throw new ApiError(response.status, code, message);
  }
  return payload as T;
}

export interface FeedbackPayload {
  event_id?: string;
  category: string;
  details?: string;
}

export function submitFeedback(
  payload: FeedbackPayload,
): Promise<{ status: string; id: string }> {
  return requestJson('/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function fetchSnapshot(window: string = '24h'): Promise<SnapshotResponse> {
  return requestJson<SnapshotResponse>(`/snapshot?window=${encodeURIComponent(window)}`);
}

export function fetchCountryBrief(
  name: string,
  iso2: string | undefined,
  window: string,
  signal?: AbortSignal,
): Promise<CountryBriefResponse> {
  const params = new URLSearchParams({ name, window });
  if (iso2) params.set('iso2', iso2);
  return requestJson<CountryBriefResponse>(`/countries/brief?${params.toString()}`, { signal });
}

export function fetchEventCard(eventId: string): Promise<HoverCardData> {
  return requestJson<HoverCardData>(`/events/${encodeURIComponent(eventId)}/card`);
}

export function fetchEventDetail(eventId: string): Promise<EventDetailData> {
  return requestJson<EventDetailData>(`/events/${encodeURIComponent(eventId)}`);
}

export function fetchSearchResults(
  query: string,
  window: string = '30d',
  limit: number = 20,
  signal?: AbortSignal,
): Promise<SearchApiResult[]> {
  const params = new URLSearchParams({ q: query, window, limit: String(limit) });
  return requestJson<SearchApiResult[]>(`/search?${params.toString()}`, { signal });
}

export function subscribeToUpdates(onUpdate: () => void): () => void {
  if (typeof EventSource === 'undefined') return () => {};
  const source = new EventSource(`${API_BASE}/stream`);
  const handleUpdate = () => onUpdate();
  source.addEventListener('snapshot_updated', handleUpdate);
  return () => {
    source.removeEventListener('snapshot_updated', handleUpdate);
    source.close();
  };
}
