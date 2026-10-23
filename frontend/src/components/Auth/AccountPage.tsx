import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Clock3,
  Copy,
  Download,
  KeyRound,
  Link2,
  Loader2,
  LogOut,
  MailCheck,
  Monitor,
  ShieldCheck,
  Smartphone,
  Unlink,
  UserRound,
} from 'lucide-react';
import { AuthMasthead } from './AuthLayout';
import { PasswordField, PasswordStrength } from './AuthFields';
import { useAuth } from '../../auth/AuthContext';
import {
  changePassword,
  deleteAccount,
  disableTwoFactor,
  enableTwoFactor,
  fetchActivity,
  fetchSessions,
  googleConnectUrl,
  regenerateRecoveryCodes,
  resendVerification,
  revokeOtherSessions,
  revokeSession,
  setupTwoFactor,
  unlinkGoogle,
  updateProfile,
} from '../../services/auth';
import { ApiError } from '../../services/api';
import type { SecurityEvent, SessionInfo, TotpSetup } from '../../types/auth';
import {
  assessPassword,
  copyToClipboard,
  describeAuthEvent,
  describeAuthMethod,
  eventMethod,
  formatAccountDate,
  formatAccountDateTime,
  initials,
} from '../../utils/auth';
import { formatRelativeTime } from '../../utils/time';
import { navigate } from '../../router';
import './Account.css';

const errorMessage = (error: unknown): string => {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Try again.';
};

