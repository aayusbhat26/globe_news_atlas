import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight,
  Check,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Link2,
  Plus,
} from 'lucide-react';
import { PageShell } from './PageShell';
import {
  addWatchlineEntry,
  fetchCitation,
  fetchWatchlineEntries,
  removeWatchlineEntry,
} from '../../services/atlas';
import { ApiError, fetchEventDetail } from '../../services/api';
import { useAuth } from '../../auth/AuthContext';
import { navigate } from '../../router';
import { copyToClipboard } from '../../utils/auth';
import { getCategoryColor } from '../../utils/colors';
import { formatRelativeTime } from '../../utils/time';
import { resolveArticleUrl } from '../../utils/url';
import type { Citation, WatchlineEntry } from '../../types/atlas';
import type { EventDetailData } from '../../types/event';
import './EventPage.css';

interface EventPageProps {
  eventId: string;
}

const hostOf = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

export const EventPage: React.FC<EventPageProps> = ({ eventId }) => {
  const auth = useAuth();
  const [data, setData] = useState<EventDetailData | null>(null);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const [copyFallback, setCopyFallback] = useState<{ label: string; value: string } | null>(null);
  const [entries, setEntries] = useState<WatchlineEntry[]>([]);
  const [followBusy, setFollowBusy] = useState<string | null>(null);
  const [followMessage, setFollowMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!auth.user) {
      setEntries([]);
      return;
    }
    fetchWatchlineEntries()
      .then((result) => setEntries(result.entries))
      .catch(() => undefined);
  }, [auth.user]);

  const toggleCountry = async (country: string) => {
    if (!auth.user) {
      navigate(`/login?next=${encodeURIComponent(`/event/${eventId}`)}`);
      return;
    }
    const existing = entries.find(
      (entry) => entry.kind === 'place' && entry.key === country.toLowerCase(),
    );
    setFollowBusy(country);
    setFollowMessage(null);
    try {
      const result = existing
        ? await removeWatchlineEntry(existing.id)
        : await addWatchlineEntry('place', country, country);
      setEntries(result.entries);
      setFollowMessage(
        existing ? `${country} removed from your watchline.` : `${country} pinned to your watchline.`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate(`/login?next=${encodeURIComponent(`/event/${eventId}`)}`);
        return;
      }
      setFollowMessage(err instanceof Error ? err.message : 'Could not update your watchline.');
    } finally {
      setFollowBusy(null);
    }
  };

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([fetchEventDetail(eventId), fetchCitation(eventId).catch(() => null)])
      .then(([detail, cite]) => {
        setData(detail);
        setCitation(cite);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'This event could not be found.');
      })
      .finally(() => setLoading(false));
  }, [eventId]);

  useEffect(() => {
    if (!data) return;
    const origin = window.location.origin;
    const description = (data.summary || data.excerpt || data.title).slice(0, 180);
    const pageTitle = `${data.title} — Globe News Atlas`;
    const canonicalUrl = citation?.url || `${origin}/event/${encodeURIComponent(eventId)}`;
    const imageUrl = `${origin}/og-image.png`;
    const restores: Array<() => void> = [];

    let descriptionMeta = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = descriptionMeta?.getAttribute('content') || '';
    if (!descriptionMeta) {
      descriptionMeta = document.createElement('meta');
      descriptionMeta.name = 'description';
      document.head.appendChild(descriptionMeta);
    }
    descriptionMeta.setAttribute('content', description);

    let canonical = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    const previousCanonical = canonical?.getAttribute('href') || '';
    const canonicalCreated = !canonical;
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonical.href = canonicalUrl;

    const meta = [
      ['property', 'og:type', 'article'],
      ['property', 'og:site_name', 'Globe News Atlas'],
      ['property', 'og:title', pageTitle],
      ['property', 'og:description', description],
      ['property', 'og:url', canonicalUrl],
      ['property', 'og:image', imageUrl],
      ['property', 'og:image:alt', data.title],
      ['name', 'twitter:card', 'summary_large_image'],
      ['name', 'twitter:title', pageTitle],
      ['name', 'twitter:description', description],
      ['name', 'twitter:image', imageUrl],
    ] as const;

    for (const [attribute, key, content] of meta) {
      let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`);
      const created = !element;
      const previous = element?.getAttribute('content') ?? null;
      if (!element) {
        element = document.createElement('meta');
        element.setAttribute(attribute, key);
        document.head.appendChild(element);
      }
      element.setAttribute('content', content);
      restores.push(() => {
        if (created) {
          element?.remove();
        } else if (previous != null) {
          element?.setAttribute('content', previous);
        } else {
          element?.removeAttribute('content');
        }
      });
    }

    return () => {
      descriptionMeta?.setAttribute('content', previousDescription);
      if (canonicalCreated) {
        canonical?.remove();
      } else if (canonical) {
        canonical.href = previousCanonical;
      }
      restores.forEach((restore) => restore());
    };
  }, [citation, data, eventId]);

  const embedCode = useMemo(
    () =>
      `<iframe src="${window.location.origin}/embed/event/${eventId}" title="Globe News Atlas event card" width="420" height="330" loading="lazy" style="border:0"></iframe>`,
    [eventId],
  );

  const copy = async (key: string, value: string, label: string) => {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(key);
      setCopyFallback(null);
      setCopyNotice(`${label} copied.`);
      window.setTimeout(() => {
        setCopied(null);
        setCopyNotice(null);
      }, 2400);
    } else {
      setCopied(null);
      setCopyNotice(
        `Could not copy the ${label.toLowerCase()}. Select the text below and copy it manually.`,
      );
      setCopyFallback({ label, value });
    }
  };

  const downloadBibtex = () => {
    if (!citation) return;
    const blob = new Blob([citation.bibtex], { type: 'application/x-bibtex' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${citation.event_id}.bib`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <PageShell kicker="Event dossier" title="Reading the dossier" width="narrow">
        <div className="page-loading" role="status">Loading the event dossier…</div>
      </PageShell>
    );
  }

  if (error || !data) {
    return (
      <PageShell kicker="Event dossier" title="Dossier unavailable" width="narrow">
        <div className="page-error" role="alert">
          <h2>This event could not be opened.</h2>
          <p>{error || 'It may have fallen out of the active window.'}</p>
          <button type="button" className="page-secondary" onClick={() => window.history.back()}>
            Go back
          </button>
        </div>
      </PageShell>
    );
  }

  const color = getCategoryColor(data.category);
  const rated = data.spectrum.left + data.spectrum.centre + data.spectrum.right;
  const coverageColumns = data.coverage.filter(
    (column) => column.outlet_count > 0 || column.sample_headlines?.length,
  );
  const sourcesShown = data.sources_shown ?? data.sources.length;
  const sourcesTotal = Math.max(
    data.sources_total ?? data.source_count ?? data.sources.length,
    sourcesShown,
  );
  const sourcesSampled = sourcesTotal > sourcesShown;
  const deck =
    data.summary && data.summary.trim().toLowerCase() !== data.title.trim().toLowerCase()
      ? data.summary
      : data.excerpt;

  return (
    <PageShell
      kicker={`${data.category} · event dossier`}
      title={data.title}
      standfirst={deck}
      documentTitle={`${data.title} — Globe News Atlas`}
      meta={
        <>
          {data.location_name && <span>{data.location_name}</span>}
          {data.last_updated && <span>Updated {formatRelativeTime(data.last_updated)}</span>}
          <span>{data.outlet_count} outlets</span>
          <span>{data.source_count} sources</span>
          <span>Revision {data.revision}</span>
        </>
      }
      actions={
        <>
          <button
            type="button"
            className="page-secondary"
            onClick={() => copy('link', citation?.url || `${window.location.origin}/event/${eventId}`, 'Link')}
          >
            {copied === 'link' ? <Check size={13} /> : <Link2 size={13} />}
            {copied === 'link' ? 'Copied' : 'Copy link'}
          </button>
          <a
            className="page-secondary event-page__embed-link"
            href={`/embed/event/${eventId}`}
            target="_blank"
            rel="noreferrer"
          >
            Embed preview <ArrowUpRight size={12} />
          </a>
        </>
      }
    >
      <div className="event-page">
        <p className="sr-only" role="status" aria-live="polite">
          {copyNotice || ''}
        </p>
        {copyFallback && (
          <div className="event-copy-fallback" role="alert">
            <label htmlFor="event-copy-fallback">
              {copyNotice || `${copyFallback.label} is ready to copy.`}
            </label>
            <textarea
              id="event-copy-fallback"
              readOnly
              rows={copyFallback.label === 'Embed code' ? 4 : 3}
              value={copyFallback.value}
              onFocus={(event) => event.currentTarget.select()}
              onClick={(event) => event.currentTarget.select()}
            />
            <button
              type="button"
              className="page-quiet"
              onClick={() => {
                setCopyFallback(null);
                setCopyNotice(null);
              }}
            >
              Dismiss
            </button>
          </div>
        )}
        {data.content_warning && (
          <div className="event-warning" role="note">
            <strong>Content note</strong>
            <span>{data.content_warning}</span>
          </div>
        )}

        <div className="event-layout">
          <main className="event-main">
            <section className="event-section">
              <div className="event-section__head">
                <h2>What we know</h2>
                <span style={{ color }}>
                  {data.status} · {data.severity}
                </span>
              </div>
              {data.summary && deck !== data.summary && <p className="event-lead">{data.summary}</p>}
              {data.excerpt && (
                <blockquote className="event-excerpt">
                  {data.excerpt}
                  {data.sources[0] && (
                    <cite>
                      {data.sources[0].outlet_name}
                      {data.sources[0].published_at ? ` · ${formatRelativeTime(data.sources[0].published_at)}` : ''}
                    </cite>
                  )}
                </blockquote>
              )}
              {data.is_single_source && (
                <p className="event-caveat">
                  This dispatch rests on a single outlet. Treat it as an unconfirmed account until
                  another independent source reports it.
                </p>
              )}
            </section>

            <section className="event-section">
              <div className="event-section__head">
                <h2>How it is covered</h2>
                <span>{data.outlet_count} distinct outlets</span>
              </div>
              <div className="event-spectrum">
                {rated > 0 ? (
                  <>
                    <div className="event-spectrum__bar" aria-label="Coverage balance">
                      {(['left', 'centre', 'right'] as const).map((camp) => {
                        const value = data.spectrum[camp];
                        if (!value) return null;
                        return (
                          <span
                            key={camp}
                            className={`event-spectrum__segment event-spectrum__segment--${camp}`}
                            style={{ width: `${(value / rated) * 100}%` }}
                            title={`${camp}: ${value}`}
                          />
                        );
                      })}
                    </div>
                    <div className="event-spectrum__legend">
                      {(['left', 'centre', 'right'] as const).map((camp) => (
                        <span key={camp}>
                          {camp} <b>{data.spectrum[camp]}</b>
                        </span>
                      ))}
                      {data.spectrum.unrated > 0 && (
                        <span>unrated <b>{data.spectrum.unrated}</b></span>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="event-muted">
                    None of the reporting outlets carry a published editorial alignment.
                  </p>
                )}
                {data.has_coverage_gap && (
                  <p className="event-caveat">
                    Rated coverage sits entirely on one side of the spectrum. The Atlas records this,
                    not a conclusion about the story.
                  </p>
                )}
              </div>

              {coverageColumns.length > 0 && (
                <div className="event-coverage">
                  {coverageColumns.map((column) => (
                    <div key={column.camp} className="event-coverage__column">
                      <div className="event-coverage__head">
                        <span>{column.camp}</span>
                        <span>{column.outlet_count} outlets · {column.article_count} articles</span>
                      </div>
                      {column.framing_note && <p>{column.framing_note}</p>}
                      {column.sample_headlines?.length > 0 && (
                        <ul>
                          {column.sample_headlines.map((headline, index) => (
                            <li key={index}>
                              <a
                                href={resolveArticleUrl(headline.url, headline.outlet, headline.title)}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {headline.title}
                                <span>
                                  {headline.outlet}
                                  {headline.via_google_news && (
                                    <span className="via-google">via Google News</span>
                                  )}{' '}
                                  <ExternalLink size={10} />
                                </span>
                              </a>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="event-section">
              <div className="event-section__head">
                <h2>How the record changed</h2>
                <span>{data.timeline.length} entries</span>
              </div>
              {data.timeline.length > 0 ? (
                <ol className="event-timeline">
                  {data.timeline.map((entry, index) => (
                    <li key={index}>
                      <time dateTime={entry.timestamp}>{formatRelativeTime(entry.timestamp)}</time>
                      <p>{entry.description}</p>
                      <span>{entry.source_count} {entry.source_count === 1 ? 'source' : 'sources'}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="event-muted">No revisions recorded for this dispatch.</p>
              )}
            </section>

            <section className="event-section">
              <div className="event-section__head">
                <h2>Sources</h2>
                <span>
                  {sourcesSampled
                    ? `Showing ${sourcesShown} of ${sourcesTotal} sources`
                    : `${sourcesShown} ${sourcesShown === 1 ? 'link' : 'links'}`}
                </span>
              </div>
              {sourcesSampled && (
                <p className="event-muted">
                  The dossier lists a ranked sample of the sources attached to this
                  event; the full source count is {sourcesTotal}.
                </p>
              )}
              {data.sources.length > 0 ? (
                <ol className="event-sources">
                  {data.sources.map((source, index) => (
                    <li key={`${source.url}-${index}`}>
                      <span className="event-sources__index">{String(index + 1).padStart(2, '0')}</span>
                      <div>
                        <span className="event-sources__outlet">
                          {source.outlet_name}
                          <span>{source.alignment}</span>
                          {source.via_google_news && (
                            <span className="via-google">via Google News</span>
                          )}
                          {source.published_at && <span>{formatRelativeTime(source.published_at)}</span>}
                        </span>
                        <a
                          href={resolveArticleUrl(source.url, source.outlet_name, source.title)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {source.title}
                          <ExternalLink size={11} />
                        </a>
                        {source.snippet && <p>{source.snippet}</p>}
                        <small>{hostOf(source.url)}</small>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="event-muted">No direct source links were supplied.</p>
              )}
            </section>
          </main>

          <aside className="event-aside">
            <section className="event-aside__block">
              <h2>The record</h2>
              <dl className="event-record">
                <div>
                  <dt>First reported</dt>
                  <dd>{data.first_reported ? formatRelativeTime(data.first_reported) : 'Unknown'}</dd>
                </div>
                <div>
                  <dt>Last updated</dt>
                  <dd>{data.last_updated ? formatRelativeTime(data.last_updated) : 'Unknown'}</dd>
                </div>
                <div>
                  <dt>Location</dt>
                  <dd>{data.location_name || 'Not geocoded'}</dd>
                </div>
                <div>
                  <dt>Coordinates</dt>
                  <dd className="event-record__mono">
                    {data.lat != null && data.lng != null
                      ? `${data.lat.toFixed(3)}, ${data.lng.toFixed(3)}`
                      : 'Not plotted'}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{Math.round((data.confidence || 0) * 100)}%</dd>
                </div>
                <div>
                  <dt>Countries</dt>
                  <dd>{data.countries.length ? data.countries.join(', ') : 'None tagged'}</dd>
                </div>
                <div>
                  <dt>Official source</dt>
                  <dd>{data.has_official_source ? 'Attached' : 'Not attached'}</dd>
                </div>
              </dl>
            </section>

            {data.countries.length > 0 && (
              <section className="event-aside__block event-follow">
                <h2>Follow a desk</h2>
                <p>Pin any country named in this dispatch. Its desk appears on your watchline.</p>
                <div className="event-follow__chips">
                  {data.countries.map((country) => {
                    const followed = entries.some(
                      (entry) => entry.kind === 'place' && entry.key === country.toLowerCase(),
                    );
                    return (
                      <button
                        key={country}
                        type="button"
                        className={followed ? 'is-followed' : ''}
                        onClick={() => toggleCountry(country)}
                        disabled={followBusy === country || auth.loading}
                      >
                        {followed ? <Check size={12} /> : <Plus size={12} />}
                        {country}
                      </button>
                    );
                  })}
                </div>
                {followMessage && (
                  <p className="event-follow__message" role="status">{followMessage}</p>
                )}
              </section>
            )}

            {citation && (
              <section className="event-aside__block event-cite">
                <div className="event-cite__head">
                  <h2>Cite this event</h2>
                  <button
                    type="button"
                    className="page-icon-btn"
                    onClick={downloadBibtex}
                    aria-label="Download BibTeX citation"
                    title="Download .bib"
                  >
                    <Download size={14} />
                  </button>
                </div>
                <div className="event-cite__row">
                  <span>APA</span>
                  <button type="button" onClick={() => copy('apa', citation.apa, 'APA citation')}>
                    {copied === 'apa' ? <Check size={12} /> : <Copy size={12} />}
                    {copied === 'apa' ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <p className="event-cite__text">{citation.apa}</p>
                <div className="event-cite__row">
                  <span>BibTeX</span>
                  <button type="button" onClick={() => copy('bibtex', citation.bibtex, 'BibTeX citation')}>
                    {copied === 'bibtex' ? <Check size={12} /> : <Copy size={12} />}
                    {copied === 'bibtex' ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <pre className="event-cite__pre">{citation.bibtex}</pre>
              </section>
            )}

            <section className="event-aside__block event-embed">
              <div className="event-embed__head">
                <h2>Embed this card</h2>
                <FileText size={14} aria-hidden="true" />
              </div>
              <p>Paste this iframe into a classroom page or blog. It stays linked to the live record.</p>
              <textarea readOnly value={embedCode} aria-label="Embed code" rows={4} />
              <div className="event-embed__actions">
                <button type="button" className="page-secondary" onClick={() => copy('embed', embedCode, 'Embed code')}>
                  {copied === 'embed' ? <Check size={12} /> : <Copy size={12} />}
                  {copied === 'embed' ? 'Copied' : 'Copy iframe'}
                </button>
                <a className="page-quiet" href={`/embed/event/${eventId}`} target="_blank" rel="noreferrer">
                  Open preview <ArrowUpRight size={12} />
                </a>
              </div>
            </section>

            {data.corrections.length > 0 && (
              <section className="event-aside__block">
                <h2>Corrections</h2>
                <ul className="event-corrections">
                  {data.corrections.map((correction, index) => (
                    <li key={index}>
                      <span>{formatRelativeTime(correction.timestamp)}</span>
                      <p>{correction.description}</p>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>
      </div>
    </PageShell>
  );
};
