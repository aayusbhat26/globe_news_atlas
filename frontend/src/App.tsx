import React, { lazy, Suspense, useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSnapshot } from './hooks/useSnapshot';
import { useTheme, useWebGLSupport, checkWebGL } from './hooks/useTheme';
import type { SnapshotEvent } from './types/snapshot';
import type { CountryFocus } from './types/country';

import { Header } from './components/Controls/Header';
import { CategoryFilter } from './components/Controls/CategoryFilter';
import { FloatingDock } from './components/Controls/TimeWindow';
import { SearchModal } from './components/Controls/SearchModal';
const GlobeView = lazy(() =>
  import('./components/Globe/GlobeView').then((module) => ({ default: module.GlobeView })),
);
import { HoverCard } from './components/Cards/HoverCard';
import { LocationDispatch } from './components/Cards/LocationDispatch';
import { CountryBrief } from './components/Cards/CountryBrief';
import { DetailModal } from './components/Cards/DetailModal';
import { ReportProblemModal } from './components/Feedback/ReportProblemModal';
import { ListView } from './components/Fallback/ListView';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AuthPage, type AuthMode } from './components/Auth/AuthPage';
import { AccountPage } from './components/Auth/AccountPage';
import { LegalPage } from './components/Auth/LegalPage';
import { WatchlinePage } from './components/Editions/WatchlinePage';
import { StorylinesPage } from './components/Editions/StorylinesPage';
import { ThinFilePage } from './components/Editions/ThinFilePage';
import { RewindPage } from './components/Editions/RewindPage';
import { XDeskPage } from './components/Editions/XDeskPage';
import { EventPage } from './components/Editions/EventPage';
import { EmbedPage } from './components/Editions/EmbedPage';
import { PageShell } from './components/Editions/PageShell';
import { decodePathSegment, navigate, usePathname } from './router';
import { formatAgeShort, formatRelativeTime } from './utils/time';

import './i18n';
import './App.css';

const AUTH_ROUTES: Record<string, AuthMode> = {
  '/login': 'login',
  '/signup': 'signup',
  '/forgot-password': 'forgot',
  '/reset-password': 'reset',
  '/verify-email': 'verify',
};

