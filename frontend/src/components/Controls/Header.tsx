import React from 'react';
import { Globe as GlobeIcon, Search, Sun, Moon, List, Languages } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { UserMenu } from './UserMenu';
import { EditionsMenu } from './EditionsMenu';
import './Controls.css';

interface HeaderProps {
  onOpenSearch: () => void;
  isDark: boolean;
  onToggleTheme: () => void;
  viewMode: 'globe' | 'flat' | 'list';
  onChangeViewMode: (mode: 'globe' | 'flat' | 'list') => void;
  snapshotLabel?: string;
  snapshotTone?: 'live' | 'delayed' | 'stale';
  snapshotTitle?: string;
  onRefreshSnapshot?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenSearch,
  isDark,
  onToggleTheme,
  viewMode,
  onChangeViewMode,
  snapshotLabel,
  snapshotTone = 'live',
  snapshotTitle,
  onRefreshSnapshot,
}) => {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language.split('-')[0] || 'en';
  const shortcut = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.userAgent)
    ? '⌘K'
    : 'Ctrl K';

  const handleLangChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    i18n.changeLanguage(e.target.value);
  };

  return (
    <header className="atlas-header">
      <div className="atlas-header__brand">
        <div className="atlas-header__logo">
          <GlobeIcon size={22} className="logo-icon" />
        </div>
        <div>
          <h1 className="atlas-header__title">{t('app_title')}</h1>
          <div className="atlas-header__meta">
            <p className="atlas-header__subtitle">{t('app_subtitle')}</p>
            {snapshotLabel && (
              <button
                type="button"
                className={`atlas-snapshot atlas-snapshot--${snapshotTone}`}
                onClick={onRefreshSnapshot}
                title={snapshotTitle || snapshotLabel}
                aria-label={`${snapshotLabel}. ${t('refresh_snapshot')}`}
              >
                <span className="atlas-snapshot__dot" aria-hidden="true" />
                <span className="atlas-snapshot__label">{snapshotLabel}</span>
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="atlas-header__actions">
        <button
          type="button"
          className="control-btn control-btn--search"
          onClick={onOpenSearch}
          aria-label={`${t('search_placeholder')} ${shortcut}`}
          aria-keyshortcuts="Control+K Meta+K"
        >
          <Search size={15} />
          <span className="search-text-hint">{t('search_placeholder')}</span>
          <kbd className="kbd-shortcut" aria-hidden="true">{shortcut}</kbd>
        </button>

        <div className="view-mode-toggle" role="group" aria-label={t('view_mode')}>
          <button
            type="button"
            className={`view-btn ${viewMode === 'globe' ? 'view-btn--active' : ''}`}
            onClick={() => onChangeViewMode('globe')}
            aria-label={t('globe_3d')}
            aria-pressed={viewMode === 'globe'}
            title={t('globe_3d')}
          >
            <GlobeIcon size={15} />
          </button>
          <button
            type="button"
            className={`view-btn ${viewMode === 'list' ? 'view-btn--active' : ''}`}
            onClick={() => onChangeViewMode('list')}
            aria-label={t('list_view')}
            aria-pressed={viewMode === 'list'}
            title={t('list_view')}
          >
            <List size={15} />
          </button>
        </div>

        <EditionsMenu />

        <div className="lang-selector-wrapper">
          <Languages size={14} className="lang-icon" aria-hidden="true" />
          <select
            className="lang-select"
            value={language}
            onChange={handleLangChange}
            aria-label={t('select_language')}
          >
            <option value="en">EN</option>
            <option value="hi">HI</option>
            <option value="es">ES</option>
          </select>
        </div>

        <button
          type="button"
          className="control-btn control-btn--icon"
          onClick={onToggleTheme}
          aria-label={isDark ? t('switch_light') : t('switch_dark')}
          title={isDark ? t('switch_light') : t('switch_dark')}
        >
          {isDark ? <Sun size={17} /> : <Moon size={17} />}
        </button>

        <UserMenu />
      </div>
    </header>
  );
};
