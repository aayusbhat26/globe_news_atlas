import React, { useEffect, useState } from 'react';
import { ArrowLeft, Globe, Moon, Sun } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';
import { fetchSnapshot } from '../../services/api';
import type { SnapshotEvent } from '../../types/snapshot';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import './Auth.css';

interface AuthLayoutProps {
  children: React.ReactNode;
}

interface EditionHeadlines {
  events: SnapshotEvent[];
  total: number | null;
}

const formatEditionDate = () =>
  new Intl.DateTimeFormat('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date());

export const AuthMasthead: React.FC = () => {
  const { isDark, toggleTheme } = useTheme();
  return (
    <header className="auth-masthead">
      <button type="button" className="auth-brand" onClick={() => navigate('/')}>
        <span className="auth-brand__mark" aria-hidden="true">
          <Globe size={21} strokeWidth={1.6} />
        </span>
        <span className="auth-brand__words">
          <strong>Globe News Atlas</strong>
          <small>Reader accounts</small>
        </span>
      </button>
      <div className="auth-masthead__actions">
        <button
          type="button"
          className="auth-quiet-link"
          onClick={() => navigate('/')}
          aria-label="Return to the atlas"
        >
          <ArrowLeft size={14} aria-hidden="true" />
          <span>Return to the atlas</span>
        </button>
        <button
          type="button"
          className="auth-theme-toggle"
          onClick={toggleTheme}
          aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
          title={isDark ? 'Light theme' : 'Dark theme'}
        >
          {isDark ? <Sun size={17} /> : <Moon size={17} />}
        </button>
      </div>
    </header>
  );
};

const OrbitIllustration: React.FC = () => (
  <svg
    className="auth-orbit"
    viewBox="0 0 640 640"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <circle cx="320" cy="320" r="238" stroke="currentColor" strokeWidth="1" />
    <ellipse cx="320" cy="320" rx="238" ry="86" stroke="currentColor" strokeWidth="0.8" />
    <ellipse cx="320" cy="320" rx="238" ry="164" stroke="currentColor" strokeWidth="0.6" />
    <ellipse cx="320" cy="320" rx="90" ry="238" stroke="currentColor" strokeWidth="0.8" />
    <ellipse cx="320" cy="320" rx="176" ry="238" stroke="currentColor" strokeWidth="0.6" />
    <path d="M82 320h476M320 82v476" stroke="currentColor" strokeWidth="0.6" />
    <path d="M128 208c56 21 126 32 192 32s136-11 192-32" stroke="currentColor" strokeWidth="0.6" />
    <path d="M128 432c56-21 126-32 192-32s136 11 192 32" stroke="currentColor" strokeWidth="0.6" />
    <circle cx="452" cy="196" r="4.5" fill="currentColor" />
    <circle cx="196" cy="414" r="3" fill="currentColor" />
    <circle cx="512" cy="356" r="2.4" fill="currentColor" />
    <path d="M452 196 512 356" stroke="currentColor" strokeWidth="0.7" strokeDasharray="3 5" />
  </svg>
);

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  const [edition, setEdition] = useState<EditionHeadlines>({ events: [], total: null });
  const [loadingEdition, setLoadingEdition] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    fetchSnapshot('24h')
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        const headlines = (snapshot.events || [])
          .filter((event) => Boolean(event.t))
          .slice(0, 3);
        setEdition({
          events: headlines,
          total: snapshot.n?.total ?? snapshot.n?.e ?? null,
        });
      })
      .catch(() => undefined)
      .finally(() => {
        if (!controller.signal.aborted) setLoadingEdition(false);
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="auth-shell">
      <AuthMasthead />
      <main className="auth-frame">
        <section className="auth-edition" aria-labelledby="auth-edition-title">
          <OrbitIllustration />
          <div className="auth-edition__topline">
            <span>Vol. II · Open sources</span>
            <span>{formatEditionDate()}</span>
          </div>

          <div className="auth-edition__lead">
            <p className="auth-kicker">The world, on the record</p>
            <h1 id="auth-edition-title" className="auth-edition__title">
              Keep the world
              <em>in view.</em>
            </h1>
            <p className="auth-edition__deck">
              A considered briefing of protest, conflict, technology and the forces
              moving between them. Save your place, follow the desks that matter, and
              return to a record built from open sources.
            </p>
          </div>

          <div className="auth-dispatches" aria-live="polite">
            <div className="auth-dispatches__head">
              <span>Latest dispatches</span>
              <span className="auth-dispatches__count">
                {edition.total != null
                  ? `${edition.total.toLocaleString()} in the last 24 hours`
                  : 'Current edition'}
              </span>
            </div>
            {loadingEdition && <p className="auth-dispatches__empty">Reading the wire…</p>}
            {!loadingEdition && edition.events.length === 0 && (
              <p className="auth-dispatches__empty">
                The wire is quiet. Open the atlas for the latest record.
              </p>
            )}
            {!loadingEdition && edition.events.length > 0 && (
              <ol className="auth-dispatches__list">
                {edition.events.map((event, index) => (
                  <li key={event.id}>
                    <button
                      type="button"
                      className="auth-dispatch"
                      onClick={() => navigate(`/?event=${encodeURIComponent(event.id)}`)}
                    >
                      <span className="auth-dispatch__index">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <span className="auth-dispatch__body">
                        <span className="auth-dispatch__meta">
                          <span>{event.cat.replace(/_/g, ' ')}</span>
                          <span>{event.loc || 'World'}</span>
                          <span>{formatRelativeTime(event.at)}</span>
                        </span>
                        <span className="auth-dispatch__title">{event.t}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <p className="auth-edition__foot">
            Reporting from open sources. Built for readers, not algorithms.
          </p>
        </section>

        <section className="auth-panel">{children}</section>
      </main>
    </div>
  );
};
