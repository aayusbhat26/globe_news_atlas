import React, { useRef } from 'react';
import { MapPin, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { SnapshotEvent } from '../../types/snapshot';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import './LocationDispatch.css';

interface LocationDispatchProps {
  events: SnapshotEvent[];
  onSelect: (eventId: string) => void;
  onClose: () => void;
}

export const LocationDispatch: React.FC<LocationDispatchProps> = ({
  events,
  onSelect,
  onClose,
}) => {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLElement>(null);
  const place = events[0]?.loc || t('location_unavailable');
  useFocusTrap(true, panelRef, onClose);

  return (
    <section ref={panelRef} className="dispatch-panel" role="dialog" aria-label={`${events.length} ${t('dispatches')}: ${place}`}>
      <header className="dispatch-panel__head">
        <div>
          <span className="dispatch-panel__eyebrow">{t('location_desk')}</span>
          <h2 className="dispatch-panel__title">
            <MapPin size={14} />
            {place}
          </h2>
          <p className="dispatch-panel__count">
            {t('dispatches_count', { count: events.length })}
          </p>
        </div>
        <button
          type="button"
          data-autofocus
          className="dispatch-panel__close"
          onClick={onClose}
          aria-label={t('close')}
        >
          <X size={16} />
        </button>
      </header>

      <ul className="dispatch-panel__list">
        {events.map((event) => {
          const color = getCategoryColor(event.cat);
          return (
            <li key={event.id}>
              <button
                type="button"
                className="dispatch-item"
                onClick={() => onSelect(event.id)}
              >
                <span className="dispatch-item__rule" style={{ backgroundColor: color }} />
                <span className="dispatch-item__body">
                  <span className="dispatch-item__meta">
                    <span className="dispatch-item__category" style={{ color }}>
                      {t(`category.${event.cat}`, event.cat)}
                    </span>
                    <span>{t('outlets_count', { count: event.oc || 1 })}</span>
                    {event.at && <span>{formatRelativeTime(event.at)}</span>}
                  </span>
                  <span className="dispatch-item__title">{event.t}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
};
