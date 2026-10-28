import React, { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight,
  History,
  Pause,
  Play,
  SkipBack,
  SkipForward,
} from 'lucide-react';
import { PageShell } from './PageShell';
import { fetchPulse, fetchRewind } from '../../services/atlas';
import { isAbortError } from '../../services/api';
import { useTheme, useWebGLSupport } from '../../hooks/useTheme';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import { LocationDispatch } from '../Cards/LocationDispatch';
import type { PulseResponse, RewindResponse } from '../../types/atlas';
import type { SnapshotEvent } from '../../types/snapshot';
import './Rewind.css';

const GlobeView = lazy(() =>
  import('../Globe/GlobeView').then((module) => ({ default: module.GlobeView })),
);

const formatStamp = (value: string | null): string => {
  if (!value) return 'Unknown time';
  return new Date(value).toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const RewindPage: React.FC = () => {
  const [data, setData] = useState<RewindResponse | null>(null);
  const [pulse, setPulse] = useState<PulseResponse | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [pulseLoading, setPulseLoading] = useState(true);
  const [pulseError, setPulseError] = useState<string | null>(null);
  const [pulseToken, setPulseToken] = useState(0);
  const [locationGroup, setLocationGroup] = useState<SnapshotEvent[] | null>(null);
  const [webglLost, setWebglLost] = useState(false);
  const { isDark } = useTheme();
  const hasWebGL = useWebGLSupport() && !webglLost;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    fetchRewind(controller.signal)
      .then((rewind) => {
        if (!active) return;
        setData(rewind);
        setIndex(Math.max(0, rewind.frames.length - 1));
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(err instanceof Error ? err.message : 'Could not load the replay archive.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadToken]);

  // Pulse is a separate request: a momentum failure must not hide the archive.
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setPulseLoading(true);
    setPulseError(null);
    fetchPulse('24h', controller.signal)
      .then((result) => {
        if (active) setPulse(result);
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setPulseError(err instanceof Error ? err.message : 'Momentum could not be read.');
      })
      .finally(() => {
        if (active) setPulseLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [pulseToken]);

  const frames = data?.frames || [];

  useEffect(() => {
    setLocationGroup(null);
  }, [index]);

  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const timer = globalThis.setInterval(() => {
      setIndex((current) => Math.min(current + 1, frames.length - 1));
    }, 950);
    return () => globalThis.clearInterval(timer);
  }, [playing, frames.length]);

  useEffect(() => {
    if (playing && frames.length > 0 && index >= frames.length - 1) {
      setPlaying(false);
    }
  }, [playing, index, frames.length]);

  useEffect(() => {
    if (frames.length && index > frames.length - 1) setIndex(frames.length - 1);
  }, [frames.length, index]);

  const frame = frames[index];
  const events = useMemo(() => frame?.events || [], [frame]);
  const firstStamp = data?.from;
  const lastStamp = data?.to;

  return (
    <PageShell
      kicker="Archive desk"
      title="Atlas Rewind"
      standfirst="Play back the last days of the atlas. Each frame is a real 24-hour snapshot produced by the pipeline — events appear, gather outlets, and fall out of the window."
      meta={
        <>
          {data && <span>{data.count} archived snapshots</span>}
          {firstStamp && lastStamp && (
            <span>
              {new Date(firstStamp).toLocaleDateString()} → {new Date(lastStamp).toLocaleDateString()}
            </span>
          )}
          <span>24h window per frame</span>
        </>
      }
    >
      {loading && !data ? (
        <div className="page-loading" role="status">Reading the archive…</div>
      ) : error ? (
        <div className="page-error" role="alert">
          <h2>The archive could not be read.</h2>
          <p>{error}</p>
          <button
            type="button"
            className="page-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            Try again
          </button>
        </div>
      ) : !data?.available || frames.length === 0 ? (
        <div className="page-empty">
          <History size={22} aria-hidden="true" />
          <h2>The archive is still being bound.</h2>
          <p>
            Rewind is built from the snapshot history kept in the Parquet lake. The next pipeline run
            will add its frames here.
          </p>
        </div>
      ) : (
        <>
          <div className="rewind-stage">
            <section className="rewind-globe" aria-label="Replay globe">
              {hasWebGL ? (
                <Suspense
                  fallback={<div className="rewind-globe__loading" role="status">Preparing the globe…</div>}
                >
                  <GlobeView
                    events={events}
                    arcs={frame?.arcs || []}
                    onEventHover={() => undefined}
                    onEventClick={(id) => {
                      setLocationGroup(null);
                      navigate(`/event/${id}`);
                    }}
                    onLocationClick={(group) => setLocationGroup(group)}
                    activeCountry={null}
                    targetCoords={null}
                    isDark={isDark}
                    legendInitiallyOpen={false}
                    onWebGLError={() => setWebglLost(true)}
                  />
                </Suspense>
              ) : (
                <div className="rewind-fallback">
                  <span>{frame ? formatStamp(frame.ts) : ''}</span>
                  <ol>
                    {events.slice(0, 12).map((event) => (
                      <li key={event.id}>
                        <button type="button" onClick={() => navigate(`/event/${event.id}`)}>
                          {event.t}
                        </button>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              <div className="rewind-stamp">
                <span>{frame ? formatStamp(frame.ts) : ''}</span>
                <span>
                  {frame?.counts?.e ?? events.length} events · {frame?.counts?.a ?? frame?.arcs.length ?? 0} arcs
                </span>
              </div>

              {locationGroup && (
                <LocationDispatch
                  events={locationGroup}
                  onSelect={(id) => {
                    setLocationGroup(null);
                    navigate(`/event/${id}`);
                  }}
                  onClose={() => setLocationGroup(null)}
                />
              )}
            </section>

            <aside className="rewind-pulse" aria-labelledby="rewind-pulse-title">
              <div className="rewind-pulse__head">
                <h2 id="rewind-pulse-title">Heating up</h2>
                <span>
                  {pulseLoading
                    ? 'Reading momentum…'
                    : `${pulse?.basis.frames || 0} frames compared`}
                </span>
              </div>
              {pulseError ? (
                <div className="rewind-pulse__error" role="alert">
                  <p>{pulseError}</p>
                  <button
                    type="button"
                    className="page-secondary"
                    onClick={() => setPulseToken((token) => token + 1)}
                  >
                    Retry momentum
                  </button>
                </div>
              ) : pulseLoading && !pulse ? (
                <p className="rewind-pulse__empty">Reading the momentum desk…</p>
              ) : !pulse?.items.length ? (
                <p className="rewind-pulse__empty">
                  Momentum appears once two archived snapshots contain the same event.
                </p>
              ) : (
                <ol>
                  {pulse.items.slice(0, 8).map((item) => (
                    <li key={item.id}>
                      <button type="button" onClick={() => navigate(`/event/${item.id}`)}>
                        <span className="rewind-pulse__reason">
                          {item.is_new
                            ? 'New since last frame'
                            : `+${item.outlet_delta} ${item.outlet_delta === 1 ? 'outlet' : 'outlets'}`}
                        </span>
                        <span className="rewind-pulse__title">{item.title}</span>
                        <span className="rewind-pulse__meta">
                          {item.outlet_count} outlets now
                          {item.previous_outlets != null ? ` · was ${item.previous_outlets}` : ''}
                          {item.updated_at ? ` · ${formatRelativeTime(item.updated_at)}` : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
              <p className="rewind-pulse__note">
                Momentum compares outlet counts between archived snapshots. It measures coverage
                attention, not the severity of an event.
              </p>
            </aside>
          </div>

          <div className="rewind-controls">
            <div className="rewind-controls__buttons">
              <button
                type="button"
                className="page-icon-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex((current) => Math.max(0, current - 1));
                }}
                aria-label="Previous frame"
                disabled={index <= 0}
              >
                <SkipBack size={15} />
              </button>
              <button
                type="button"
                className="rewind-play"
                onClick={() => {
                  if (index >= frames.length - 1) setIndex(0);
                  setPlaying((current) => !current);
                }}
                aria-label={playing ? 'Pause replay' : 'Play replay'}
              >
                {playing ? <Pause size={16} /> : <Play size={16} />}
                {playing ? 'Pause' : index >= frames.length - 1 ? 'Replay from the start' : 'Play'}
              </button>
              <button
                type="button"
                className="page-icon-btn"
                onClick={() => {
                  setPlaying(false);
                  setIndex((current) => Math.min(frames.length - 1, current + 1));
                }}
                aria-label="Next frame"
                disabled={index >= frames.length - 1}
              >
                <SkipForward size={15} />
              </button>
              <button
                type="button"
                className="page-quiet"
                onClick={() => {
                  setPlaying(false);
                  setIndex(frames.length - 1);
                }}
                disabled={index >= frames.length - 1}
              >
                Jump to latest
              </button>
            </div>

            <div className="rewind-scrub">
              <input
                type="range"
                min={0}
                max={Math.max(0, frames.length - 1)}
                value={index}
                onChange={(event) => {
                  setPlaying(false);
                  setIndex(Number(event.target.value));
                }}
                aria-label="Replay frame"
                aria-valuetext={frame ? formatStamp(frame.ts) : undefined}
              />
              <div className="rewind-scrub__labels">
                <span>{firstStamp ? formatStamp(firstStamp) : ''}</span>
                <span>{lastStamp ? formatStamp(lastStamp) : ''}</span>
              </div>
            </div>

            <button
              type="button"
              className="page-secondary"
              onClick={() => frame?.events[0] && navigate(`/event/${frame.events[0].id}`)}
            >
              Open top dispatch <ArrowUpRight size={12} />
            </button>
          </div>

          <p className="page-note">
            {data.count} frames kept from the available snapshot history
            {data.available_runs ? ` (${data.available_runs} runs recorded)` : ''}. The replay retains
            up to {data.history_days || 30} days and samples evenly when the archive is dense, so gaps
            between frames vary.
          </p>
        </>
      )}
    </PageShell>
  );
};
