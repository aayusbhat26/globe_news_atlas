import React, { useState, useEffect, useRef } from 'react';
import type { SnapshotEvent } from '../../types/snapshot';
import type { SearchApiResult } from '../../types/event';
import { getCategoryColor } from '../../utils/colors';
import { isAbortError, fetchSearchResults } from '../../services/api';
import { Search, X, MapPin } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import './SearchModal.css';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  events: SnapshotEvent[];
  onSelectEvent: (event: SnapshotEvent) => void;
}

const errorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) return error.message;
  return 'Search is unavailable right now.';
};

const SEARCH_PAGE_SIZE = 20;
const SEARCH_MAX_LIMIT = 100;

const toSnapshotEvent = (result: SearchApiResult): SnapshotEvent => ({
  id: result.id,
  lat: result.lat,
  lng: result.lng,
  cat: result.category,
  imp: result.importance,
  t: result.title,
  at: result.updated_at,
  oc: result.outlet_count,
  sp: {},
  st: result.status,
  sb: 0,
  ss: false,
  cg: false,
  cw: false,
  sum: result.summary,
  loc: result.location_name,
  gp: '',
  src: '',
});

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  events,
  onSelectEvent,
}) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [serverResults, setServerResults] = useState<SnapshotEvent[]>([]);
  const [serverTotal, setServerTotal] = useState<number | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [limit, setLimit] = useState(SEARCH_PAGE_SIZE);
  const [retryToken, setRetryToken] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef(onClose);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setQuery('');
    setServerResults([]);
    setServerTotal(null);
    setSearching(false);
    setSearchError(null);
    setLimit(SEARCH_PAGE_SIZE);
    setRetryToken(0);
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 30);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKeyDown, true);
      previousFocusRef.current?.focus();
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const cleaned = query.trim();
    if (cleaned.length < 2) {
      setServerResults([]);
      setServerTotal(null);
      setSearchError(null);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setSearching(true);
    setSearchError(null);
    const timer = window.setTimeout(() => {
      fetchSearchResults(cleaned, '30d', limit, controller.signal)
        .then((response) => {
          if (!active) return;
          setServerResults(response.items.map(toSnapshotEvent));
          setServerTotal(response.total);
        })
        .catch((error: unknown) => {
          if (!active || isAbortError(error)) return;
          setServerResults([]);
          setServerTotal(null);
          setSearchError(errorMessage(error));
        })
        .finally(() => {
          if (active) setSearching(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, isOpen, limit, retryToken]);

  if (!isOpen) return null;

  const qLower = query.trim().toLowerCase();
  const activeSearch = qLower.length >= 2;
  const matches = (value?: string | null) =>
    Boolean(value && value.toLowerCase().includes(qLower));

  const localResults = qLower
    ? events.filter((event) => {
        return (
          matches(event.t) ||
          matches(event.cat) ||
          matches(event.sum) ||
          matches(event.loc) ||
          matches(event.src) ||
          matches(event.gp)
        );
      })
    : events.slice(0, 10);
  const filtered = activeSearch ? serverResults : localResults;
  const visibleResults = filtered;

  const canLoadMore =
    activeSearch &&
    !searching &&
    !searchError &&
    limit < SEARCH_MAX_LIMIT &&
    (serverTotal == null
      ? serverResults.length >= limit
      : serverResults.length < serverTotal);

  const limitReached =
    activeSearch && !searchError && (serverTotal == null || serverResults.length < serverTotal)
      ? limit >= SEARCH_MAX_LIMIT
      : false;

  let resultHeading: string;
  if (!qLower) {
    resultHeading = t('recent_events');
  } else if (!activeSearch) {
    resultHeading = t('search_results_count', { count: localResults.length });
  } else if (searching && serverResults.length === 0) {
    resultHeading = t('searching');
  } else if (searchError) {
    resultHeading = t('search_failed_short');
  } else if (serverTotal != null) {
    resultHeading = t('search_showing_of_total', {
      shown: serverResults.length,
      total: serverTotal,
    });
  } else {
    resultHeading = t('search_showing_limited', {
      shown: serverResults.length,
      limit,
    });
  }

  const focusResult = (index: number) => {
    const items = panelRef.current?.querySelectorAll<HTMLButtonElement>('.search-result-item');
    if (!items || items.length === 0) return;
    const bounded = Math.max(0, Math.min(index, items.length - 1));
    items[bounded]?.focus();
  };

  const handleResultsKeyDown = (event: React.KeyboardEvent<HTMLUListElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const items = Array.from(
      panelRef.current?.querySelectorAll<HTMLButtonElement>('.search-result-item') ?? [],
    );
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusResult(current < 0 ? 0 : current + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (current <= 0) inputRef.current?.focus();
      else focusResult(current - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusResult(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusResult(items.length - 1);
    }
  };

  return (
    <div
      className="search-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panelRef}
        className="search-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="search-dialog-title"
      >
        <h2 id="search-dialog-title" className="sr-only">{t('search_events')}</h2>
        <div className="search-input-wrapper">
          <Search size={18} className="search-modal-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            className="search-input"
            placeholder={t('search_placeholder')}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setLimit(SEARCH_PAGE_SIZE);
              setServerResults([]);
              setServerTotal(null);
              setSearchError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                focusResult(0);
              }
            }}
            aria-label={t('search_events')}
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            className="search-close-btn"
            onClick={onClose}
            aria-label={t('close')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="search-results-head" aria-live="polite">
          <span>{resultHeading}</span>
          <span>
            {!activeSearch && qLower
              ? t('search_snapshot_only')
              : limitReached
                ? t('search_cap_note', { count: SEARCH_MAX_LIMIT })
                : t('search_hint')}
          </span>
        </div>

        <ul
          className="search-results-list"
          aria-busy={searching}
          onKeyDown={handleResultsKeyDown}
        >
          {visibleResults.map((item) => {
            const catColor = getCategoryColor(item.cat);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="search-result-item"
                  onClick={() => {
                    onSelectEvent(item);
                    onClose();
                  }}
                >
                  <span className="search-result-header">
                    <span
                      className="category-badge"
                      style={{ color: catColor, borderColor: catColor }}
                    >
                      {t(`category.${item.cat}`, item.cat)}
                    </span>
                    <span className="search-result-location">
                      <MapPin size={10} aria-hidden="true" />
                      {item.loc ||
                        (Number.isFinite(item.lat) && Number.isFinite(item.lng)
                          ? `${item.lat.toFixed(1)}°, ${item.lng.toFixed(1)}°`
                          : t('location_unavailable'))}
                    </span>
                  </span>
                  <span className="search-result-title">{item.t}</span>
                  {item.sum && <span className="search-result-summary">{item.sum}</span>}
                </button>
              </li>
            );
          })}
          {activeSearch && searchError && (
            <li className="search-empty search-error" role="alert">
              <span>{searchError}</span>
              <button
                type="button"
                className="search-error__retry"
                onClick={() => setRetryToken((token) => token + 1)}
              >
                {t('retry')}
              </button>
            </li>
          )}
          {!searching && !searchError && filtered.length === 0 && (
            <li className="search-empty">
              {t('no_search_results', { query })}
            </li>
          )}
        </ul>

        {canLoadMore && (
          <div className="search-more">
            <button
              type="button"
              className="search-more__btn"
              onClick={() =>
                setLimit((current) => Math.min(SEARCH_MAX_LIMIT, current + SEARCH_PAGE_SIZE))
              }
              disabled={searching}
            >
              {searching ? t('searching') : t('search_load_more')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