const AtlasApp: React.FC = () => {
  const [timeWindow, setTimeWindow] = useState<'1h' | '24h' | '7d' | '30d'>('24h');
  const [spectrumFilter, setSpectrumFilter] = useState<'all' | 'left' | 'centre' | 'right'>('all');
  const [activeCategory, setActiveCategory] = useState<string>('all');

  const [viewMode, setViewMode] = useState<'globe' | 'flat' | 'list'>(() => (checkWebGL() ? 'globe' : 'list'));
  const [hoveredEvent, setHoveredEvent] = useState<SnapshotEvent | null>(null);
  const [locationGroup, setLocationGroup] = useState<SnapshotEvent[] | null>(null);
  const [countryFocus, setCountryFocus] = useState<CountryFocus | null>(null);
  const [activeEventId, setActiveEventId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get('event')
  );
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);
  const [reportEventId, setReportEventId] = useState<string | null>(null);
  const [targetCoords, setTargetCoords] = useState<{ lat: number; lng: number; altitude?: number } | null>(null);
  const [webglError, setWebglError] = useState<boolean>(false);

  const { t } = useTranslation();
  const { isDark, toggleTheme } = useTheme();
  const hasWebGL = useWebGLSupport();
  const {
    data: snapshot,
    isLoading,
    error,
    lastUpdated,
    streamError,
    isOffline,
    isStale,
    refresh,
  } = useSnapshot(timeWindow);
  const hasNoData = snapshot?.available === false;
  const [clock, setClock] = useState<number>(() => Date.now());

  // The age label needs to move even when no new snapshot arrives.
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const snapshotAt = snapshot?.ts || lastUpdated?.toISOString() || null;
  const snapshotAge = snapshotAt && clock ? formatRelativeTime(snapshotAt) : null;
  const snapshotLabel = snapshotAt
    ? t('snapshot_age', { time: snapshotAge })
    : t('snapshot_waiting');  const snapshotTone = isOffline || isStale ? 'stale' : streamError ? 'delayed' : 'live';
  const snapshotTitle = [
    snapshotAt ? new Date(snapshotAt).toLocaleString() : null,
    isOffline ? t('offline_banner') : null,
    streamError ? t('live_updates_offline') : null,
    error ? error : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const showDataBanner = Boolean(
    isOffline || error || hasNoData || (isLoading && !snapshot) || (streamError && !error),
  );
  const bannerTone = isOffline
    ? 'offline'
    : error
      ? isStale
        ? 'stale'
        : 'error'
      : hasNoData
        ? 'empty'
        : 'notice';

  useEffect(() => {
    document.title = 'Globe News Atlas — World events and coverage';
  }, []);

  // Automatic fallback to List view if WebGL is unavailable on device or errored
  useEffect(() => {
    if ((!hasWebGL || webglError) && viewMode === 'globe') {
      setViewMode('list');
    }
  }, [hasWebGL, webglError, viewMode]);

  useEffect(() => {
    setHoveredEvent(null);
    setLocationGroup(null);
  }, [timeWindow, activeCategory, spectrumFilter]);

  useEffect(() => {
    setCountryFocus(null);
  }, [activeCategory, spectrumFilter]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (activeEventId) {
      params.set('event', activeEventId);
    } else {
      params.delete('event');
    }
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
    );
  }, [activeEventId]);

  // Keyboard shortcut: Cmd+K / Ctrl+K opens search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Filter events based on the selected category and political spectrum
  const filteredEvents = useMemo(() => {
    if (!snapshot?.events) return [];

    return snapshot.events.filter((e) => {
      if (activeCategory !== 'all' && e.cat !== activeCategory) return false;

      if (spectrumFilter !== 'all') {
        const campCount = e.sp?.[spectrumFilter] || 0;
        if (campCount === 0) return false;
      }

      return true;
    });
  }, [snapshot, activeCategory, spectrumFilter]);

  const activeArcs = useMemo(() => {
    return snapshot?.arcs || [];
  }, [snapshot]);

  const selectCategory = (category: string) => {
    setActiveCategory((current) => {
      if (category === 'all') return 'all';
      return current === category ? 'all' : category;
    });
  };

  const handleSelectFromSearch = (event: SnapshotEvent) => {
    setLocationGroup(null);
    setCountryFocus(null);
    setTargetCoords({ lat: event.lat, lng: event.lng });
    setActiveEventId(event.id);
  };

  const handleLocationSelect = (eventId: string) => {
    setLocationGroup(null);
    setCountryFocus(null);
    setActiveEventId(eventId);
  };

  const handleCountryClick = (country: CountryFocus) => {
    if (countryFocus?.name === country.name) {
      setCountryFocus(null);
      return;
    }
    setHoveredEvent(null);
    setLocationGroup(null);
    setCountryFocus(country);
    setTargetCoords({ lat: country.lat, lng: country.lng, altitude: 0.92 });
  };

  return (
    <ErrorBoundary>
      <div className="app-root">
        {/* Top Header */}
        <Header
          onOpenSearch={() => setIsSearchOpen(true)}
          isDark={isDark}
          onToggleTheme={toggleTheme}
          viewMode={viewMode}
          onChangeViewMode={(mode) => {
            if (mode === 'globe' && webglError) {
              setWebglError(false);
            }
            if (mode !== 'globe') {
              setCountryFocus(null);
            }
            setViewMode(mode);
          }}
          snapshotLabel={snapshotLabel}
          snapshotTone={snapshotTone}
          snapshotTitle={snapshotTitle}
          onRefreshSnapshot={refresh}
        />

        {/* Category index */}
        <CategoryFilter
          activeCategory={activeCategory}
          onSelectCategory={selectCategory}
        />

        {/* Data freshness, connectivity and live-stream status */}
        {showDataBanner && (
          <div
            className={`data-banner data-banner--${bannerTone}`}
            role={bannerTone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
          >
            {isOffline && <span>{t('offline_banner')}</span>}
            {!isOffline && error && snapshot && (
              <span>
                {t('stale_data_banner', {
                  time: formatAgeShort(snapshot.ts || lastUpdated?.toISOString()),
                })}
                {error ? ` (${error})` : ''}
              </span>
            )}
            {!isOffline && error && !snapshot && (
              <span>
                Live API unavailable: {error}
              </span>
            )}
            {!isOffline && !error && streamError && (
              <span>{t('live_updates_offline')}</span>
            )}
            {isLoading && !snapshot && !error && !isOffline && (
              <span>Loading live event data...</span>
            )}
            {hasNoData && !error && !isOffline && (
              <span>
                No pipeline snapshot has been generated yet. Run the ingestion pipeline to populate the globe.
              </span>
            )}
            {(error || hasNoData || isOffline) && !isLoading && (
              <button className="data-banner__btn" onClick={refresh}>
                {t('retry')}
              </button>
            )}
          </div>
        )}

        {/* WebGL context fallback notice */}
        {webglError && (
          <div className="webgl-banner">
            <span>Browser WebGL context was reset. Switched to the table view.</span>
            <button
              className="webgl-banner__btn"
              onClick={() => {
                setWebglError(false);
                setViewMode('globe');
              }}
            >
              Retry globe
            </button>
          </div>
        )}

        {/* Main View: 3D Globe or Accessible List */}
        {viewMode === 'globe' && !webglError && hasWebGL ? (
          <Suspense
            fallback={
              <div className="view-loading" role="status">
                <span>{t('preparing_globe')}</span>
              </div>
            }
          >
            <GlobeView
              events={filteredEvents}
              arcs={activeArcs}
              onEventHover={(ev) => setHoveredEvent(ev)}
              onEventClick={(id) => {
                setCountryFocus(null);
                setActiveEventId(id);
              }}
              onLocationClick={(group) => {
                setCountryFocus(null);
                setLocationGroup(group);
              }}
              onCountryClick={handleCountryClick}
              activeCountry={countryFocus?.name || null}
              targetCoords={targetCoords}
              isDark={isDark}
              insetTop={108}
              onWebGLError={() => {
                setWebglError(true);
                setViewMode('list');
              }}
              onWebGLRestored={() => setWebglError(false)}
            />
          </Suspense>
        ) : (
          <ListView
            events={filteredEvents}
            onEventClick={(id) => setActiveEventId(id)}
          />
        )}

        {/* Dot hover preview (suppressed while a desk is open) */}
        {hoveredEvent && !activeEventId && !locationGroup && !countryFocus && (
          <HoverCard
            event={hoveredEvent}
            onClose={() => setHoveredEvent(null)}
            onClick={(id) => setActiveEventId(id)}
          />
        )}

        {locationGroup && !activeEventId && (
          <LocationDispatch
            events={locationGroup}
            onSelect={handleLocationSelect}
            onClose={() => setLocationGroup(null)}
          />
        )}

        {countryFocus && !activeEventId && !locationGroup && (
          <CountryBrief
            key={countryFocus.name}
            country={countryFocus}
            timeWindow={timeWindow}
            dataVersion={snapshot?.ts || null}
            onChangeWindow={setTimeWindow}
            onSelectEvent={(id) => setActiveEventId(id)}
            onClose={() => setCountryFocus(null)}
          />
        )}

        {/* Floating Bottom Control Dock */}
        <FloatingDock
          timeWindow={timeWindow}
          onChangeTimeWindow={setTimeWindow}
          spectrumFilter={spectrumFilter}
          onChangeSpectrumFilter={setSpectrumFilter}
          eventCount={filteredEvents.length}
          matchingTotal={snapshot?.n.e ?? snapshot?.events.length ?? filteredEvents.length}
          windowTotal={snapshot?.n.total ?? snapshot?.n.e ?? filteredEvents.length}
          windowCapped={Boolean(snapshot?.n.capped)}
          filtersActive={activeCategory !== 'all' || spectrumFilter !== 'all'}
        />

        {/* Full 90% Viewport Detail Modal */}
        {activeEventId && (
          <DetailModal
            eventId={activeEventId}
            onClose={() => setActiveEventId(null)}
            onReportProblem={(id) => setReportEventId(id)}
          />
        )}

        {/* Search Modal */}
        <SearchModal
          isOpen={isSearchOpen}
          onClose={() => setIsSearchOpen(false)}
          events={snapshot?.events || []}
          onSelectEvent={handleSelectFromSearch}
        />

        {/* Report a Problem Modal */}
        <ReportProblemModal
          eventId={reportEventId}
          isOpen={Boolean(reportEventId)}
          onClose={() => setReportEventId(null)}
        />
      </div>
    </ErrorBoundary>
  );
};

