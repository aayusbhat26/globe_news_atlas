import React from 'react';
import type { SnapshotEvent } from '../../types/snapshot';
import { getCategoryColor, SPECTRUM_COLORS } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { useTranslation } from 'react-i18next';
import './ListView.css';

interface ListViewProps {
  events: SnapshotEvent[];
  onEventClick: (eventId: string) => void;
}

export const ListView: React.FC<ListViewProps> = ({ events, onEventClick }) => {
  const { t } = useTranslation();

  return (
    <div className="list-view-container" role="region" aria-label="Accessible News Events Table">
      <div className="list-view-wrapper">
        <table className="list-view-table" role="table">
          <thead>
            <tr>
              <th scope="col">{t('event')}</th>
              <th scope="col">{t('category_label')}</th>
              <th scope="col">{t('location')}</th>
              <th scope="col">{t('sources')}</th>
              <th scope="col">{t('coverage')}</th>
              <th scope="col">{t('updated')}</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => {
              const catColor = getCategoryColor(event.cat);
              const left = event.sp?.left || 0;
              const centre = event.sp?.centre || 0;
              const right = event.sp?.right || 0;

              return (
                <tr
                  key={event.id}
                  className="list-view-row"
                  tabIndex={0}
                  role="row"
                  onClick={() => onEventClick(event.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onEventClick(event.id);
                    }
                  }}
                >
                  <td className="list-view-cell--title">
                    <span className="list-view-title">{event.t}</span>
                    {event.ss && <span className="list-badge list-badge--warning">{t('single_source')}</span>}
                    {event.cg && <span className="list-badge list-badge--info">{t('coverage_gap')}</span>}
                  </td>
                  <td>
                    <span className="category-badge" style={{ color: catColor, borderColor: catColor }}>
                      {t(`category.${event.cat}`, event.cat)}
                    </span>
                  </td>
                  <td className="list-view-cell--mono">
                    {event.loc ||
                      (Number.isFinite(event.lat) && Number.isFinite(event.lng)
                        ? `${event.lat.toFixed(1)}°, ${event.lng.toFixed(1)}°`
                        : t('location_unavailable'))}
                  </td>
                  <td>{t('outlets_count', { count: event.oc || 1 })}</td>
                  <td>
                    <span
                      className="spectrum-text-pill"
                      aria-label={`Left: ${left}, Centre: ${centre}, Right: ${right}`}
                    >
                      <span style={{ color: SPECTRUM_COLORS.left }}>L:{left}</span>{' '}
                      <span style={{ color: SPECTRUM_COLORS.centre }}>C:{centre}</span>{' '}
                      <span style={{ color: SPECTRUM_COLORS.right }}>R:{right}</span>
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {event.at ? formatRelativeTime(event.at) : 'Unknown'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {events.length === 0 && (
          <div className="list-view-empty">
            {t('no_events_in_window')}
          </div>
        )}
      </div>
    </div>
  );
};
