import React, { useState, useEffect, useRef } from 'react';
import type { EventDetailData } from '../../types/event';
import { fetchEventDetail } from '../../services/api';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { resolveArticleUrl } from '../../utils/url';
import { X, ExternalLink, Flag, ArrowUpRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { navigate } from '../../router';
import './DetailModal.css';

interface DetailModalProps {
  eventId: string;
  onClose: () => void;
  onReportProblem: (eventId: string) => void;
}

const sourceHost = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

const normalise = (value: string): string =>
  value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

const withoutHeadlineLead = (summary: string, title: string): string => {
  const sentences = summary.split(/(?<=[.!?])\s+/);
  if (sentences.length < 2) return summary;
  const headlineKey = normalise(title).slice(0, 80);
  if (headlineKey && normalise(sentences[0]).includes(headlineKey)) {
    return sentences.slice(1).join(' ');
  }
  return summary;
};

export const DetailModal: React.FC<DetailModalProps> = ({
  eventId,
  onClose,
  onReportProblem,
}) => {
  const [data, setData] = useState<EventDetailData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState<number>(0);
  const { t, i18n } = useTranslation();
  const campLabel = (camp: string): string =>
    camp === 'unrated' ? t('unrated') : t(camp, camp);
  const summaryLabel = (method: string): string => {
    if (method.startsWith('llm')) return t('summary_ai');
    if (method === 'extractive') return t('summary_compiled');
    return t('summary_event');
  };
  const absoluteTime = (value: string | null): string => {
    if (!value) return t('time_unknown');
    return new Date(value).toLocaleString(i18n.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  };
  const dossierRef = useRef<HTMLElement>(null);
  const dialogLabel = data?.title || t('event_dossier');
  useFocusTrap(true, dossierRef, onClose, {
    // The correction form sits on top of the dossier; let it close first.
    skipEscape: () => Boolean(document.querySelector('.report-modal-backdrop')),
  });

  const dialogRail = (
    <div className="dossier__rail">
      <span className="dossier__rail-label">Globe News Atlas</span>
      <span className="dossier__rail-divider">/</span>
      <span className="dossier__rail-label">{t('event_dossier')}</span>
      <button type="button" data-autofocus className="dossier__close" onClick={onClose} aria-label={t('close')}>
        <X size={18} />
      </button>
    </div>
  );

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);
    setData(null);

    fetchEventDetail(eventId)
      .then((detail) => {
        if (isMounted) {
          setData(detail);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to load event details');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [eventId, reloadToken]);

  if (loading) {
    return (
      <div className="dossier-backdrop" onClick={onClose} role="presentation">
        <article
          ref={dossierRef}
          className="dossier dossier--message"
          role="dialog"
          aria-modal="true"
          aria-label={t('event_dossier')}
          aria-busy="true"
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
        >
          {dialogRail}
          <div className="dossier__message-body">
            <p className="dossier__message">Loading the event dossier…</p>
          </div>
        </article>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="dossier-backdrop" onClick={onClose} role="presentation">
        <article
          ref={dossierRef}
          className="dossier dossier--message"
          role="dialog"
          aria-modal="true"
          aria-label={t('event_dossier')}
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
        >
          {dialogRail}
          <div className="dossier__message-body">
            <p className="dossier__message dossier__message--error">Could not load this event</p>
            <p className="dossier__message-detail">{error}</p>
            <button className="report-btn" onClick={() => setReloadToken((token) => token + 1)}>
              {t('retry')}
            </button>
          </div>
        </article>
      </div>
    );
  }

  if (!data) return null;

  const catColor = getCategoryColor(data.category);
  const coordinates =
    data.lat != null && data.lng != null
      ? `${data.lat.toFixed(3)}°, ${data.lng.toFixed(3)}°`
      : 'Not plotted';
  const primarySource = data.sources[0] || null;
  const primaryOutlet = primarySource?.outlet_name || 'Unknown outlet';
  const rated = data.spectrum.left + data.spectrum.centre + data.spectrum.right;
  const coverageColumns = data.coverage.filter(
    (col) => col.outlet_count > 0 || (col.sample_headlines?.length ?? 0) > 0
  );
  const sourcesShown = data.sources_shown ?? data.sources.length;
  const sourcesTotal = Math.max(
    data.sources_total ?? data.source_count ?? data.sources.length,
    sourcesShown,
  );
  const sourcesSampled = sourcesTotal > sourcesShown;
  const normalizedTitle = data.title.trim().toLowerCase();
  const normalizedSummary = data.summary.trim().toLowerCase();
  const summaryIsHeadlineOnly =
    !data.summary ||
    normalizedSummary === normalizedTitle ||
    (normalizedSummary.includes(normalizedTitle) &&
      normalizedSummary.length < normalizedTitle.length + 50);
  const lead =
    summaryIsHeadlineOnly && data.excerpt
      ? data.excerpt
      : withoutHeadlineLead(data.summary, data.title) ||
        data.excerpt ||
        'The publisher has supplied a headline, but no summary text yet.';
  const excerptText = (data.excerpt || '').trim();
  const showExcerpt =
    excerptText.length > 0 && !lead.toLowerCase().includes(excerptText.toLowerCase());

  return (
    <div
      className="dossier-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <article
        ref={dossierRef}
        className="dossier"
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        {dialogRail}

        <div className="dossier__scroll">
          <header className="dossier__header">
            <div className="dossier__kicker">
              <span
                className="dossier__category"
                style={{ color: catColor, borderColor: catColor }}
              >
                {t(`category.${data.category}`, data.category)}
              </span>
              <span className={`dossier__status dossier__status--${data.status}`}>
                {t(`status.${data.status}`, data.status)}
              </span>
              {data.location_name && <span className="dossier__dateline">{data.location_name}</span>}
              {data.is_single_source && (
                <span className="dossier__flag">{t('single_source_account')}</span>
              )}
              {data.has_coverage_gap && (
                <span className="dossier__flag dossier__flag--gap">{t('coverage_gap')}</span>
              )}
            </div>

            <h2 className="dossier__title">{data.title}</h2>

            <div className="dossier__byline">
              <span>{primaryOutlet}</span>
              {data.first_reported && (
                <span>
                  {t('first_reported')} <time dateTime={data.first_reported}>{absoluteTime(data.first_reported)}</time>
                </span>
              )}
              <span>{t('sources_count', { count: data.source_count })}</span>
              <span>{t('articles_count', { count: data.article_count })}</span>
            </div>
          </header>

          {data.content_warning && (
            <div className="dossier__warning" role="note">
              <strong>{t('content_note')}</strong>
              <span>{data.content_warning}</span>
            </div>
          )}

          <div className="dossier__columns">
            <main className="dossier__main">
              <section className="dossier-section">
                <div className="dossier-section__head">
                  <h3>{t('what_happened')}</h3>
                  <span className="dossier-section__meta">{summaryLabel(data.summary_method)}</span>
                </div>
                <p className="dossier__lead">{lead}</p>
                {data.is_single_source && (
                  <p className="dossier__caveat">
                    {t('single_source_caveat')}
                  </p>
                )}
                {data.has_coverage_gap && (
                  <p className="dossier__caveat dossier__caveat--gap">
                    {t('coverage_gap_caveat')}
                  </p>
                )}
              </section>

              {sourcesShown === 1 && sourcesTotal === 1 && !showExcerpt && primarySource && (
                <section className="dossier-section">
                  <div className="dossier-section__head">
                    <h3>{t('original_report')}</h3>
                    <span className="dossier-section__meta">
                      {primarySource.published_at
                        ? formatRelativeTime(primarySource.published_at)
                        : t('time_unknown')}
                    </span>
                  </div>
                  <a
                    className="report-card"
                    href={resolveArticleUrl(primarySource.url, primarySource.outlet_name, primarySource.title)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="report-card__outlet">
                      {primarySource.outlet_name}
                      <span className="report-card__alignment">{primarySource.alignment}</span>
                      {primarySource.via_google_news && (
                        <span className="via-google">{t('via_google_news')}</span>
                      )}
                      <ExternalLink size={11} />
                    </span>
                    <span className="report-card__title">{primarySource.title}</span>
                    <span className="report-card__cta">
                      {t('read_full_report')}
                      <ArrowUpRight size={13} />
                    </span>
                  </a>
                </section>
              )}

              {showExcerpt && (
                <section className="dossier-section">
                  <div className="dossier-section__head">
                    <h3>{t('from_the_report')}</h3>
                  </div>
                  <blockquote className="dossier__excerpt">{excerptText}</blockquote>
                  {primarySource && (
                    <a
                      className="dossier__source-link"
                      href={resolveArticleUrl(primarySource.url, primarySource.outlet_name, primarySource.title)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('continue_at', { outlet: primaryOutlet })}
                      <ArrowUpRight size={13} />
                    </a>
                  )}
                </section>
              )}

              {coverageColumns.length > 1 && (
                <section className="dossier-section">
                  <div className="dossier-section__head">
                    <h3>{t('how_covered')}</h3>
                    <span className="dossier-section__meta">
                      {t('outlets_count', { count: data.outlet_count })}
                    </span>
                  </div>
                  <div className="coverage-list">
                    {coverageColumns.map((col) => (
                      <div key={col.camp} className="coverage-row">
                        <div className="coverage-row__head">
                          <span className={`coverage-row__camp coverage-row__camp--${col.camp}`}>
                            {campLabel(col.camp)}
                          </span>
                          <span className="coverage-row__count">
                            {t('outlets_count', { count: col.outlet_count })} ·{' '}
                            {t('articles_count', { count: col.article_count })}
                          </span>
                        </div>
                        {col.sample_headlines && col.sample_headlines.length > 0 ? (
                          <ul className="coverage-row__headlines">
                            {col.sample_headlines.map((headline, index) => (
                              <li key={index}>
                                <a
                                  href={resolveArticleUrl(headline.url, headline.outlet, headline.title)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  <span>{headline.title}</span>
                                  <span className="coverage-row__outlet">
                                    {headline.outlet}{' '}
                                    {headline.via_google_news && (
                                      <span className="via-google">{t('via_google_news')}</span>
                                    )}{' '}
                                    <ExternalLink size={10} />
                                  </span>
                                </a>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="dossier__muted">{t('no_sample_headlines')}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section className="dossier-section">
                <div className="dossier-section__head">
                  <h3>{t('timeline')}</h3>
                </div>
                {data.timeline.length > 0 ? (
                  <ol className="timeline-list">
                    {data.timeline.map((entry, index) => (
                      <li key={index} className="timeline-list__item">
                        <time dateTime={entry.timestamp} title={absoluteTime(entry.timestamp)}>
                          {formatRelativeTime(entry.timestamp)}
                        </time>
                        <p>{entry.description}</p>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="dossier__muted">{t('no_updates')}</p>
                )}
              </section>
            </main>

            <aside className="dossier__aside">
              <section className="aside-block aside-block--record">
                <h3 className="aside-block__title">{t('event_record')}</h3>
                <dl className="record-list">
                  <div>
                    <dt>{t('status_label')}</dt>
                    <dd>{t(`status.${data.status}`, data.status)}</dd>
                  </div>
                  <div>
                    <dt>{t('severity')}</dt>
                    <dd>{t(`severity_${data.severity}`, data.severity)}</dd>
                  </div>
                  <div>
                    <dt>{t('category_label')}</dt>
                    <dd>{t(`category.${data.category}`, data.category)}</dd>
                  </div>
                  <div>
                    <dt>{t('confidence')}</dt>
                    <dd>{Math.round((data.confidence || 0) * 100)}%</dd>
                  </div>
                  <div>
                    <dt>{t('first_reported')}</dt>
                    <dd title={absoluteTime(data.first_reported)}>
                      {data.first_reported ? formatRelativeTime(data.first_reported) : t('time_unknown')}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('last_updated')}</dt>
                    <dd title={absoluteTime(data.last_updated)}>
                      {data.last_updated ? formatRelativeTime(data.last_updated) : t('time_unknown')}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('location')}</dt>
                    <dd>
                      {data.location_name || t('location_unavailable')}
                      {data.geo_precision ? ` · ${t(`geo_${data.geo_precision}`, data.geo_precision)}` : ''}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('coordinates')}</dt>
                    <dd className="record-list__mono">{coordinates}</dd>
                  </div>
                  <div>
                    <dt>{t('revision')}</dt>
                    <dd>{data.revision}</dd>
                  </div>
                </dl>
              </section>

              <section className="aside-block aside-block--balance">
                <h3 className="aside-block__title">{t('coverage_balance')}</h3>
                {rated > 0 ? (
                  <>
                    <div className="balance-bar" aria-label={t('coverage_balance_aria')}>
                      {(['left', 'centre', 'right'] as const).map((camp) => {
                        const value = data.spectrum[camp];
                        if (!value) return null;
                        return (
                          <span
                            key={camp}
                            className={`balance-bar__segment balance-bar__segment--${camp}`}
                            style={{ width: `${(value / rated) * 100}%` }}
                            title={`${campLabel(camp)}: ${value}`}
                          />
                        );
                      })}
                    </div>
                    <div className="balance-legend">
                      {(['left', 'centre', 'right'] as const).map((camp) => (
                        <span key={camp}>
                          <i className={`balance-dot balance-dot--${camp}`} />
                          {campLabel(camp)} <b>{data.spectrum[camp]}</b>
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="dossier__muted">
                    {t('no_alignment')}
                  </p>
                )}
                {data.spectrum.unrated > 0 && (
                  <p className="dossier__fineprint">
                    {t('unrated_sources', { count: data.spectrum.unrated })}
                  </p>
                )}
              </section>

              {sourcesTotal > 1 && (
              <section className="aside-block aside-block--sources">
                <h3 className="aside-block__title">
                  {t('sources')}{' '}
                  <span>
                    {sourcesSampled
                      ? t('sources_shown_of_total_short', {
                          shown: sourcesShown,
                          total: sourcesTotal,
                        })
                      : t('sources_count', { count: sourcesShown })}
                  </span>
                </h3>
                {sourcesSampled && (
                  <p className="dossier__fineprint">{t('sources_sampled_note')}</p>
                )}
                {data.sources.length > 0 ? (
                  <ol className="source-list">
                    {data.sources.map((src, index) => (
                      <li key={`${src.url}-${index}`}>
                        <a
                          href={resolveArticleUrl(src.url, src.outlet_name, src.title || data.title)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <span className="source-list__number">{String(index + 1).padStart(2, '0')}</span>
                          <span className="source-list__body">
                            <span className="source-list__outlet">
                              {src.outlet_name}
                              <span className="source-list__alignment">{src.alignment === 'unrated' ? t('unrated') : t(src.alignment, src.alignment)}</span>
                              {src.via_google_news && (
                                <span className="via-google">{t('via_google_news')}</span>
                              )}
                            </span>
                            <span className="source-list__title">{src.title}</span>
                            {src.snippet && <span className="source-list__snippet">{src.snippet}</span>}
                            <span className="source-list__host">{sourceHost(src.url)}</span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="dossier__muted">{t('no_source_links')}</p>
                )}
              </section>
              )}

              {(data.reddit_threads > 0 || data.bluesky_posts > 0) && (
                <section className="aside-block aside-block--social">
                  <h3 className="aside-block__title">{t('public_discussion')}</h3>
                  <div className="social-counts">
                    {data.reddit_threads > 0 && (
                      <span>
                        Reddit <b>{data.reddit_threads}</b>
                      </span>
                    )}
                    {data.bluesky_posts > 0 && (
                      <span>
                        Bluesky <b>{data.bluesky_posts}</b>
                      </span>
                    )}
                  </div>
                  <p className="dossier__fineprint">
                    {t('public_discussion_counts_only', {
                      count: data.reddit_threads + data.bluesky_posts,
                    })}
                  </p>
                </section>
              )}
            </aside>
          </div>
        </div>

        <footer className="dossier__footer">
          <span>
            {t('sources_count', { count: data.source_count })} ·{' '}
            {t('outlets_count', { count: data.outlet_count })} ·{' '}
            {data.countries.length > 0 ? data.countries.join(', ') : t('no_country_tags')}
          </span>
          <div className="dossier__footer-actions">
            <button
              className="report-btn"
              onClick={() => {
                onClose();
                navigate(`/event/${data.id}`);
              }}
            >
              <ArrowUpRight size={12} /> Open as page
            </button>
            <button className="report-btn" onClick={() => onReportProblem(data.id)}>
              <Flag size={12} /> {t('report_problem')}
            </button>
          </div>
        </footer>
      </article>
    </div>
  );
};
