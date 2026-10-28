import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUpRight,
  Bookmark,
  Check,
  Copy,
  Link2,
  Plus,
  Sparkles,
  X,
} from 'lucide-react';
import { useAuth } from '../../auth/AuthContext';
import { PageShell } from './PageShell';
import {
  addWatchlineEntry,
  fetchPublicWatchline,
  fetchStorylines,
  fetchWatchline,
  fetchWatchlineOptions,
  markWatchlineSeen,
  removeWatchlineEntry,
} from '../../services/atlas';
import { ApiError, isAbortError } from '../../services/api';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { copyToClipboard } from '../../utils/auth';
import { navigate } from '../../router';
import type { Storyline, WatchlineEntry, WatchlineFeed } from '../../types/atlas';
import './Watchline.css';

const WINDOWS = ['1h', '24h', '7d', '30d'] as const;
type TimeWindow = (typeof WINDOWS)[number];

const errorMessage = (error: unknown): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Sign in to change this watchline.';
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Try again.';
};

export const WatchlinePage: React.FC = () => {
  const auth = useAuth();
  const publicKeys = useMemo(
    () => new URLSearchParams(window.location.search).getAll('keys'),
    [],
  );
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('24h');
  const [feed, setFeed] = useState<WatchlineFeed | null>(null);
  const [entries, setEntries] = useState<WatchlineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const feedRef = useRef<WatchlineFeed | null>(null);
  const requestSeq = useRef(0);
  const [place, setPlace] = useState('');
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [options, setOptions] = useState<Array<{ name: string; events: number }>>([]);
  const [suggestions, setSuggestions] = useState<Storyline[]>([]);
  const [copied, setCopied] = useState(false);
  const [shareFallback, setShareFallback] = useState<string | null>(null);

  const isPublic = !auth.loading && !auth.user && publicKeys.length > 0;
  const signedIn = Boolean(auth.user);

  const load = useCallback(async (signal?: AbortSignal) => {
    const seq = ++requestSeq.current;
    const hasFeed = Boolean(feedRef.current);
    setLoading(!hasFeed);
    setRefreshing(hasFeed);
    setError(null);
    try {
      const data = isPublic
        ? await fetchPublicWatchline(publicKeys, timeWindow, signal)
        : await fetchWatchline(timeWindow, signal);
      if (seq !== requestSeq.current) return;
      feedRef.current = data;
      setFeed(data);
      setEntries(data.entries);
    } catch (err) {
      if (seq !== requestSeq.current || isAbortError(err)) return;
      setError(errorMessage(err));
    } finally {
      if (seq === requestSeq.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [isPublic, publicKeys, timeWindow]);

  useEffect(() => {
    if (auth.loading) return;
    if (!auth.user && publicKeys.length === 0) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [auth.loading, auth.user, load, publicKeys.length, reloadToken]);

  useEffect(() => {
    if (!signedIn) return;
    fetchWatchlineOptions()
      .then((data) => setOptions(data.places))
      .catch(() => undefined);
  }, [signedIn]);

  useEffect(() => {
    if (!signedIn || entries.length > 0) return;
    fetchStorylines('24h')
      .then((data) => setSuggestions(data.storylines.slice(0, 4)))
      .catch(() => undefined);
  }, [signedIn, entries.length]);

  const handleAdd = async (name: string) => {
    const value = name.trim();
    if (!value || adding) return;
    setAdding(true);
    setActionError(null);
    setNotice(null);
    try {
      const result = await addWatchlineEntry('place', value, value);
      setEntries(result.entries);
      setPlace('');
      setNotice(`${result.entry.label} is now on your watchline.`);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate(`/login?next=${encodeURIComponent('/watchline')}`);
        return;
      }
      setActionError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const handleFollowArc = async (arc: Storyline) => {
    setAdding(true);
    setActionError(null);
    try {
      const result = await addWatchlineEntry('arc', arc.id, '');
      setEntries(result.entries);
      setNotice('Storyline followed.');
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate(`/login?next=${encodeURIComponent('/watchline')}`);
        return;
      }
      setActionError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (entry: WatchlineEntry) => {
    setBusyId(entry.id);
    setActionError(null);
    try {
      const result = await removeWatchlineEntry(entry.id);
      setEntries(result.entries);
      await load();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const handleSeen = async () => {
    try {
      const result = await markWatchlineSeen();
      setFeed((current) =>
        current
          ? {
              ...current,
              new_count: 0,
              last_seen: result.last_seen,
              feed: current.feed.map((event) => ({ ...event, fresh: false })),
            }
          : current,
      );
      setNotice('Watchline marked as read.');
    } catch (err) {
      setActionError(errorMessage(err));
    }
  };

  const handleShare = async () => {
    const keys = entries.map((entry) => `${entry.kind}:${entry.key}`);
    const query = keys.map((key) => `keys=${encodeURIComponent(key)}`).join('&');
    const url = `${globalThis.location.origin}/watchline${query ? `?${query}` : ''}`;
    const ok = await copyToClipboard(url);
    setCopied(ok);
    setShareFallback(ok ? null : url);
    if (ok) window.setTimeout(() => setCopied(false), 2200);
  };

  const startSuggestions = suggestions.filter(
    (arc) => !entries.some((entry) => entry.kind === 'arc' && entry.key === arc.id),
  );

  return (
    <PageShell
      kicker={isPublic ? 'Shared reader edition' : 'Reader edition'}
      title={isPublic ? 'A shared Watchline' : signedIn ? 'My Watchline' : 'Your own world desk'}
      standfirst={
        isPublic
          ? 'A read-only desk assembled from pinned places and storylines. Every dispatch opens into its full dossier.'
          : 'Pin the countries and storylines you care about. The desk returns only dispatches that touch them, with what changed since your last visit.'
      }
      meta={
        <>
          <span>{timeWindow.toUpperCase()} window</span>
          {feed?.generated_at && <span>Snapshot {formatRelativeTime(feed.generated_at)}</span>}
          {feed?.last_seen && <span>Last visit {formatRelativeTime(feed.last_seen)}</span>}
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
          {entries.length > 0 && (
            <button type="button" className="page-secondary" onClick={handleShare}>
              {copied ? <Check size={13} /> : <Link2 size={13} />}
              {copied ? 'Link copied' : 'Copy desk link'}
            </button>
          )}
        </>
      }
    >
      {isPublic && (
        <div className="watchline-public-note" role="note">
          <Bookmark size={15} aria-hidden="true" />
          <span>You are reading someone else’s shared desk. You can pin your own after signing in.</span>
          <button
            type="button"
            className="page-primary"
            onClick={() => navigate(`/login?next=${encodeURIComponent('/watchline')}`)}
          >
            Build your own
          </button>
        </div>
      )}

      {shareFallback && (
        <div className="watchline-share-fallback" role="status">
          <label htmlFor="watchline-share-link">Copy this desk link</label>
          <input
            id="watchline-share-link"
            readOnly
            value={shareFallback}
            onFocus={(event) => event.currentTarget.select()}
          />
        </div>
      )}
      <p className="sr-only" role="status" aria-live="polite">
        {shareFallback
          ? 'The clipboard was unavailable. Select and copy the desk link shown above.'
          : copied
            ? 'Desk link copied.'
            : ''}
      </p>

      {feed && (
        <dl className="page-count-strip">
          <div>
            <dt>Pinned desks</dt>
            <dd>{entries.length}</dd>
          </div>
          <div>
            <dt>Dispatches</dt>
            <dd>{feed.matched_total}</dd>
          </div>
          {signedIn && (
            <div>
              <dt>New since last visit</dt>
              <dd>{feed.new_count}</dd>
            </div>
          )}
          <div>
            <dt>{signedIn ? 'Storylines followed' : 'Storylines'}</dt>
            <dd>{feed.arcs.length}</dd>
          </div>
        </dl>
      )}

      {feed && signedIn && feed.new_count > 0 && (
        <section className="watchline-brief" aria-label="Return brief">
          <div>
            <span className="watchline-brief__kicker">Since your last visit</span>
            <p>
              {feed.new_count} {feed.new_count === 1 ? 'dispatch has' : 'dispatches have'} moved on your desk.
            </p>
          </div>
          <button type="button" className="page-secondary" onClick={handleSeen}>
            <Check size={13} /> Mark as read
          </button>
        </section>
      )}

      {signedIn && (
        <section className="page-section watchline-pins" aria-labelledby="watchline-pins-title">
          <div className="page-section__head">
            <h2 id="watchline-pins-title">Pinned desks</h2>
            <span>
              {entries.length} / {feed?.capacity ?? 8}
            </span>
          </div>
          <div className="watchline-pins__row">
            {entries.map((entry) => (
              <span key={entry.id} className={`watchline-pin${entry.kind === 'arc' ? ' watchline-pin--arc' : ''}`}>
                <span>{entry.label}</span>
                <button
                  type="button"
                  onClick={() => handleRemove(entry)}
                  disabled={busyId === entry.id}
                  aria-label={`Remove ${entry.label} from watchline`}
                  title="Remove"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
            {entries.length === 0 && <span className="watchline-pins__empty">Nothing pinned yet.</span>}
          </div>

          <form
            className="watchline-add"
            onSubmit={(event) => {
              event.preventDefault();
              handleAdd(place);
            }}
          >
            <label className="sr-only" htmlFor="watchline-place">
              Country or place
            </label>
            <input
              id="watchline-place"
              type="text"
              list="watchline-places"
              value={place}
              onChange={(event) => setPlace(event.target.value)}
              placeholder="Add a country — India, Ukraine, Brazil…"
              autoComplete="off"
              maxLength={80}
            />
            <datalist id="watchline-places">
              {options.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.events} dispatches in 24h
                </option>
              ))}
            </datalist>
            <button type="submit" className="page-primary" disabled={adding || !place.trim()}>
              <Plus size={13} /> {adding ? 'Adding…' : 'Pin desk'}
            </button>
          </form>
          {actionError && (
            <p className="watchline-message watchline-message--error" role="alert">
              {actionError}
            </p>
          )}
          {notice && (
            <p className="watchline-message" role="status">
              {notice}
            </p>
          )}
        </section>
      )}

      {feed?.arcs && feed.arcs.length > 0 && (
        <section className="page-section" aria-labelledby="watchline-arcs-title">
          <div className="page-section__head">
            <h2 id="watchline-arcs-title">Storylines on this desk</h2>
            <span>Followed relations</span>
          </div>
          <div className="watchline-arcs">
            {feed.arcs.map((arc) => (
              <button
                key={arc.arc_id}
                type="button"
                className="watchline-arc"
                onClick={() => navigate('/storylines')}
              >
                <span className="watchline-arc__label">{arc.label}</span>
                <span className="watchline-arc__meta">
                  {arc.type} · {arc.stage} · {arc.window_events} dispatches this window
                </span>
                <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="page-section" aria-labelledby="watchline-feed-title">
        <div className="page-section__head">
          <h2 id="watchline-feed-title">The desk</h2>
          <span>
            {feed ? `${feed.shown} of ${feed.matched_total} dispatches` : 'Loading'}
          </span>
        </div>

        {loading && !feed ? (
          <div className="page-loading" role="status">Reading your watchline…</div>
        ) : error ? (
          <div className="page-error" role="alert">
            <h2>The desk could not be read.</h2>
            <p>{error}</p>
            <button
              type="button"
              className="page-secondary"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              Try again
            </button>
          </div>
        ) : !auth.loading && !signedIn && !isPublic ? (
          <div className="page-empty">
            <h2>A watchline needs a reader.</h2>
            <p>
              Sign in to pin countries and storylines, keep a return brief, and share a read-only desk link.
              Your pins stay tied to your account, not this browser.
            </p>
            <button
              type="button"
              className="page-primary"
              onClick={() => navigate(`/login?next=${encodeURIComponent('/watchline')}`)}
            >
              Sign in to open a desk
            </button>
          </div>
        ) : feed && feed.available === false ? (
          <div className="page-empty" role="status">
            <h2>The desk is temporarily unavailable.</h2>
            <p>
              The snapshot is still being assembled. Your pins are kept; retry in a
              moment.
            </p>
            <button
              type="button"
              className="page-secondary"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              Try again
            </button>
          </div>
        ) : feed && feed.feed.length === 0 ? (
          <div className="page-empty">
            <h2>No dispatches on this desk yet.</h2>
            <p>
              {entries.length === 0
                ? 'Pin a country or follow a storyline. The next snapshot will fill the desk.'
                : 'Nothing in the current window touches these desks. Widen the window or pin another place.'}
            </p>
            {signedIn && entries.length === 0 && startSuggestions.length > 0 && (
              <>
                <span className="watchline-suggest__label">Start with a storyline</span>
                <div className="watchline-suggest">
                  {startSuggestions.map((arc) => (
                    <button
                      key={arc.id}
                      type="button"
                      className="watchline-suggest__item"
                      onClick={() => handleFollowArc(arc)}
                      disabled={adding}
                    >
                      <Sparkles size={13} aria-hidden="true" />
                      <span>
                        {arc.countries.slice(0, 3).join(' / ') || `${arc.a} – ${arc.b}`}
                        <small>{arc.type} · {arc.window_events} dispatches</small>
                      </span>
                      <Plus size={13} aria-hidden="true" />
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            <ol className="watchline-feed">
              {feed?.feed.map((event, index) => {
                const color = getCategoryColor(event.cat);
                return (
                  <li key={event.id}>
                    <button type="button" className="watchline-story" onClick={() => navigate(`/event/${event.id}`)}>
                      <span className="watchline-story__rank">{String(index + 1).padStart(2, '0')}</span>
                      <span className="watchline-story__rule" style={{ backgroundColor: color }} aria-hidden="true" />
                      <span className="watchline-story__body">
                        <span className="watchline-story__meta">
                          {event.fresh && <span className="watchline-story__fresh">New</span>}
                          <span>{event.cat}</span>
                          {event.loc && <span>{event.loc}</span>}
                          {event.at && <span>{formatRelativeTime(event.at)}</span>}
                          <span>{event.oc} {event.oc === 1 ? 'outlet' : 'outlets'}</span>
                        </span>
                        <span className="watchline-story__title">{event.t}</span>
                        <span className="watchline-story__desks">
                          {event.matched.map((match) => (
                            <span key={`${match.kind}-${match.key}`}>{match.label}</span>
                          ))}
                        </span>
                      </span>
                      <ArrowUpRight size={15} className="watchline-story__arrow" aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ol>
            {signedIn && feed && feed.matched_total > feed.shown && (
              <p className="page-note">
                Showing the {feed.shown} most consequential dispatches of {feed.matched_total}. Widen the window to see more.
              </p>
            )}
          </>
        )}
      </section>

      {signedIn && entries.length > 0 && (
        <p className="page-note watchline-footnote">
          <Copy size={11} aria-hidden="true" /> The desk link shares only the pinned keys and the public dispatches attached to them.
        </p>
      )}
    </PageShell>
  );
};
