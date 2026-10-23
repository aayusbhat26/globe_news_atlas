import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Check, FileSearch, Plus, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { CountryBriefResponse, CountryFocus } from '../../types/country';
import { ApiError, fetchCountryBrief } from '../../services/api';
import {
  addWatchlineEntry,
  fetchWatchlineEntries,
  removeWatchlineEntry,
} from '../../services/atlas';
import type { WatchlineEntry } from '../../types/atlas';
import { useAuth } from '../../auth/AuthContext';
import { navigate } from '../../router';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import './CountryBrief.css';

type TimeWindow = '1h' | '24h' | '7d' | '30d';
type BriefTab = 'all' | 'brief' | 'protest' | 'conflict' | 'technology';

const TABS: BriefTab[] = ['all', 'brief', 'protest', 'conflict', 'technology'];
const WINDOW_LADDER: TimeWindow[] = ['1h', '24h', '7d', '30d'];

interface CountryBriefProps {
  country: CountryFocus;
  timeWindow: TimeWindow;
  dataVersion?: string | null;
  onChangeWindow: (window: TimeWindow) => void;
  onSelectEvent: (eventId: string) => void;
  onClose: () => void;
}

const nextWindow = (window: TimeWindow): TimeWindow | null => {
  const index = WINDOW_LADDER.indexOf(window);
  return index >= 0 && index < WINDOW_LADDER.length - 1 ? WINDOW_LADDER[index + 1] : null;
};

const summaryDiffersFromTitle = (title: string, summary: string): boolean => {
  const normal = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  return Boolean(summary) && !normal(summary).startsWith(normal(title).slice(0, 48));
};

