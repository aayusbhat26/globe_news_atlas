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

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

async function performRequest(
  path: string,
  init?: RequestInit,
): Promise<{ payload: unknown; headers: Headers; status: number }> {
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
    if (isAbortError(error)) {
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
  return { payload, headers: response.headers, status: response.status };
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const { payload } = await performRequest(path, init);
  return payload as T;
}

/**
 * Same contract as requestJson, but keeps the response headers. Used where the
 * API reports a true result total alongside a capped payload.
 */
export async function requestJsonWithMeta<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; headers: Headers; status: number }> {
  const { payload, headers, status } = await performRequest(path, init);
  return { data: payload as T, headers, status };
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

export function fetchSnapshot(
  window: string = '24h',
  signal?: AbortSignal,
): Promise<SnapshotResponse> {
  return requestJson<SnapshotResponse>(`/snapshot?window=${encodeURIComponent(window)}`, {
    signal,
  });
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

export interface SearchResponse {
  items: SearchApiResult[];
  /** True archive total when the API sends X-Total-Count; null when it does not. */
  total: number | null;
}

export async function fetchSearchResults(
  query: string,
  window: string = '30d',
  limit: number = 20,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, window, limit: String(limit) });
  const { data, headers } = await requestJsonWithMeta<SearchApiResult[]>(
    `/search?${params.toString()}`,
    { signal },
  );
  const rawTotal = headers.get('X-Total-Count');
  const parsed = rawTotal != null && rawTotal.trim() !== '' ? Number(rawTotal) : NaN;
  return {
    items: Array.isArray(data) ? data : [],
    total: Number.isFinite(parsed) && parsed >= 0 ? parsed : null,
  };
}

export function subscribeToUpdates(
  onUpdate: () => void,
  onStatus?: (connected: boolean) => void,
): () => void {
  if (typeof EventSource === 'undefined') {
    onStatus?.(false);
    return () => {};
  }
  let source: EventSource;
  try {
    source = new EventSource(`${API_BASE}/stream`);
  } catch {
    onStatus?.(false);
    return () => {};
  }
  const handleUpdate = () => onUpdate();
  const handleOpen = () => onStatus?.(true);
  const handleError = () => onStatus?.(false);
  source.addEventListener('snapshot_updated', handleUpdate);
  source.addEventListener('open', handleOpen);
  source.addEventListener('error', handleError);
  source.onopen = handleOpen;
  source.onerror = handleError;
  return () => {
    source.removeEventListener('snapshot_updated', handleUpdate);
    source.removeEventListener('open', handleOpen);
    source.removeEventListener('error', handleError);
    source.close();
  };
}
