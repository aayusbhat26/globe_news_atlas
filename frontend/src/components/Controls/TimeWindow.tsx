import React from 'react';
import { useTranslation } from 'react-i18next';
import './Controls.css';

interface FloatingDockProps {
  timeWindow: '1h' | '24h' | '7d' | '30d';
  onChangeTimeWindow: (w: '1h' | '24h' | '7d' | '30d') => void;
  spectrumFilter: 'all' | 'left' | 'centre' | 'right';
  onChangeSpectrumFilter: (f: 'all' | 'left' | 'centre' | 'right') => void;
  eventCount: number;
  totalEventCount?: number;
}

export const FloatingDock: React.FC<FloatingDockProps> = ({
  timeWindow,
  onChangeTimeWindow,
  spectrumFilter,
  onChangeSpectrumFilter,
  eventCount,
  totalEventCount = eventCount,
}) => {
  const { t } = useTranslation();
  const isCapped = totalEventCount > eventCount;

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
        title={isCapped ? t('events_shown_tooltip', { total: totalEventCount }) : undefined}
      >
        {isCapped
          ? t('events_shown_of_total', {
              shown: eventCount,
              total: totalEventCount,
              count: totalEventCount,
            })
          : t('events_count', { count: eventCount })}
      </span>
    </div>
  );
};
