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
import { useTheme, useWebGLSupport } from '../../hooks/useTheme';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import type { PulseResponse, RewindResponse } from '../../types/atlas';
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
  const { isDark } = useTheme();
  const hasWebGL = useWebGLSupport();

  useEffect(() => {
    Promise.all([fetchRewind(), fetchPulse('24h')])
      .then(([rewind, pulseData]) => {
        setData(rewind);
        setPulse(pulseData);
        setIndex(Math.max(0, rewind.frames.length - 1));
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Could not load the replay archive.');
      })
      .finally(() => setLoading(false));
  }, []);

  const frames = data?.frames || [];

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
                    onEventClick={(id) => navigate(`/event/${id}`)}
                    onLocationClick={() => undefined}
                    onCountryClick={() => undefined}
                    activeCountry={null}
                    targetCoords={null}
                    isDark={isDark}
                    legendInitiallyOpen={false}
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
            </section>

            <aside className="rewind-pulse" aria-labelledby="rewind-pulse-title">
              <div className="rewind-pulse__head">
                <h2 id="rewind-pulse-title">Heating up</h2>
                <span>{pulse?.basis.frames || 0} frames compared</span>
              </div>
              {!pulse?.items.length ? (
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