const NotFoundPage: React.FC = () => (
  <PageShell
    kicker="404"
    title="This page is not on the atlas"
    width="narrow"
    documentTitle="Page not found — Globe News Atlas"
  >
    <div className="page-empty">
      <h2>The address does not match an Atlas edition or dispatch.</h2>
      <p>Check the link, or return to the globe and search the archive.</p>
      <button type="button" className="page-primary" onClick={() => navigate('/')}>
        Back to the Atlas
      </button>
    </div>
  </PageShell>
);

const normalisePath = (raw: string): string => {
  if (!raw || raw === '/') return '/';
  const trimmed = raw.replace(/\/+$/, '');
  return trimmed || '/';
};

export const App: React.FC = () => {
  const rawPathname = usePathname();
  const pathname = normalisePath(rawPathname);
  const authMode = AUTH_ROUTES[pathname];
  const embedMatch = pathname.match(/^\/embed\/event\/([^/]+)$/);
  const eventMatch = pathname.match(/^\/event\/([^/]+)$/);

  if (authMode) {
    // Each auth mode owns its form, notices and one-time token state.
    return <AuthPage key={authMode} mode={authMode} />;
  }
  if (pathname === '/account') {
    return <AccountPage />;
  }
  if (pathname === '/terms' || pathname === '/privacy') {
    return <LegalPage kind={pathname === '/terms' ? 'terms' : 'privacy'} />;
  }
  if (pathname === '/watchline') {
    return <WatchlinePage />;
  }
  if (pathname === '/storylines') {
    return <StorylinesPage />;
  }
  if (pathname === '/thin-file') {
    return <ThinFilePage />;
  }
  if (pathname === '/rewind') {
    return <RewindPage />;
  }
  if (pathname === '/x-desk') {
    return <XDeskPage />;
  }
  if (embedMatch) {
    return <EmbedPage eventId={decodePathSegment(embedMatch[1])} />;
  }
  if (eventMatch) {
    return <EventPage eventId={decodePathSegment(eventMatch[1])} />;
  }
  if (pathname === '/') {
    return <AtlasApp />;
  }
  return <NotFoundPage />;
};

export default App;
