import React, { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Check, Plus, Waypoints } from 'lucide-react';
import { useAuth } from '../../auth/AuthContext';
import { PageShell } from './PageShell';
import {
  addWatchlineEntry,
  fetchStorylines,
  fetchWatchlineEntries,
  removeWatchlineEntry,
} from '../../services/atlas';
import { ApiError, isAbortError } from '../../services/api';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import type { Storyline, StorylinesResponse, WatchlineEntry } from '../../types/atlas';
import './Storylines.css';

const WINDOWS = ['1h', '24h', '7d', '30d'] as const;
type TimeWindow = (typeof WINDOWS)[number];
const TYPES = ['all', 'military', 'talks', 'trade', 'sanctions', 'aid'] as const;
type RelationType = (typeof TYPES)[number];

const TYPE_LABEL: Record<string, string> = {
  military: 'Military',
  talks: 'Talks',
  trade: 'Trade',
  sanctions: 'Sanctions',
  aid: 'Aid',
};

const STAGE_LABEL: Record<string, string> = {
  proposed: 'Proposed',
  negotiating: 'Negotiating',
  agreed: 'Agreed',
  violated: 'Violated',
  active: 'Active',
};

export const StorylinesPage: React.FC = () => {
  const auth = useAuth();
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('24h');
  const [type, setType] = useState<RelationType>('all');
  const [data, setData] = useState<StorylinesResponse | null>(null);
  const [entries, setEntries] = useState<WatchlineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(!data);
    setRefreshing(Boolean(data));
    setError(null);
    fetchStorylines(timeWindow, controller.signal)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(err instanceof Error ? err.message : 'Could not load storylines.');
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
    // `data` is read only to distinguish a first load from a window refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeWindow, reloadToken]);

  useEffect(() => {
    if (!auth.user) return;
    fetchWatchlineEntries()
      .then((result) => setEntries(result.entries))
      .catch(() => undefined);
  }, [auth.user]);

  const followed = useMemo(() => {
    const index = new Map<string, WatchlineEntry>();
    for (const entry of entries) {
      if (entry.kind === 'arc') index.set(entry.key, entry);
    }
    return index;
  }, [entries]);

  const storylines = (data?.storylines || []).filter(
    (arc) => type === 'all' || arc.type === type,
  );

  const toggleFollow = async (arc: Storyline) => {
    if (!auth.user) {
      navigate(`/login?next=${encodeURIComponent('/storylines')}`);
      return;
    }
    const existing = followed.get(arc.id);
    setBusyId(arc.id);
    setMessage(null);
    try {
      if (existing) {
        const result = await removeWatchlineEntry(existing.id);
        setEntries(result.entries);
        setMessage('Storyline removed from your watchline.');
      } else {
        const result = await addWatchlineEntry('arc', arc.id, '');
        setEntries(result.entries);
        setMessage('Storyline followed. It now appears on your watchline.');
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate(`/login?next=${encodeURIComponent('/storylines')}`);
        return;
      }
      setMessage(err instanceof Error ? err.message : 'Could not update the storyline.');
    } finally {
      setBusyId(null);
    }
  };

  const pair = (arc: Storyline) =>
    arc.countries.length ? arc.countries.join(' / ') : `${arc.a} – ${arc.b}`;

  return (
    <PageShell
      kicker="Relations desk"
      title="Storylines"
      standfirst="Countries that keep appearing in the same dispatches. Each line is a real co-occurrence pattern in the reporting, with its own stage and weight — not a forecast."
      meta={
        <>
          <span>{timeWindow.toUpperCase()} window</span>
          {data && <span>{data.total_storylines} storylines</span>}
          {data?.generated_at && <span>Snapshot {formatRelativeTime(data.generated_at)}</span>}
        </>
      }
      actions={
        <>
          <div className="page-windows" role="group" aria-label="Time window">
            {WINDOWS.map((value) => (
              <button
                key={value}
                type="button"
                className={timeWindow === value ? 'is-active' : ''}
                aria-pressed={timeWindow === value}
                onClick={() => setTimeWindow(value)}
              >
                {value}
              </button>
            ))}
          </div>
          {refreshing && (
            <span className="page-refreshing" role="status">
              Refreshing…
            </span>
          )}
        </>
      }
    >
      <div className="storyline-filters" role="group" aria-label="Relation type">
        {TYPES.map((value) => (
          <button
            key={value}
            type="button"
            className={type === value ? 'is-active' : ''}
            aria-pressed={type === value}
            onClick={() => setType(value)}
          >
            {value === 'all' ? 'All relations' : TYPE_LABEL[value]}
          </button>
        ))}
      </div>

      {message && (
        <p className="storyline-message" role="status">
          {message}
        </p>
      )}

      {loading && !data ? (
        <div className="page-loading" role="status">Reading the relations desk…</div>
      ) : error ? (
        <div className="page-error" role="alert">
          <h2>Storylines could not be read.</h2>
          <p>{error}</p>
          <button
            type="button"
            className="page-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            Try again
          </button>
        </div>
      ) : data?.available === false ? (
        <div className="page-empty" role="status">
          <Waypoints size={22} aria-hidden="true" />
          <h2>The relations desk is temporarily unavailable.</h2>
          <p>The snapshot exists, but its storyline extract is not ready yet.</p>
          <button
            type="button"
            className="page-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            Try again
          </button>
        </div>
      ) : storylines.length === 0 ? (
        <div className="page-empty">
          <Waypoints size={22} aria-hidden="true" />
          <h2>No storyline in this cut.</h2>
          <p>Try a different relation type or widen the time window.</p>
        </div>
      ) : (
        <ol className="storyline-list">
          {storylines.map((arc, index) => {
            const isFollowed = followed.has(arc.id);
            return (
              <li key={arc.id} className="storyline">
                <div className="storyline__index">{String(index + 1).padStart(2, '0')}</div>
                <div className="storyline__main">
                  <div className="storyline__top">
                    <div>
                      <span className={`storyline__type storyline__type--${arc.type}`}>
                        {TYPE_LABEL[arc.type] || arc.type}
                      </span>
                      <span className="storyline__stage">{STAGE_LABEL[arc.stage] || arc.stage}</span>
                    </div>
                    <button
                      type="button"
                      className={`storyline__follow${isFollowed ? ' is-followed' : ''}`}
                      onClick={() => toggleFollow(arc)}
                      disabled={busyId === arc.id || auth.loading}
                    >
                      {isFollowed ? <Check size={12} /> : <Plus size={12} />}
                      {isFollowed ? 'Following' : 'Follow'}
                    </button>
                  </div>

                  <h2 className="storyline__pair">{pair(arc)}</h2>
                  <p className="storyline__meta">
                    {arc.window_events} dispatches in this window · {arc.total_events} tracked ·{' '}
                    {arc.direction === 'bidirectional' ? 'two-way' : 'one-way'} relation
                  </p>

                  {arc.events.length > 0 && (
                    <ul className="storyline__events">
                      {arc.events.map((event) => (
                        <li key={event.id}>
                          <button type="button" onClick={() => navigate(`/event/${event.id}`)}>
                            <span>{event.title}</span>
                            <span className="storyline__event-meta">
                              {event.outlet_count} {event.outlet_count === 1 ? 'outlet' : 'outlets'}
                              {event.updated_at ? ` · ${formatRelativeTime(event.updated_at)}` : ''}
                            </span>
                            <ArrowUpRight size={13} aria-hidden="true" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="storyline__weight" aria-label={`Weight ${Math.round((arc.importance || 0) * 100)}`}>
                  <span>{Math.round((arc.importance || 0) * 100)}</span>
                  <small>weight</small>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <p className="page-note">
        A storyline is extracted from events that name both countries and share a relation type.
        Only relations with at least two dispatches in the selected window and three on record are
        shown. Weight combines coverage breadth and event importance; it is not a probability.
      </p>
    </PageShell>
  );
};
