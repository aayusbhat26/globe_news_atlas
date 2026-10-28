import React, { useEffect, useRef, useState } from 'react';
import { ExternalLink, MessageSquare, ShieldCheck } from 'lucide-react';
import { PageShell } from './PageShell';
import './XDesk.css';

declare global {
  interface Window {
    twttr?: { widgets?: { load: (element?: HTMLElement) => void } };
  }
}

const ACCOUNTS = [
  { name: 'Reuters', handle: 'Reuters', note: 'Wire service' },
  { name: 'Associated Press', handle: 'AP', note: 'Wire service' },
  { name: 'BBC World', handle: 'BBCWorld', note: 'Public broadcaster' },
  { name: 'Al Jazeera English', handle: 'AJEnglish', note: 'International desk' },
  { name: 'The Guardian', handle: 'guardian', note: 'World news' },
  { name: 'DW News', handle: 'dwnews', note: 'Germany / Europe' },
  { name: 'France 24 English', handle: 'France24_en', note: 'France / world' },
  { name: 'The Hindu', handle: 'the_hindu', note: 'India' },
  { name: 'Mint', handle: 'livemint', note: 'India / business' },
  { name: 'NDTV', handle: 'ndtv', note: 'India' },
  { name: 'The Jerusalem Post', handle: 'Jerusalem_Post', note: 'Middle East' },
  { name: 'South China Morning Post', handle: 'SCMPNews', note: 'Asia' },
];

const WIDGET_SCRIPT = 'x-widgets';

export const XDeskPage: React.FC = () => {
  const [enabled, setEnabled] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) return;
    const existing = document.getElementById(WIDGET_SCRIPT);
    if (existing) {
      window.twttr?.widgets?.load(gridRef.current || undefined);
      return;
    }
    const script = document.createElement('script');
    script.id = WIDGET_SCRIPT;
    script.src = 'https://platform.twitter.com/widgets.js';
    script.async = true;
    script.charset = 'utf-8';
    script.onload = () => window.twttr?.widgets?.load(gridRef.current || undefined);
    document.body.appendChild(script);
  }, [enabled]);

  return (
    <PageShell
      kicker="Social desk"
      title="X desk"
      standfirst="Live timelines from a curated set of newsroom accounts, shown through X’s official embed. This is a display desk: posts are not scraped, stored, or ingested into the Atlas event pipeline."
      meta={
        <>
          <span>Official X embed</span>
          <span>Opt-in</span>
          <span>Not ingested</span>
        </>
      }
      documentTitle="X desk — Globe News Atlas"
    >
      <section className="x-desk-intro">
        <div className="x-desk-intro__copy">
          <h2>
            <MessageSquare size={18} aria-hidden="true" /> Newsroom timelines, on X’s terms
          </h2>
          <p>
            X no longer offers a free read API. The legal, no-cost way to show X content is
            X’s own embedded timeline: the posts are served by X, attributed to the publisher,
            and remain subject to X’s terms and privacy policy. The Atlas does not copy,
            scrape or resell X posts.
          </p>
          <p className="x-desk-intro__note">
            <ShieldCheck size={15} aria-hidden="true" />
            Loading the timelines connects this page to X and may set X cookies. The map,
            dossiers, account area and editions never load X widgets.
          </p>
        </div>
        <div className="x-desk-intro__actions">
          {!enabled ? (
            <button type="button" className="x-desk-load" onClick={() => setEnabled(true)}>
              Load X timelines
            </button>
          ) : (
            <span className="x-desk-loaded" role="status">
              X timelines loaded
            </span>
          )}
          <a
            className="x-desk-privacy-link"
            href="https://x.com/en/privacy"
            target="_blank"
            rel="noreferrer"
          >
            X privacy policy <ExternalLink size={12} aria-hidden="true" />
          </a>
        </div>
      </section>

      {enabled ? (
        <div className="x-desk-grid" ref={gridRef}>
          {ACCOUNTS.map((account) => (
            <article className="x-desk-card" key={account.handle}>
              <header className="x-desk-card__head">
                <div>
                  <strong>{account.name}</strong>
                  <span>@{account.handle}</span>
                </div>
                <em>{account.note}</em>
              </header>
              <a
                className="twitter-timeline"
                data-theme="light"
                data-dnt="true"
                data-height="420"
                data-chrome="noheader nofooter noborders"
                href={`https://x.com/${account.handle}`}
              >
                Posts by {account.name}
              </a>
            </article>
          ))}
        </div>
      ) : (
        <div className="x-desk-consent">
          <p>
            The desk is intentionally opt-in. Nothing from X loads until you press the button
            above.
          </p>
        </div>
      )}

      <p className="x-desk-footnote">
        This is a curated social reading desk, not a full X firehose. The Atlas event
        pipeline remains independent and uses open news sources, with X posts shown only as
        live embeds.
      </p>
    </PageShell>
  );
};