const StatusMessage: React.FC<{
  tone: 'error' | 'success' | 'info';
  children: React.ReactNode;
}> = ({ tone, children }) => (
  <div className={`account-status account-status--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    {children}
  </div>
);

const AccountSection: React.FC<{
  id: string;
  index: string;
  title: string;
  description: string;
  children: React.ReactNode;
}> = ({ id, index, title, description, children }) => (
  <section className="account-section" id={id} aria-labelledby={`${id}-title`}>
    <div className="account-section__head">
      <span className="account-section__index" aria-hidden="true">
        {index}
      </span>
      <div>
        <h2 id={`${id}-title`} className="account-section__title">
          {title}
        </h2>
        <p className="account-section__description">{description}</p>
      </div>
    </div>
    <div className="account-section__body">{children}</div>
  </section>
);

const RecoveryCodes: React.FC<{
  codes: string[];
  onDone?: () => void;
}> = ({ codes, onDone }) => {
  const [copied, setCopied] = useState(false);
  const copyCodes = async () => {
    const success = await copyToClipboard(codes.join('\n'));
    setCopied(success);
    if (success) window.setTimeout(() => setCopied(false), 2000);
  };
  const download = () => {
    const blob = new Blob(
      [
        'Globe News Atlas — recovery codes\n',
        'Each code can be used once. Store these somewhere safe.\n\n',
        codes.join('\n'),
        '\n',
      ],
      { type: 'text/plain;charset=utf-8' },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'globe-news-atlas-recovery-codes.txt';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="recovery-codes">
      <div className="recovery-codes__head">
        <div>
          <h3>Recovery codes</h3>
          <p>Shown once. Each code signs you in one time if the authenticator is lost.</p>
        </div>
        <div className="recovery-codes__actions">
          <button type="button" className="account-text-button" onClick={copyCodes}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" className="account-text-button" onClick={download}>
            <Download size={14} />
            Download
          </button>
        </div>
      </div>
      <ol className="recovery-codes__grid">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      {onDone && (
        <button type="button" className="account-quiet-button" onClick={onDone}>
          I have saved these codes
        </button>
      )}
    </div>
  );
};

const SessionRow: React.FC<{
  session: SessionInfo;
  busy: boolean;
  onRevoke: (id: string) => void;
}> = ({ session, busy, onRevoke }) => {
  const mobile = /Android|iPhone|iPad/i.test(session.device);
  return (
    <li className="session-row">
      <span className="session-row__icon" aria-hidden="true">
        {mobile ? <Smartphone size={18} /> : <Monitor size={18} />}
      </span>
      <div className="session-row__body">
        <div className="session-row__title">
          <span>{session.device}</span>
          {session.current && <span className="account-badge account-badge--current">This device</span>}
        </div>
        <p className="session-row__meta">
          {describeAuthMethod(session.auth_method)}
          {session.ip ? ` · ${session.ip}` : ''} · Active {formatRelativeTime(session.last_seen_at)}
        </p>
        <p className="session-row__meta session-row__meta--quiet">
          Opened {formatAccountDate(session.created_at)} · {session.remember ? 'Remembered 30 days' : 'Standard session'}
        </p>
      </div>
      {!session.current && (
        <button
          type="button"
          className="account-text-button account-text-button--danger"
          onClick={() => onRevoke(session.id)}
          disabled={busy}
        >
          Sign out
        </button>
      )}
    </li>
  );
};

const ActivityRow: React.FC<{ event: SecurityEvent }> = ({ event }) => {
  const method = eventMethod(event.metadata);
  return (
    <li className="activity-row">
      <span className="activity-row__dot" aria-hidden="true" />
      <div className="activity-row__body">
        <span className="activity-row__title">{describeAuthEvent(event.event)}</span>
        <span className="activity-row__meta">
          {formatAccountDateTime(event.created_at)}
          {method ? ` · ${method.replace(/_/g, ' ')}` : ''}
          {event.ip ? ` · ${event.ip}` : ''}
        </span>
      </div>
    </li>
  );
};

const AccountSkeleton: React.FC = () => (
  <div className="account-shell">
    <AuthMasthead />
    <div className="account-loading" role="status">
      <Loader2 size={18} className="auth-spinner" />
      Opening your reader account…
    </div>
  </div>
);

export const AccountPage: React.FC = () => {
  const auth = useAuth();
  const user = auth.user;
  const minimum = auth.config.password_min_length || 12;

  const [displayName, setDisplayName] = useState('');
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileStatus, setProfileStatus] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [resendBusy, setResendBusy] = useState(false);
  const [resendStatus, setResendStatus] = useState<{ tone: 'error' | 'success' | 'info'; text: string; link?: string } | null>(null);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordCode, setPasswordCode] = useState('');
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordStatus, setPasswordStatus] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);

  const [totpPassword, setTotpPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpSetup, setTotpSetup] = useState<TotpSetup | null>(null);
  const [totpBusy, setTotpBusy] = useState('');
  const [totpStatus, setTotpStatus] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [disablePassword, setDisablePassword] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [regenPassword, setRegenPassword] = useState('');
  const [regenCode, setRegenCode] = useState('');
  const [showDisable, setShowDisable] = useState(false);
  const [showRegen, setShowRegen] = useState(false);

  const [googlePassword, setGooglePassword] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleStatus, setGoogleStatus] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activity, setActivity] = useState<SecurityEvent[]>([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [dataError, setDataError] = useState<string | null>(null);
  const [sessionBusy, setSessionBusy] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<string | null>(null);

  const [showClose, setShowClose] = useState(false);
  const [closePassword, setClosePassword] = useState('');
  const [closeCode, setCloseCode] = useState('');
  const [closeEmail, setCloseEmail] = useState('');
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeStatus, setCloseStatus] = useState<string | null>(null);

  const didRedirect = useRef(false);

  useEffect(() => {
    if (!auth.loading && !auth.user && !didRedirect.current) {
      didRedirect.current = true;
      navigate('/login?next=/account', { replace: true });
    }
  }, [auth.loading, auth.user]);

  useEffect(() => {
    document.title = 'Reader account — Globe News Atlas';
  }, []);

  useEffect(() => {
    if (user) setDisplayName(user.display_name);
  }, [user]);

  const loadSecurityData = useCallback(async () => {
    if (!user) return;
    setDataLoading(true);
    setDataError(null);
    try {
      const [sessionData, activityData] = await Promise.all([fetchSessions(), fetchActivity()]);
      setSessions(sessionData.sessions);
      setActivity(activityData.events);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        await auth.refresh();
        return;
      }
      setDataError(errorMessage(error));
    } finally {
      setDataLoading(false);
    }
  }, [auth, user]);

  useEffect(() => {
    if (user) loadSecurityData();
  }, [user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (auth.loading) return <AccountSkeleton />;
  if (!user) return <AccountSkeleton />;

  const onNavigate = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const saveProfile = async (event: React.FormEvent) => {
    event.preventDefault();
    setProfileStatus(null);
    if (!displayName.trim()) {
      setProfileStatus({ tone: 'error', text: 'Enter a display name.' });
      return;
    }
    setProfileBusy(true);
    try {
      const result = await updateProfile(displayName.trim());
      auth.setUser(result.user);
      setProfileStatus({ tone: 'success', text: result.message });
    } catch (error) {
      setProfileStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setProfileBusy(false);
    }
  };

  const resendEmail = async () => {
    setResendStatus(null);
    setResendBusy(true);
    try {
      const result = await resendVerification();
      setResendStatus({
        tone: 'success',
        text: result.message,
        link: result.dev_verification_link || undefined,
      });
    } catch (error) {
      setResendStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setResendBusy(false);
    }
  };

  const savePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setPasswordStatus(null);
    const assessment = assessPassword(newPassword, minimum, user.email);
    if (assessment.problems.length) {
      setPasswordStatus({ tone: 'error', text: assessment.problems[0] });
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordStatus({ tone: 'error', text: 'The passwords do not match.' });
      return;
    }
    if (!user.has_password && user.totp_enabled && !passwordCode.trim()) {
      setPasswordStatus({ tone: 'error', text: 'Enter your authenticator or recovery code.' });
      return;
    }
    setPasswordBusy(true);
    try {
      const result = await changePassword(currentPassword, newPassword, passwordCode.trim());
      auth.setUser(result.user);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordCode('');
      setPasswordStatus({ tone: 'success', text: result.message });
      await loadSecurityData();
    } catch (error) {
      setPasswordStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setPasswordBusy(false);
    }
  };

  const beginTotp = async () => {
    setTotpStatus(null);
    if (user.has_password && !totpPassword) {
      setTotpStatus({ tone: 'error', text: 'Enter your password to begin.' });
      return;
    }
    setTotpBusy('setup');
    try {
      const result = await setupTwoFactor(totpPassword);
      setTotpSetup(result);
      setTotpCode('');
    } catch (error) {
      setTotpStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setTotpBusy('');
    }
  };

  const activateTotp = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!totpCode.trim()) {
      setTotpStatus({ tone: 'error', text: 'Enter the six-digit code from your app.' });
      return;
    }
    setTotpBusy('enable');
    setTotpStatus(null);
    try {
      const result = await enableTwoFactor(totpCode.trim());
      auth.setUser(result.user);
      setRecoveryCodes(result.recovery_codes);
      setTotpSetup(null);
      setTotpPassword('');
      setTotpCode('');
      setTotpStatus({ tone: 'success', text: 'Two-factor authentication is now on.' });
      await loadSecurityData();
    } catch (error) {
      setTotpStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setTotpBusy('');
    }
  };

  const turnOffTotp = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!disableCode.trim()) {
      setTotpStatus({ tone: 'error', text: 'Enter a current authenticator or recovery code.' });
      return;
    }
    if (user.has_password && !disablePassword) {
      setTotpStatus({ tone: 'error', text: 'Enter your password.' });
      return;
    }
    setTotpBusy('disable');
    setTotpStatus(null);
    try {
      const result = await disableTwoFactor(disablePassword, disableCode.trim());
      auth.setUser(result.user);
      setDisablePassword('');
      setDisableCode('');
      setShowDisable(false);
      setRecoveryCodes(null);
      setTotpStatus({ tone: 'success', text: result.message });
      await loadSecurityData();
    } catch (error) {
      setTotpStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setTotpBusy('');
    }
  };

  const replaceRecoveryCodes = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!regenCode.trim()) {
      setTotpStatus({ tone: 'error', text: 'Enter a current authenticator or recovery code.' });
      return;
    }
    if (user.has_password && !regenPassword) {
      setTotpStatus({ tone: 'error', text: 'Enter your password.' });
      return;
    }
    setTotpBusy('regen');
    setTotpStatus(null);
    try {
      const result = await regenerateRecoveryCodes(regenPassword, regenCode.trim());
      setRecoveryCodes(result.recovery_codes);
      setRegenPassword('');
      setRegenCode('');
      setShowRegen(false);
      setTotpStatus({ tone: 'success', text: 'New recovery codes generated. Old codes no longer work.' });
      await loadSecurityData();
    } catch (error) {
      setTotpStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setTotpBusy('');
    }
  };

  const connectGoogle = async () => {
    setGoogleStatus(null);
    setGoogleBusy(true);
    try {
      const url = await googleConnectUrl();
      window.location.assign(url);
    } catch (error) {
      setGoogleStatus({ tone: 'error', text: errorMessage(error) });
      setGoogleBusy(false);
    }
  };

  const disconnectGoogle = async (event: React.FormEvent) => {
    event.preventDefault();
    setGoogleStatus(null);
    if (!googlePassword) {
      setGoogleStatus({ tone: 'error', text: 'Enter your password to disconnect Google.' });
      return;
    }
    setGoogleBusy(true);
    try {
      const result = await unlinkGoogle(googlePassword);
      auth.setUser(result.user);
      setGooglePassword('');
      setGoogleStatus({ tone: 'success', text: result.message });
      await loadSecurityData();
    } catch (error) {
      setGoogleStatus({ tone: 'error', text: errorMessage(error) });
    } finally {
      setGoogleBusy(false);
    }
  };

  const signOutSession = async (id: string) => {
    setSessionBusy(id);
    setSessionStatus(null);
    try {
      const result = await revokeSession(id);
      setSessionStatus(result.message);
      await loadSecurityData();
    } catch (error) {
      setSessionStatus(errorMessage(error));
    } finally {
      setSessionBusy(null);
    }
  };

  const signOutOtherSessions = async () => {
    setSessionBusy('others');
    setSessionStatus(null);
    try {
      const result = await revokeOtherSessions();
      setSessionStatus(result.message);
      await loadSecurityData();
    } catch (error) {
      setSessionStatus(errorMessage(error));
    } finally {
      setSessionBusy(null);
    }
  };

  const closeAccount = async (event: React.FormEvent) => {
    event.preventDefault();
    setCloseStatus(null);
    if (closeEmail.trim().toLowerCase() !== user.email) {
      setCloseStatus('Type the email address exactly to confirm.');
      return;
    }
    if (user.has_password && !closePassword) {
      setCloseStatus('Enter your password to close the account.');
      return;
    }
    if (!user.has_password && user.totp_enabled && !closeCode.trim()) {
      setCloseStatus('Enter your authenticator or recovery code.');
      return;
    }
    setCloseBusy(true);
    try {
      await deleteAccount(closePassword, closeEmail.trim(), closeCode.trim());
      await auth.refresh();
      auth.notifyAuthChange();
      navigate('/', { replace: true });
    } catch (error) {
      setCloseStatus(errorMessage(error));
    } finally {
      setCloseBusy(false);
    }
  };

  const signOut = async () => {
    await auth.signOut();
    navigate('/', { replace: true });
  };

  return (
    <div className="account-shell">
      <AuthMasthead />
      <main className="account-main">
        <header className="account-hero">
          <div className="account-hero__identity">
            <span className="account-avatar" aria-hidden="true">
              {initials(user.display_name, user.email)}
            </span>
            <div>
              <p className="auth-kicker">Reader account</p>
              <h1 className="account-hero__name">{user.display_name}</h1>
              <div className="account-hero__meta">
                <span>{user.email}</span>
                <span className={`account-badge${user.email_verified ? ' account-badge--ok' : ' account-badge--warn'}`}>
                  {user.email_verified ? 'Confirmed' : 'Unconfirmed'}
                </span>
                <span>Joined {formatAccountDate(user.created_at)}</span>
              </div>
            </div>
          </div>
          <button type="button" className="account-quiet-button account-quiet-button--signout" onClick={signOut}>
            <LogOut size={15} />
            Sign out
          </button>
        </header>

        <div className="account-grid">
          <aside className="account-nav" aria-label="Account sections">
            <p className="account-nav__label">On this page</p>
            {[
              ['profile', 'Profile'],
              ['security', 'Password & sign-in'],
              ['two-factor', 'Two-factor'],
              ['google', 'Google'],
              ['sessions', 'Sessions'],
              ['activity', 'Activity'],
              ['close', 'Close account'],
            ].map(([id, label]) => (
              <button key={id} type="button" onClick={() => onNavigate(id)}>
                {label}
              </button>
            ))}
            <div className="account-nav__foot">
              <ShieldCheck size={14} aria-hidden="true" />
              <span>Reader data stays private. No trackers.</span>
            </div>
          </aside>

          <div className="account-content">
            <AccountSection
              id="profile"
              index="01"
              title="Profile"
              description="The name attached to your reading and account notices."
            >
              {profileStatus && (
                <StatusMessage tone={profileStatus.tone}>{profileStatus.text}</StatusMessage>
              )}
              <form className="account-form" onSubmit={saveProfile} noValidate>
                <div className="account-form__row">
                  <label className="account-field">
                    <span>Display name</span>
                    <input
                      className="auth-input"
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      maxLength={80}
                      autoComplete="name"
                    />
                  </label>
                  <button type="submit" className="account-primary-button" disabled={profileBusy}>
                    {profileBusy ? <Loader2 size={15} className="auth-spinner" /> : <UserRound size={15} />}
                    {profileBusy ? 'Saving…' : 'Save name'}
                  </button>
                </div>
              </form>

              <div className="account-detail-row">
                <div>
                  <span className="account-detail-row__label">Email address</span>
                  <strong>{user.email}</strong>
                  <p>
                    {user.email_verified
                      ? 'Confirmed. Security and sign-in notices go here.'
                      : 'Not confirmed yet. Confirm the address to secure recovery.'}
                  </p>
                  {resendStatus && (
                    <StatusMessage tone={resendStatus.tone}>
                      {resendStatus.text}
                      {resendStatus.link && (
                        <>
                          {' '}
                          <a href={resendStatus.link}>Open confirmation link</a>.
                        </>
                      )}
                    </StatusMessage>
                  )}
                </div>
                {!user.email_verified && (
                  <button
                    type="button"
                    className="account-quiet-button"
                    onClick={resendEmail}
                    disabled={resendBusy}
                  >
                    {resendBusy ? <Loader2 size={14} className="auth-spinner" /> : <MailCheck size={14} />}
                    {resendBusy ? 'Sending…' : 'Send confirmation'}
                  </button>
                )}
              </div>
            </AccountSection>

            <AccountSection
              id="security"
              index="02"
              title="Password"
              description={
                user.has_password
                  ? 'Change the password used to sign in. Other devices are signed out.'
                  : 'Set a password so you can sign in without Google.'
              }
            >
              {passwordStatus && (
                <StatusMessage tone={passwordStatus.tone}>{passwordStatus.text}</StatusMessage>
              )}
              <form className="account-form" onSubmit={savePassword} noValidate>
                {user.has_password && (
                  <PasswordField
                    label="Current password"
                    value={currentPassword}
                    onChange={setCurrentPassword}
                    autoComplete="current-password"
                    placeholder="Your current password"
                  />
                )}
                <div className="account-form__split">
                  <div>
                    <PasswordField
                      label={user.has_password ? 'New password' : 'Password'}
                      value={newPassword}
                      onChange={setNewPassword}
                      autoComplete="new-password"
                      placeholder={`At least ${minimum} characters`}
                    />
                    <PasswordStrength password={newPassword} minimum={minimum} email={user.email} />
                  </div>
                  <PasswordField
                    label="Confirm password"
                    value={confirmPassword}
                    onChange={setConfirmPassword}
                    autoComplete="new-password"
                    placeholder="Repeat the password"
                  />
                </div>
                {!user.has_password && user.totp_enabled && (
                  <label className="account-field">
                    <span>Authenticator or recovery code</span>
                    <input
                      className="auth-input auth-input--code"
                      value={passwordCode}
                      onChange={(event) => setPasswordCode(event.target.value)}
                      autoComplete="one-time-code"
                      placeholder="123456 or ABCDE-FGHIJ"
                    />
                  </label>
                )}
                <div className="account-form__actions">
                  <button type="submit" className="account-primary-button" disabled={passwordBusy}>
                    {passwordBusy ? <Loader2 size={15} className="auth-spinner" /> : <KeyRound size={15} />}
                    {passwordBusy ? 'Updating…' : user.has_password ? 'Change password' : 'Set password'}
                  </button>
                  <span className="account-form__note">
                    Argon2id hashed. Other sessions are revoked on change.
                  </span>
                </div>
              </form>
            </AccountSection>

            <AccountSection
              id="two-factor"
              index="03"
              title="Two-factor authentication"
              description="A time-based code from an authenticator app, with single-use recovery codes."
            >
              <div className="account-inline-head">
                <span className={`account-badge${user.totp_enabled ? ' account-badge--ok' : ''}`}>
                  {user.totp_enabled ? 'On' : 'Off'}
                </span>
                {user.totp_enabled && (
                  <span className="account-inline-head__meta">
                    {user.recovery_codes_remaining} recovery code
                    {user.recovery_codes_remaining === 1 ? '' : 's'} remaining
                  </span>
                )}
              </div>
              {totpStatus && <StatusMessage tone={totpStatus.tone}>{totpStatus.text}</StatusMessage>}

              {recoveryCodes && (
                <RecoveryCodes codes={recoveryCodes} onDone={() => setRecoveryCodes(null)} />
              )}

              {!user.totp_enabled && !totpSetup && (
                <div className="account-panel">
                  <p>
                    Protect the account with any TOTP app. A password alone is no longer
                    enough after this is on.
                  </p>
                  {user.has_password && (
                    <PasswordField
                      label="Confirm your password to begin"
                      value={totpPassword}
                      onChange={setTotpPassword}
                      autoComplete="current-password"
                      placeholder="Your current password"
                    />
                  )}
                  <button
                    type="button"
                    className="account-primary-button"
                    onClick={beginTotp}
                    disabled={totpBusy === 'setup'}
                  >
                    {totpBusy === 'setup' ? <Loader2 size={15} className="auth-spinner" /> : <Smartphone size={15} />}
                    {totpBusy === 'setup' ? 'Preparing…' : 'Set up an authenticator'}
                  </button>
                </div>
              )}

              {!user.totp_enabled && totpSetup && (
                <form className="totp-setup" onSubmit={activateTotp}>
                  <div className="totp-setup__visual">
                    {totpSetup.qr_data_uri ? (
                      <img
                        src={totpSetup.qr_data_uri}
                        alt="QR code for the authenticator app"
                        width={168}
                        height={168}
                      />
                    ) : (
                      <div className="totp-setup__placeholder" aria-hidden="true">
                        <Smartphone size={40} />
                      </div>
                    )}
                    <div className="totp-setup__instructions">
                      <p className="account-step">Scan the code with your authenticator app.</p>
                      <p>Or enter this key manually:</p>
                      <code className="totp-secret">{totpSetup.secret}</code>
                      <a href={totpSetup.otpauth_uri} className="account-inline-link">
                        Open in an authenticator
                      </a>
                    </div>
                  </div>
                  <label className="account-field">
                    <span>Six-digit code from the app</span>
                    <input
                      className="auth-input auth-input--code"
                      value={totpCode}
                      onChange={(event) => setTotpCode(event.target.value)}
                      autoComplete="one-time-code"
                      inputMode="numeric"
                      placeholder="000000"
                      autoFocus
                    />
                  </label>
                  <div className="account-form__actions">
                    <button type="submit" className="account-primary-button" disabled={totpBusy === 'enable'}>
                      {totpBusy === 'enable' ? <Loader2 size={15} className="auth-spinner" /> : <ShieldCheck size={15} />}
                      {totpBusy === 'enable' ? 'Turning on…' : 'Turn on two-factor'}
                    </button>
                    <button
                      type="button"
                      className="account-text-button"
                      onClick={() => {
                        setTotpSetup(null);
                        setTotpCode('');
                        setTotpPassword('');
                        setTotpStatus(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}

              {user.totp_enabled && (
                <div className="account-actions-grid">
                  <div className="account-panel">
                    <h3>Authenticator</h3>
                    <p>You will be asked for a code after your password, and after Google sign-in.</p>
                    <div className="account-form__actions">
                      <button
                        type="button"
                        className="account-quiet-button"
                        onClick={() => setShowDisable((value) => !value)}
                      >
                        <Unlink size={14} />
                        {showDisable ? 'Keep two-factor on' : 'Turn off two-factor'}
                      </button>
                      <button
                        type="button"
                        className="account-quiet-button"
                        onClick={() => setShowRegen((value) => !value)}
                      >
                        <Copy size={14} />
                        Replace recovery codes
                      </button>
                    </div>
                    {showDisable && (
                      <form className="account-inline-form" onSubmit={turnOffTotp}>
                        {user.has_password && (
                          <PasswordField
                            label="Password"
                            value={disablePassword}
                            onChange={setDisablePassword}
                            autoComplete="current-password"
                            placeholder="Your password"
                          />
                        )}
                        <label className="account-field">
                          <span>Authenticator or recovery code</span>
                          <input
                            className="auth-input auth-input--code"
                            value={disableCode}
                            onChange={(event) => setDisableCode(event.target.value)}
                            autoComplete="one-time-code"
                            placeholder="123456 or ABCDE-FGHIJ"
                          />
                        </label>
                        <button type="submit" className="account-danger-button" disabled={totpBusy === 'disable'}>
                          {totpBusy === 'disable' ? <Loader2 size={14} className="auth-spinner" /> : null}
                          Turn off two-factor
                        </button>
                      </form>
                    )}
                    {showRegen && (
                      <form className="account-inline-form" onSubmit={replaceRecoveryCodes}>
                        {user.has_password && (
                          <PasswordField
                            label="Password"
                            value={regenPassword}
                            onChange={setRegenPassword}
                            autoComplete="current-password"
                            placeholder="Your password"
                          />
                        )}
                        <label className="account-field">
                          <span>Authenticator or recovery code</span>
                          <input
                            className="auth-input auth-input--code"
                            value={regenCode}
                            onChange={(event) => setRegenCode(event.target.value)}
                            autoComplete="one-time-code"
                            placeholder="123456 or ABCDE-FGHIJ"
                          />
                        </label>
                        <button type="submit" className="account-quiet-button" disabled={totpBusy === 'regen'}>
                          {totpBusy === 'regen' ? <Loader2 size={14} className="auth-spinner" /> : null}
                          Generate new codes
                        </button>
                      </form>
                    )}
                  </div>
                </div>
              )}
            </AccountSection>

            <AccountSection
              id="google"
              index="04"
              title="Google sign-in"
              description="An alternative way into the same reader account. Your reader data does not change."
            >
              {googleStatus && <StatusMessage tone={googleStatus.tone}>{googleStatus.text}</StatusMessage>}
              <div className="account-detail-row">
                <div>
                  <span className="account-detail-row__label">Google</span>
                  <strong>{user.google_linked ? 'Connected' : 'Not connected'}</strong>
                  <p>
                    {user.google_linked
                      ? 'Google sign-in is active. Password reset and two-factor still protect the account.'
                      : user.has_password
                        ? 'Connect Google to sign in without typing your password.'
                        : 'This account uses Google sign-in. Set a password before disconnecting it.'}
                  </p>
                </div>
                {user.google_linked ? (
                  user.has_password ? (
                    <form className="account-inline-form account-inline-form--compact" onSubmit={disconnectGoogle}>
                      <PasswordField
                        label="Password"
                        value={googlePassword}
                        onChange={setGooglePassword}
                        autoComplete="current-password"
                        placeholder="Confirm password"
                      />
                      <button type="submit" className="account-quiet-button" disabled={googleBusy}>
                        {googleBusy ? <Loader2 size={14} className="auth-spinner" /> : <Unlink size={14} />}
                        Disconnect Google
                      </button>
                    </form>
                  ) : (
                    <button
                      type="button"
                      className="account-quiet-button"
                      onClick={() => onNavigate('security')}
                    >
                      Set a password first
                    </button>
                  )
                ) : (
                  <button
                    type="button"
                    className="account-primary-button"
                    onClick={connectGoogle}
                    disabled={!auth.config.google_enabled || googleBusy}
                    title={!auth.config.google_enabled ? 'Google sign-in is not configured on this server.' : undefined}
                  >
                    {googleBusy ? <Loader2 size={15} className="auth-spinner" /> : <Link2 size={15} />}
                    Connect Google
                  </button>
                )}
              </div>
              {!auth.config.google_enabled && (
                <p className="account-hint">
                  Google sign-in is not configured on this server. Add a Google OAuth client
                  to enable it.
                </p>
              )}
            </AccountSection>

            <AccountSection
              id="sessions"
              index="05"
              title="Sessions"
              description="Every browser currently signed in to this reader account."
            >
              {sessionStatus && <StatusMessage tone="info">{sessionStatus}</StatusMessage>}
              {dataError && <StatusMessage tone="error">{dataError}</StatusMessage>}
              {dataLoading && sessions.length === 0 ? (
                <p className="account-loading-line">
                  <Loader2 size={15} className="auth-spinner" />
                  Reading active sessions…
                </p>
              ) : (
                <ul className="session-list">
                  {sessions.map((session) => (
                    <SessionRow
                      key={session.id}
                      session={session}
                      busy={sessionBusy === session.id}
                      onRevoke={signOutSession}
                    />
                  ))}
                </ul>
              )}
              {sessions.some((session) => !session.current) && (
                <button
                  type="button"
                  className="account-quiet-button"
                  onClick={signOutOtherSessions}
                  disabled={sessionBusy === 'others'}
                >
                  {sessionBusy === 'others' ? <Loader2 size={14} className="auth-spinner" /> : <LogOut size={14} />}
                  Sign out all other sessions
                </button>
              )}
            </AccountSection>

            <AccountSection
              id="activity"
              index="06"
              title="Security activity"
              description="The last 20 account events, kept so you can spot anything unfamiliar."
            >
              {dataLoading && activity.length === 0 ? (
                <p className="account-loading-line">
                  <Loader2 size={15} className="auth-spinner" />
                  Reading the security ledger…
                </p>
              ) : activity.length === 0 ? (
                <p className="account-empty">No activity recorded yet.</p>
              ) : (
                <ul className="activity-list">
                  {activity.map((event, index) => (
                    <ActivityRow key={`${event.event}-${event.created_at}-${index}`} event={event} />
                  ))}
                </ul>
              )}
            </AccountSection>

            <AccountSection
              id="close"
              index="07"
              title="Close account"
              description="Permanently remove the reader account, sessions and security history."
            >
              {closeStatus && <StatusMessage tone="error">{closeStatus}</StatusMessage>}
              {!showClose ? (
                <button type="button" className="account-danger-button" onClick={() => setShowClose(true)}>
                  <AlertTriangle size={15} />
                  Close this account
                </button>
              ) : (
                <form className="account-danger-panel" onSubmit={closeAccount}>
                  <p>
                    This cannot be undone. Type <strong>{user.email}</strong> and confirm
                    your credentials to continue.
                  </p>
                  <label className="account-field">
                    <span>Confirm email address</span>
                    <input
                      className="auth-input"
                      type="email"
                      value={closeEmail}
                      onChange={(event) => setCloseEmail(event.target.value)}
                      autoComplete="off"
                      placeholder={user.email}
                    />
                  </label>
                  {user.has_password ? (
                    <PasswordField
                      label="Password"
                      value={closePassword}
                      onChange={setClosePassword}
                      autoComplete="current-password"
                      placeholder="Your password"
                    />
                  ) : user.totp_enabled ? (
                    <label className="account-field">
                      <span>Authenticator or recovery code</span>
                      <input
                        className="auth-input auth-input--code"
                        value={closeCode}
                        onChange={(event) => setCloseCode(event.target.value)}
                        autoComplete="one-time-code"
                        placeholder="123456 or ABCDE-FGHIJ"
                      />
                    </label>
                  ) : null}
                  <div className="account-form__actions">
                    <button
                      type="submit"
                      className="account-danger-button"
                      disabled={closeBusy || closeEmail.trim().toLowerCase() !== user.email}
                    >
                      {closeBusy ? <Loader2 size={15} className="auth-spinner" /> : <AlertTriangle size={15} />}
                      {closeBusy ? 'Closing…' : 'Permanently close account'}
                    </button>
                    <button
                      type="button"
                      className="account-text-button"
                      onClick={() => {
                        setShowClose(false);
                        setCloseStatus(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </AccountSection>

            <footer className="account-foot">
              <Clock3 size={14} aria-hidden="true" />
              <span>
                Sessions expire automatically. Passkeys and email changes are not part of
                this release.
              </span>
            </footer>
          </div>
        </div>
      </main>
    </div>
  );
};
