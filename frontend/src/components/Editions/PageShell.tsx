import React, { useEffect } from 'react';
import { ArrowLeft, Globe, Moon, Sun, UserRound } from 'lucide-react';
import { useAuth } from '../../auth/AuthContext';
import { useTheme } from '../../hooks/useTheme';
import { navigate } from '../../router';
import './Pages.css';

interface PageShellProps {
  title: string;
  kicker: string;
  standfirst?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  width?: 'wide' | 'narrow';
  documentTitle?: string;
}

export const PageShell: React.FC<PageShellProps> = ({
  title,
  kicker,
  standfirst,
  meta,
  actions,
  children,
  width = 'wide',
  documentTitle,
}) => {
  const { isDark, toggleTheme } = useTheme();
  const auth = useAuth();

  useEffect(() => {
    document.title = documentTitle || `${title} — Globe News Atlas`;
  }, [documentTitle, title]);

  return (
    <div className="page-shell">
      <header className="page-topbar">
        <button type="button" className="page-brand" onClick={() => navigate('/')}>
          <Globe size={20} strokeWidth={1.7} aria-hidden="true" />
          <span>
            <strong>Globe News Atlas</strong>
            <small>Open-source world desk</small>
          </span>
        </button>

        <nav className="page-nav" aria-label="Editions">
          <button type="button" onClick={() => navigate('/')}>
            <ArrowLeft size={13} aria-hidden="true" />
            Atlas
          </button>
          <button type="button" onClick={() => navigate('/watchline')}>
            Watchline
          </button>
          <button type="button" onClick={() => navigate('/storylines')}>
            Storylines
          </button>
          <button type="button" onClick={() => navigate('/rewind')}>
            Rewind
          </button>
          <button type="button" onClick={() => navigate('/thin-file')}>
            Thin File
          </button>
          <button type="button" onClick={() => navigate('/x-desk')}>
            X Desk
          </button>
        </nav>

        <div className="page-topbar__actions">
          <button
            type="button"
            className="page-icon-btn"
            onClick={toggleTheme}
            aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
            title={isDark ? 'Light theme' : 'Dark theme'}
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          {auth.loading ? null : auth.user ? (
            <button
              type="button"
              className="page-account-btn"
              onClick={() => navigate('/account')}
              title={auth.user.display_name}
            >
              <UserRound size={14} aria-hidden="true" />
              <span>{auth.user.display_name.split(' ')[0]}</span>
            </button>
          ) : (
            <button
              type="button"
              className="page-account-btn"
              onClick={() =>
                navigate(`/login?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`)
              }
            >
              Sign in
            </button>
          )}
        </div>
      </header>

      <main className={`page-main${width === 'narrow' ? ' page-main--narrow' : ''}`}>
        <header className="page-header">
          <div className="page-header__copy">
            <span className="page-kicker">{kicker}</span>
            <h1 className="page-title">{title}</h1>
            {standfirst && <p className="page-standfirst">{standfirst}</p>}
            {meta && <div className="page-meta">{meta}</div>}
          </div>
          {actions && <div className="page-header__actions">{actions}</div>}
        </header>
        {children}
      </main>

      <footer className="page-foot">
        <span>Globe News Atlas · Open sources</span>
        <nav aria-label="Editions footer">
          <button type="button" onClick={() => navigate('/watchline')}>Watchline</button>
          <button type="button" onClick={() => navigate('/storylines')}>Storylines</button>
          <button type="button" onClick={() => navigate('/thin-file')}>Thin File</button>
          <button type="button" onClick={() => navigate('/rewind')}>Rewind</button>
          <button type="button" onClick={() => navigate('/x-desk')}>X Desk</button>
          <button type="button" onClick={() => navigate('/')}>Atlas</button>
        </nav>
      </footer>
    </div>
  );
};
