import React from 'react';
import type { SnapshotEvent } from '../../types/snapshot';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { X, ArrowRight, AlertTriangle, MapPin } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import './HoverCard.css';

interface HoverCardProps {
  event: SnapshotEvent;
  onClose: () => void;
  onClick: (eventId: string) => void;
}

type StackedEvent = SnapshotEvent & { _stackSize?: number };

export const HoverCard: React.FC<HoverCardProps> = ({ event, onClose, onClick }) => {
  const { t } = useTranslation();
  const catColor = getCategoryColor(event.cat);
  const stackSize = (event as StackedEvent)._stackSize ?? 1;

  const left = event.sp?.left ?? 0;
  const centre = event.sp?.centre ?? 0;
  const right = event.sp?.right ?? 0;
  const unrated = event.sp?.unrated ?? 0;
  const ratedTotal = left + centre + right;

  const leftPct = ratedTotal > 0 ? (left / ratedTotal) * 100 : 0;
  const centrePct = ratedTotal > 0 ? (centre / ratedTotal) * 100 : 0;
  const rightPct = ratedTotal > 0 ? (right / ratedTotal) * 100 : 0;

  return (
    <div
      className="hover-card"
      role="dialog"
      aria-label={event.t}
      onClick={() => onClick(event.id)}
    >
      <div className="hover-card__header">
        <div className="hover-card__badges">
          <span className="category-badge" style={{ color: catColor, borderColor: catColor }}>
            {t(`category.${event.cat}`, event.cat)}
          </span>
          <span className={`status-badge status-badge--${event.st}`}>
            {t(`status.${event.st}`, event.st)}
          </span>
          {event.ss && (
            <span className="warning-badge" title="Only reported by a single source">
              <AlertTriangle size={10} style={{ display: 'inline', marginRight: 2 }} />
              {t('single_source')}
            </span>
          )}
          {event.cg && <span className="warning-badge warning-badge--warn">{t('coverage_gap')}</span>}
          {stackSize > 1 && (
            <span className="warning-badge warning-badge--info">
              <MapPin size={10} style={{ display: 'inline', marginRight: 2 }} />
              {t('at_this_location', { count: stackSize })}
            </span>
          )}
        </div>
        <button
          className="hover-card__close"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          aria-label="Close hover preview"
        >
          <X size={14} />
        </button>
      </div>

      <h3 className="hover-card__title">{event.t}</h3>

      {event.sum ? (
        <p className="hover-card__summary">{event.sum}</p>
      ) : (
        <p className="hover-card__summary hover-card__summary--empty">
          {t('no_summary')}
        </p>
      )}

      {event.loc && (
        <div className="hover-card__location">
          <MapPin size={12} />
          <span>{event.loc}</span>
        </div>
      )}

      {/* Political Spectrum Mini-Bar */}
      {ratedTotal > 0 ? (
        <div className="spectrum-mini" aria-label={`Spectrum: Left ${left}, Centre ${centre}, Right ${right}`}>
          <div className="spectrum-mini__bar">
            <div className="spectrum-mini__segment spectrum-mini__segment--left" style={{ width: `${leftPct}%` }} />
            <div className="spectrum-mini__segment spectrum-mini__segment--centre" style={{ width: `${centrePct}%` }} />
            <div className="spectrum-mini__segment spectrum-mini__segment--right" style={{ width: `${rightPct}%` }} />
          </div>
          <div className="spectrum-mini__labels">
            <span>L: {left}</span>
            <span>C: {centre}</span>
            <span>R: {right}</span>
            {unrated > 0 && <span>Unrated: {unrated}</span>}
          </div>
        </div>
      ) : (
        <div className="spectrum-mini spectrum-mini--empty">
          {t('coverage_unrated')}
          {unrated > 0 ? ` (${unrated} unrated)` : ''}.
        </div>
      )}

      <div className="hover-card__footer">
        <span>
          {event.at ? `${t('updated')} ${formatRelativeTime(event.at)}` : t('time_unknown')}
          {event.src ? ` · ${event.src}` : ''}
        </span>
        <span className="hover-card__action">
          {t('open_dossier')} <ArrowRight size={12} />
        </span>
      </div>
    </div>
  );
};
