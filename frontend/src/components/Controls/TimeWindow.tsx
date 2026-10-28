import React from 'react';
import { useTranslation } from 'react-i18next';
import './Controls.css';

interface FloatingDockProps {
  timeWindow: '1h' | '24h' | '7d' | '30d';
  onChangeTimeWindow: (w: '1h' | '24h' | '7d' | '30d') => void;
  spectrumFilter: 'all' | 'left' | 'centre' | 'right';
  onChangeSpectrumFilter: (f: 'all' | 'left' | 'centre' | 'right') => void;
  eventCount: number;
  /** Events available to filter in this snapshot (n.e). */
  matchingTotal?: number;
  /** True number of events in the window (n.total). */
  windowTotal?: number;
  /** True when the API served a capped subset of the window. */
  windowCapped?: boolean;
  filtersActive?: boolean;
}

export const FloatingDock: React.FC<FloatingDockProps> = ({
  timeWindow,
  onChangeTimeWindow,
  spectrumFilter,
  onChangeSpectrumFilter,
  eventCount,
  matchingTotal,
  windowTotal,
  windowCapped = false,
  filtersActive = false,
}) => {
  const { t } = useTranslation();
  const available = Math.max(eventCount, matchingTotal ?? eventCount);
  const trueTotal = Math.max(available, windowTotal ?? available);
  const capped = windowCapped || available < trueTotal;

  const countLabel = filtersActive
    ? eventCount < available
      ? t('events_matching_of_total', {
          shown: eventCount,
          total: available,
          count: available,
        })
      : t('events_matching_count', { count: eventCount })
    : capped
      ? t('events_shown_of_total', {
          shown: eventCount,
          total: trueTotal,
          count: trueTotal,
        })
      : t('events_count', { count: eventCount });

  const capNote = capped
    ? t('events_window_cap_note', {
        shown: available,
        total: trueTotal,
        count: trueTotal,
      })
    : null;

  return (
    <div className="floating-dock" role="region" aria-label={t('time_and_perspective')}>
      <div className="dock-section">
        <span className="dock-label">{t('window')}</span>
        <div className="dock-pill-group" role="group" aria-label={t('time_window')}>
          {(['1h', '24h', '7d', '30d'] as const).map((w) => (
            <button
              key={w}
              type="button"
              className={`dock-pill ${timeWindow === w ? 'dock-pill--active' : ''}`}
              onClick={() => onChangeTimeWindow(w)}
              aria-pressed={timeWindow === w}
            >
              {w.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="dock-section">
        <span className="dock-label">{t('perspective')}</span>
        <div className="dock-pill-group" role="group" aria-label={t('perspective')}>
          {(['all', 'left', 'centre', 'right'] as const).map((s) => (
            <button
              key={s}
              type="button"
              className={`dock-pill ${spectrumFilter === s ? 'dock-pill--active' : ''}`}
              onClick={() => onChangeSpectrumFilter(s)}
              aria-pressed={spectrumFilter === s}
            >
              {t(s, s)}
            </button>
          ))}
        </div>
      </div>

      <span
        className="dock-count"
        aria-live="polite"
        title={capNote || countLabel}
      >
        <span>{countLabel}</span>
        {capNote && <small className="dock-count__cap">{capNote}</small>}
      </span>
    </div>
  );
};