export const CountryBrief: React.FC<CountryBriefProps> = ({
  country,
  timeWindow,
  dataVersion,
  onChangeWindow,
  onSelectEvent,
  onClose,
}) => {
  const { t } = useTranslation();
  const auth = useAuth();
  const panelRef = useRef<HTMLElement>(null);
  const [data, setData] = useState<CountryBriefResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState<number>(0);
  const [activeTab, setActiveTab] = useState<BriefTab>('all');
  const [followEntry, setFollowEntry] = useState<WatchlineEntry | null>(null);
  const [followBusy, setFollowBusy] = useState<boolean>(false);
  const [followError, setFollowError] = useState<string | null>(null);
  useFocusTrap(true, panelRef, onClose);

  useEffect(() => {
    setActiveTab('all');
  }, [country.name]);

  useEffect(() => {
    if (!auth.user) {
      setFollowEntry(null);
      return;
    }
    let active = true;
    fetchWatchlineEntries()
      .then(({ entries }) => {
        if (!active) return;
        setFollowEntry(
          entries.find(
            (entry) => entry.kind === 'place' && entry.key === country.name.toLowerCase(),
          ) || null,
        );
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [auth.user, country.name, data?.country]);

  const toggleFollow = async () => {
    if (!auth.user) {
      navigate(`/login?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`);
      return;
    }
    setFollowBusy(true);
    setFollowError(null);
    try {
      if (followEntry) {
        const result = await removeWatchlineEntry(followEntry.id);
        setFollowEntry(
          result.entries.find(
            (entry) => entry.kind === 'place' && entry.key === country.name.toLowerCase(),
          ) || null,
        );
      } else {
        const result = await addWatchlineEntry('place', country.name, data?.country || country.name);
        setFollowEntry(result.entry);
      }
    } catch (err) {
      setFollowError(err instanceof ApiError ? err.message : 'Could not update your watchline.');
    } finally {
      setFollowBusy(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchCountryBrief(country.name, country.iso2, timeWindow, controller.signal)
      .then((brief) => {
        setData(brief);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load country desk');
        setLoading(false);
      });
    return () => controller.abort();
  }, [country.name, country.iso2, timeWindow, dataVersion, reloadToken]);

  const displayName = data?.country || country.name;
  const section = data?.sections.find((item) => item.key === activeTab);
  const tabCount = (tab: BriefTab): number => {
    if (!data) return 0;
    if (tab === 'all') return data.total_events;
    if (tab === 'brief') return data.brief_events;
    return data.counts[tab] || 0;
  };
  const widenTarget = nextWindow(timeWindow);
  const isRefreshing = loading && Boolean(data);
  const countValue = (value: number | undefined) => (typeof value === 'number' ? value : '—');

  const selectTab = (tab: BriefTab, focus = true) => {
    setActiveTab(tab);
    if (focus) {
      document.getElementById(`country-tab-${tab}`)?.focus();
    }
  };

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, tab: BriefTab) => {
    const index = TABS.indexOf(tab);
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % TABS.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = TABS.length - 1;
    else return;
    event.preventDefault();
    selectTab(TABS[nextIndex]);
  };

  const tabLabel = (tab: BriefTab): string =>
    tab === 'all'
      ? t('country_brief_latest')
      : tab === 'brief'
        ? t('country_brief_all')
        : t(`category.${tab}`, tab);

  return (
    <section
      ref={panelRef}
      className="country-desk"
      role="dialog"
      aria-labelledby="country-desk-title"
    >
      <div className="country-desk__rail">
        <span className="country-desk__rail-brand">Globe News Atlas</span>
        <span className="country-desk__rail-divider">/</span>
        <span className="country-desk__rail-label">{t('country_desk')}</span>
        <button
          type="button"
          data-autofocus
          className="country-desk__close"
          onClick={onClose}
          aria-label={t('close')}
        >
          <X size={17} />
        </button>
      </div>

      <div className="country-desk__header">
        <div className="country-desk__masthead">
          <div className="country-desk__name-block">
            <span className="country-desk__eyebrow">{t('country_desk_kicker')}</span>
            <h2 id="country-desk-title" className="country-desk__title">
              {displayName}
              {country.iso2 && /^[A-Z]{2}$/.test(country.iso2) && (
                <span className="country-desk__code" aria-hidden="true">{country.iso2}</span>
              )}
            </h2>
          </div>
          <div className="country-desk__header-actions">
            <span className="country-desk__window">{timeWindow.toUpperCase()}</span>
            <button
              type="button"
              className={`country-desk__follow${followEntry ? ' is-followed' : ''}`}
              onClick={toggleFollow}
              disabled={followBusy || auth.loading}
              title={followEntry ? 'Remove this desk from your watchline' : 'Pin this country to your watchline'}
            >
              {followEntry ? <Check size={12} /> : <Plus size={12} />}
              {followEntry ? 'Followed' : 'Follow desk'}
            </button>
          </div>
        </div>

        {followError && (
          <p className="country-desk__follow-error" role="alert">
            {followError}
          </p>
        )}

        <p className="country-desk__lead">
          {data
            ? t('country_desk_lead', {
                count: data.total_events,
                total: data.total_events,
                focus: data.brief_events,
                window: timeWindow.toUpperCase(),
              })
            : t('country_brief_scope')}
        </p>

        <dl className="country-desk__ledger">
          <div className="country-desk__ledger-item country-desk__ledger-item--primary">
            <dt>{t('country_brief_in_focus')}</dt>
            <dd>{countValue(data?.brief_events)}</dd>
          </div>
          <div className="country-desk__ledger-item">
            <dt>{t('dispatches')}</dt>
            <dd>{countValue(data?.total_events)}</dd>
          </div>
          <div className="country-desk__ledger-item">
            <dt>{t('outlets')}</dt>
            <dd>{countValue(data?.total_outlets)}</dd>
          </div>
          <div className="country-desk__ledger-item">
            <dt>{t('country_brief_reports')}</dt>
            <dd>{countValue(data?.total_reports)}</dd>
          </div>
        </dl>
      </div>

      <div className="country-desk__tabs" role="tablist" aria-label={t('country_desk')}>
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`country-tab-${tab}`}
            className={`country-desk__tab${activeTab === tab ? ' country-desk__tab--active' : ''}`}
            aria-selected={activeTab === tab}
            aria-controls={`country-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => selectTab(tab, false)}
            onKeyDown={(event) => handleTabKeyDown(event, tab)}
          >
            <span>{tabLabel(tab)}</span>
            <span className="country-desk__tab-count">{data ? tabCount(tab) : '—'}</span>
          </button>
        ))}
      </div>

      <div
        className={`country-desk__scroll${isRefreshing ? ' is-refreshing' : ''}`}
        role="tabpanel"
        id={`country-panel-${activeTab}`}
        aria-labelledby={`country-tab-${activeTab}`}
        aria-busy={loading}
      >
        {loading && !data ? (
          <div className="country-desk__loading" role="status" aria-live="polite">
            <span>{t('country_brief_loading')}</span>
            {[0, 1, 2, 3, 4].map((row) => (
              <span key={row} className="country-desk__skeleton">
                <span className="country-desk__skeleton-rank" />
                <span className="country-desk__skeleton-lines">
                  <span />
                  <span />
                </span>
              </span>
            ))}
          </div>
        ) : error ? (
          <div className="country-desk__message" role="alert">
            <p>{t('country_brief_error')}</p>
            <p className="country-desk__message-detail">{error}</p>
            <button
              type="button"
              className="country-desk__action"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              {t('country_brief_retry')}
            </button>
          </div>
        ) : section && section.events.length > 0 ? (
          <>
            <div className="country-desk__list-head">
              <span>{t('country_brief_showing', { shown: section.events.length, count: section.count })}</span>
              <span>{t('country_brief_ranked')}</span>
            </div>
            <ol className="country-desk__list">
              {section.events.map((event, index) => {
                const color = getCategoryColor(event.category);
                const showSummary = summaryDiffersFromTitle(event.title, event.summary);
                return (
                  <li key={event.id}>
                    <button
                      type="button"
                      className="country-dispatch"
                      onClick={() => onSelectEvent(event.id)}
                    >
                      <span className="country-dispatch__rank">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <span
                        className="country-dispatch__rule"
                        style={{ backgroundColor: color }}
                        aria-hidden="true"
                      />
                      <span className="country-dispatch__body">
                        <span className="country-dispatch__meta">
                          <span className="country-dispatch__category">
                            <span
                              className="country-dispatch__category-dot"
                              style={{ backgroundColor: color }}
                              aria-hidden="true"
                            />
                            {t(`category.${event.category}`, event.category)}
                          </span>
                          {event.severity && (
                            <span>{t(`severity_${event.severity}`, event.severity)}</span>
                          )}
                          {event.updated_at && <span>{formatRelativeTime(event.updated_at)}</span>}
                          {event.is_single_source && (
                            <span className="country-dispatch__flag" title={t('single_source_caveat')}>
                              {t('single_source')}
                            </span>
                          )}
                        </span>
                        <span className="country-dispatch__title">{event.title}</span>
                        {showSummary && (
                          <span className="country-dispatch__summary">{event.summary}</span>
                        )}
                        <span className="country-dispatch__foot">
                          {event.source && <span>{event.source}</span>}
                          {event.location && (
                            <>
                              <span className="country-dispatch__dot" aria-hidden="true">·</span>
                              <span>{event.location}</span>
                            </>
                          )}
                          <span className="country-dispatch__dot" aria-hidden="true">·</span>
                          <span>{t('outlets_count', { count: event.outlet_count || 1 })}</span>
                        </span>
                      </span>
                      <ArrowUpRight className="country-dispatch__arrow" size={14} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <div className="country-desk__message">
            <FileSearch size={22} aria-hidden="true" />
            <p>
              {activeTab === 'all'
                ? t('country_brief_empty_all', { country: displayName })
                : t('country_brief_empty', { country: displayName })}
            </p>
            <p className="country-desk__message-detail">
              {activeTab !== 'all' && data && data.total_events > 0
                ? t('country_brief_focus_empty_hint')
                : t('country_brief_empty_hint')}
            </p>
            {activeTab !== 'all' && data && data.total_events > 0 && (
              <button
                type="button"
                className="country-desk__action"
                onClick={() => setActiveTab('all')}
              >
                {t('country_brief_view_all')}
              </button>
            )}
            {widenTarget && (
              <button
                type="button"
                className="country-desk__action"
                onClick={() => onChangeWindow(widenTarget)}
              >
                {t('country_brief_widen', { window: widenTarget.toUpperCase() })}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="country-desk__footer">
        <span>
          {data?.generated_at
            ? t('country_brief_updated', { time: formatRelativeTime(data.generated_at) })
            : t('country_brief_scope')}
        </span>
        <span>{t('country_brief_top10')}</span>
      </div>
    </section>
  );
};
