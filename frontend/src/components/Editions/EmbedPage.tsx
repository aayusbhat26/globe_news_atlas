import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Globe } from 'lucide-react';
import { fetchEventDetail } from '../../services/api';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import type { EventDetailData } from '../../types/event';
import './Embed.css';

interface EmbedPageProps {
  eventId: string;
}

export const EmbedPage: React.FC<EmbedPageProps> = ({ eventId }) => {
  const [data, setData] = useState<EventDetailData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    document.title = 'Globe News Atlas — event card';
    fetchEventDetail(eventId)
      .then(setData)
      .catch(() => setError(true));
  }, [eventId]);

  if (error) {
    return (
      <div className="embed-canvas">
        <div className="embed-card">
          <p className="embed-brand">Globe News Atlas</p>
          <h1 className="embed-title">This event is no longer in the active window.</h1>
          <a className="embed-link" href={`/event/${eventId}`} target="_blank" rel="noreferrer">
            Open the dossier <ArrowUpRight size={12} />
          </a>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="embed-canvas">
        <div className="embed-card">
          <p className="embed-loading">Loading event card…</p>
        </div>
      </div>
    );
  }

  const color = getCategoryColor(data.category);
  const summary =
    data.summary && data.summary.trim().toLowerCase() !== data.title.trim().toLowerCase()
      ? data.summary
      : data.excerpt;

  return (
    <div className="embed-canvas">
      <article className="embed-card">
        <header className="embed-topline">
          <span className="embed-brand">
            <Globe size={13} strokeWidth={1.7} aria-hidden="true" />
            Globe News Atlas
          </span>
          <span className="embed-category" style={{ color }}>{data.category}</span>
        </header>

        <h1 className="embed-title">{data.title}</h1>

        {summary && <p className="embed-summary">{summary}</p>}

        <footer className="embed-foot">
          <span>
            {data.location_name || 'Unlocated'}
            {data.last_updated ? ` · ${formatRelativeTime(data.last_updated)}` : ''}
          </span>
          <span>
            {data.outlet_count} {data.outlet_count === 1 ? 'outlet' : 'outlets'} · {data.source_count}{' '}
            {data.source_count === 1 ? 'source' : 'sources'}
          </span>
        </footer>

        <a className="embed-link" href={`/event/${eventId}`} target="_blank" rel="noreferrer">
          Open the full dossier <ArrowUpRight size={12} />
        </a>
      </article>
    </div>
  );
};
