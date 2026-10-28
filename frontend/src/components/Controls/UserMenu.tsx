import React, { useEffect, useRef, useState } from 'react';
import { Bookmark, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../auth/AuthContext';
import { initials } from '../../utils/auth';
import { navigate } from '../../router';

export const UserMenu: React.FC = () => {
  const auth = useAuth();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    const first = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (auth.loading) {
    return <span className="user-menu-skeleton" aria-hidden="true" />;
  }

  if (!auth.user) {
    const next = `${window.location.pathname}${window.location.search}`;
    return (
      <button
        type="button"
        className="control-btn user-signin"
        onClick={() => navigate(`/login?next=${encodeURIComponent(next)}`)}
      >
        <UserRound size={15} aria-hidden="true" />
        <span className="user-signin__label">{t('sign_in')}</span>
      </button>
    );
  }

  const user = auth.user;
  const handleSignOut = async () => {
    setSigningOut(true);
    setSignOutError(null);
    try {
      await auth.signOut();
      setOpen(false);
      navigate('/');
    } catch (error) {
      // Keep the session and the menu open; the item doubles as the retry.
      setSignOutError(
        error instanceof Error
          ? error.message
          : 'Could not reach the server. Your session is still active.',
      );
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <div className="user-menu">
      <button
        type="button"
        ref={triggerRef}
        className={`user-menu__trigger${open ? ' is-open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="user-menu-popover"
        onClick={() => setOpen((current) => !current)}
        title={user.display_name}
      >
        <span className="user-avatar" aria-hidden="true">
          {initials(user.display_name, user.email)}
        </span>
        <span className="sr-only">{t('account_menu_for', { name: user.display_name })}</span>
      </button>

      {open && (
        <div className="user-menu__popover" id="user-menu-popover" role="menu" ref={menuRef}>
          <div className="user-menu__identity">
            <span className="user-menu__name">{user.display_name}</span>
            <span className="user-menu__email">{user.email}</span>
            <span className="user-menu__status">
              {user.email_verified ? t('confirmed_reader') : t('email_unconfirmed')}
              {user.totp_enabled ? ` · ${t('two_factor_on')}` : ''}
            </span>
          </div>
          <div className="user-menu__rule" />
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => {
              setOpen(false);
              navigate('/watchline');
            }}
          >
            <Bookmark size={15} aria-hidden="true" />
            {t('my_watchline')}
          </button>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => {
              setOpen(false);
              navigate('/account');
            }}
          >
            <ShieldCheck size={15} aria-hidden="true" />
            {t('account_security')}
          </button>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={handleSignOut}
            disabled={signingOut}
          >
            <LogOut size={15} aria-hidden="true" />
            {signingOut ? t('signing_out') : signOutError ? t('sign_out_retry') : t('sign_out')}
          </button>
          {signOutError && (
            <p className="user-menu__error" role="alert" aria-live="assertive">
              {t('sign_out_failed', { error: signOutError })}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
