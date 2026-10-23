import React, { useState, useEffect, useRef } from 'react';
import type { SnapshotEvent } from '../../types/snapshot';
import type { SearchApiResult } from '../../types/event';
import { getCategoryColor } from '../../utils/colors';
import { fetchSearchResults } from '../../services/api';
import { Search, X, MapPin } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import './SearchModal.css';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  events: SnapshotEvent[];
  onSelectEvent: (event: SnapshotEvent) => void;
}

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
  const [serverResults, setServerResults] = useState<SnapshotEvent[] | null>(null);
  const [searching, setSearching] = useState(false);
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
    setServerResults(null);
    setSearching(false);
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
      setServerResults(null);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      fetchSearchResults(cleaned, '30d', 20, controller.signal)
        .then((rows) => {
          if (active) setServerResults(rows.map(toSnapshotEvent));
        })
        .catch((error: unknown) => {
          if (!active) return;
          if (error instanceof DOMException && error.name === 'AbortError') return;
          setServerResults(null);
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
  }, [query, isOpen]);

  if (!isOpen) return null;

  const qLower = query.trim().toLowerCase();
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
  const usingServer = qLower.length >= 2 && serverResults !== null;
  const filtered = usingServer ? serverResults : localResults;
  const visibleResults = filtered.slice(0, 40);

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
            onChange={(event) => setQuery(event.target.value)}
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
          <span>
            {searching
              ? t('searching')
              : qLower
                ? t('search_results_count', { count: filtered.length })
                : t('recent_events')}
          </span>
          <span>{t('search_hint')}</span>
        </div>

        <ul className="search-results-list" aria-busy={searching}>
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
          {!searching && filtered.length === 0 && (
            <li className="search-empty">
              {t('no_search_results', { query })}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
};
