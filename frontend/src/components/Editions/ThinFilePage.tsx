import React, { useEffect, useState } from 'react';
import { ArrowUpRight, FileSearch } from 'lucide-react';
import { PageShell } from './PageShell';
import { fetchThinFile } from '../../services/atlas';
import { isAbortError } from '../../services/api';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import type { ThinFile } from '../../types/atlas';
import './ThinFile.css';

const WINDOWS = ['1h', '24h', '7d', '30d'] as const;
type TimeWindow = (typeof WINDOWS)[number];

const REASON_LABEL: Record<string, string> = {
  single_outlet: 'Single outlet',
  coverage_gap: 'One-sided coverage',
  revised: 'Summary revised',
};

export const ThinFilePage: React.FC = () => {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('24h');
  const [data, setData] = useState<ThinFile | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(!data);
    setRefreshing(Boolean(data));
    setError(null);
    fetchThinFile(timeWindow, controller.signal)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(err instanceof Error ? err.message : 'Could not read the Thin File.');
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
    // `data` only decides between an initial load and a refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeWindow, reloadToken]);

  const unavailable = Boolean(
    data &&
      (data.available === false ||
        (!data.generated_at && data.total_events === 0 && data.items.length === 0)),
  );

  return (
    <PageShell
      kicker="Corroboration desk"
      title="The Thin File"
      standfirst="Stories the Atlas is carrying on the thinnest evidence: a single outlet, a rewritten summary, or reporting from only one side of the rated press. Thin does not mean false — it means under-corroborated."
      meta={
        <>
          <span>{timeWindow.toUpperCase()} window</span>
          {data && <span>{data.total_events} dispatches in the window</span>}
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
      {data && (
        <dl className="page-count-strip">
          <div>
            <dt>Thin dispatches</dt>
            <dd>{data.thin_total}</dd>
          </div>
          <div>
            <dt>Single outlet</dt>
            <dd>{data.counts.single_outlet || 0}</dd>
          </div>
          <div>
            <dt>Revised summary</dt>
            <dd>{data.counts.revised || 0}</dd>
          </div>
          <div>
            <dt>One-sided coverage</dt>
            <dd>{data.counts.coverage_gap || 0}</dd>
          </div>
        </dl>
      )}

      <div className="thin-definition">
        <span>Reading the file</span>
        <p>
          A dispatch enters the file when it has one distinct outlet, rated coverage that sits entirely
          on one side, or a summary that has been rewritten while carrying at most three outlets. Entries
          are ranked by importance, not by how suspicious they are. Open a dossier to see its sources and
          timeline.
        </p>
      </div>

      {loading && !data ? (
        <div className="page-loading" role="status">Collecting the thin file…</div>
      ) : error ? (
        <div className="page-error" role="alert">
          <h2>The file could not be read.</h2>
          <p>{error}</p>
          <button
            type="button"
            className="page-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            Try again
          </button>
        </div>
      ) : unavailable ? (
        <div className="page-empty" role="status">
          <FileSearch size={22} aria-hidden="true" />
          <h2>The Thin File is temporarily unavailable.</h2>
          <p>The snapshot exists, but its thin-dispatch extract is not ready yet.</p>
          <button
            type="button"
            className="page-secondary"
            onClick={() => setReloadToken((token) => token + 1)}
          >
            Try again
          </button>
        </div>
      ) : data && data.items.length === 0 ? (
        <div className="page-empty">
          <FileSearch size={22} aria-hidden="true" />
          <h2>Nothing thin in this window.</h2>
          <p>Every dispatch here has multiple outlets and an unchanged summary. Widen the window or check back later.</p>
        </div>
      ) : (
        <>
          <ol className="thin-list">
            {data?.items.map((item, index) => {
              const color = getCategoryColor(item.category);
              return (
                <li key={item.id}>
                  <button type="button" className="thin-row" onClick={() => navigate(`/event/${item.id}`)}>
                    <span className="thin-row__rank">{String(index + 1).padStart(2, '0')}</span>
                    <span className="thin-row__rule" style={{ backgroundColor: color }} aria-hidden="true" />
                    <span className="thin-row__body">
                      <span className="thin-row__meta">
                        <span>{item.category}</span>
                        {item.location_name && <span>{item.location_name}</span>}
                        {item.updated_at && <span>{formatRelativeTime(item.updated_at)}</span>}
                        <span>{item.outlet_count} {item.outlet_count === 1 ? 'outlet' : 'outlets'}</span>
                        {item.revision > 1 && <span>revision {item.revision}</span>}
                      </span>
                      <span className="thin-row__title">{item.title}</span>
                      <span className="thin-row__reasons">
                        {item.reasons.map((reason) => (
                          <span key={reason} className={`thin-reason thin-reason--${reason}`}>
                            {REASON_LABEL[reason] || reason}
                          </span>
                        ))}
                        {item.has_official_source && (
                          <span className="thin-reason thin-reason--official">Official source attached</span>
                        )}
                      </span>
                    </span>
                    <ArrowUpRight size={15} className="thin-row__arrow" aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ol>
          {data && (
            <p className="page-note">
              Showing {data.shown} of {data.thin_total} thin dispatches, ranked by importance.{' '}
              {data.thin_total} of {data.total_events} dispatches in this window meet the criteria.
            </p>
          )}
        </>
      )}
    </PageShell>
  );
};
