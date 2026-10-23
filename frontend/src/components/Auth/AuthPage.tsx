import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  KeyRound,
  Loader2,
  MailCheck,
  ShieldCheck,
} from 'lucide-react';
import { AuthLayout } from './AuthLayout';
import {
  AuthDivider,
  AuthNotice,
  GoogleButton,
  PasswordField,
  PasswordStrength,
  SubmitButton,
} from './AuthFields';
import { useAuth } from '../../auth/AuthContext';
import {
  checkResetToken,
  checkVerificationToken,
  forgotPassword,
  login,
  loginTwoFactor,
  googleStartUrl,
  resetPassword,
  signup,
  verifyEmail,
} from '../../services/auth';
import { ApiError } from '../../services/api';
import { isValidEmail } from '../../utils/auth';
import { navigate, replaceQuerySilently, safeNextPath } from '../../router';

export type AuthMode = 'login' | 'signup' | 'forgot' | 'reset' | 'verify';

interface AuthPageProps {
  mode: AuthMode;
}

const GOOGLE_ERRORS: Record<string, string> = {
  google_denied: 'Google sign-in was cancelled before it finished.',
  google_state: 'That Google sign-in expired or was already used. Try again.',
  google_email_mismatch:
    'Use the Google account with the same email as this reader account.',
  google_already_linked: 'That Google account is already connected to another reader.',
  google_email_unverified: 'Google has not verified that email address.',
  google_not_configured: 'Google sign-in is not configured on this server.',
  google_unreachable: 'Could not reach Google. Try again in a moment.',
  google_failed: 'Google sign-in could not be completed. Try again.',
  google_invalid_token: 'Google returned an identity this server could not verify.',
  google_nonce_mismatch: 'The Google response did not match this sign-in. Try again.',
};

const errorMessage = (error: unknown): string => {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Try again.';
};

const queryValue = (name: string): string | null =>
  new URLSearchParams(window.location.search).get(name);

const panelCopy: Record<
  AuthMode,
  { eyebrow: string; title: string; deck: string; titleDocument: string }
> = {
  login: {
    eyebrow: 'Account access',
    title: 'Sign in',
    deck: 'Return to your reading, your saved desks and the world as it stands.',
    titleDocument: 'Sign in — Globe News Atlas',
  },
  signup: {
    eyebrow: 'Reader accounts',
    title: 'Create your account',
    deck: 'A quiet place for your reading. No feed, no tracking pixels, no algorithm.',
    titleDocument: 'Create account — Globe News Atlas',
  },
  forgot: {
    eyebrow: 'Account recovery',
    title: 'Reset your password',
    deck: 'Enter the address on your account and we will send a single-use link.',
    titleDocument: 'Reset password — Globe News Atlas',
  },
  reset: {
    eyebrow: 'Account recovery',
    title: 'Choose a new password',
    deck: 'A fresh password closes every existing session and returns the account to you.',
    titleDocument: 'Choose a new password — Globe News Atlas',
  },
  verify: {
    eyebrow: 'One last step',
    title: 'Confirm your email',
    deck: 'Confirming the address lets us send sign-in and security notices to the right place.',
    titleDocument: 'Confirm email — Globe News Atlas',
  },
};

export const AuthPage: React.FC<AuthPageProps> = ({ mode }) => {
  const auth = useAuth();
  const minimum = auth.config.password_min_length || 12;
  const copy = panelCopy[mode];
  const initialHash = useMemo(
    () => new URLSearchParams(window.location.hash.replace(/^#/, '')),
    [],
  );
  const initialChallenge = mode === 'login' ? initialHash.get('two-factor') : null;
  const nextPath = useRef(
    safeNextPath(initialHash.get('next') || queryValue('next'), '/'),
  );

  const [email, setEmail] = useState(queryValue('email') || '');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [remember, setRemember] = useState(false);
  const [terms, setTerms] = useState(false);
  const [website, setWebsite] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(
    mode === 'login' && queryValue('error')
      ? GOOGLE_ERRORS[queryValue('error') || ''] ||
          'Sign-in could not be completed. Try again.'
      : null,
  );
  const [challenge, setChallenge] = useState<{ token: string; emailMasked: string } | null>(
    initialChallenge ? { token: initialChallenge, emailMasked: '' } : null,
  );
  const [code, setCode] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const token = queryValue('token');
  const [tokenState, setTokenState] = useState<
    'idle' | 'checking' | 'valid' | 'invalid' | 'error'
  >(mode === 'verify' || mode === 'reset' ? 'checking' : 'idle');
  const [tokenAttempt, setTokenAttempt] = useState(0);
  const [maskedEmail, setMaskedEmail] = useState<string | null>(null);
  const [verified, setVerified] = useState(false);
  const [resetComplete, setResetComplete] = useState(false);

  useEffect(() => {
    document.title = copy.titleDocument;
  }, [copy.titleDocument]);

  useEffect(() => {
    if (window.location.hash) {
      replaceQuerySilently(`${window.location.pathname}${window.location.search}`);
    }
  }, []);

  useEffect(() => {
    if (!['verify', 'reset'].includes(mode)) return;
    if (!token) {
      setTokenState('invalid');
      return;
    }
    const check = mode === 'verify' ? checkVerificationToken : checkResetToken;
    setTokenState('checking');
    check(token)
      .then((result) => {
        setMaskedEmail(result.email_masked);
        setTokenState(result.valid ? 'valid' : 'invalid');
      })
      .catch(() => setTokenState('error'));
  }, [mode, token, tokenAttempt]);

  useEffect(() => {
    if (!verified) return;
    const timer = window.setTimeout(() => navigate('/account', { replace: true }), 1400);
    return () => window.clearTimeout(timer);
  }, [verified]);

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!isValidEmail(email)) {
      setError('Enter a valid email address.');
      return;
    }
    if (!password) {
      setError('Enter your password.');
      return;
    }
    setBusy(true);
    try {
      const result = await login(email.trim(), password, remember);
      if (result.two_factor_required) {
        setChallenge({ token: result.challenge_token, emailMasked: result.email_masked });
        setCode('');
        setPassword('');
      } else {
        await auth.refresh();
        auth.notifyAuthChange();
        navigate(nextPath.current, { replace: true });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitTwoFactor = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!challenge) return;
    setError(null);
    if (!code.trim()) {
      setError('Enter the six-digit code or a recovery code.');
      return;
    }
    setBusy(true);
    try {
      await loginTwoFactor(
        challenge.token,
        code.trim(),
        initialChallenge ? null : remember,
      );
      await auth.refresh();
      auth.notifyAuthChange();
      navigate(nextPath.current, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitSignup = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!isValidEmail(email)) {
      setError('Enter a valid email address.');
      return;
    }
    if (password.length < minimum) {
      setError(`Use at least ${minimum} characters for your password.`);
      return;
    }
    if (password !== confirmPassword) {
      setError('The passwords do not match.');
      return;
    }
    if (!terms) {
      setError('Accept the terms and privacy notice to create an account.');
      return;
    }
    setBusy(true);
    try {
      const result = await signup({
        email: email.trim(),
        password,
        display_name: displayName.trim(),
        remember: false,
        accept_terms: terms,
        website,
      });
      setSentTo(email.trim());
      setMessage(result.message);
      setDevLink(result.dev_verification_link || null);
      setPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitForgot = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!isValidEmail(email)) {
      setError('Enter a valid email address.');
      return;
    }
    setBusy(true);
    try {
      const result = await forgotPassword(email.trim());
      setSentTo(email.trim());
      setMessage(result.message);
      setDevLink(result.dev_reset_link || null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitReset = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!token) {
      setError('This reset link is incomplete.');
      return;
    }
    if (password.length < minimum) {
      setError(`Use at least ${minimum} characters for your password.`);
      return;
    }
    if (password !== confirmPassword) {
      setError('The passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      const result = await resetPassword(token, password);
      setMessage(result.message);
      setResetComplete(true);
      setPassword('');
      setConfirmPassword('');
      await auth.refresh();
      auth.notifyAuthChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitVerify = async () => {
    if (!token) return;
    setError(null);
    setBusy(true);
    try {
      await verifyEmail(token);
      await auth.refresh();
      auth.notifyAuthChange();
      setVerified(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const startGoogle = () => {
    if (!auth.config.google_enabled) return;
    window.location.assign(googleStartUrl(nextPath.current));
  };

  const renderHeader = (titleOverride?: string) => (
    <div className="auth-panel__header">
      <p className="auth-kicker auth-kicker--panel">{copy.eyebrow}</p>
      <h2 className="auth-panel__title">{titleOverride || copy.title}</h2>
      <p className="auth-panel__deck">{copy.deck}</p>
    </div>
  );

  const renderGoogle = (label: string, withTerms = false) => (
    <>
      <GoogleButton
        onClick={startGoogle}
        enabled={auth.config.google_enabled && !auth.loading}
        label={label}
        hint={
          auth.config.environment === 'production'
            ? 'Google sign-in is not available right now.'
            : 'Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable Google sign-in.'
        }
      />
      {withTerms && (
        <p className="auth-google-note">
          By continuing with Google you agree to the{' '}
          <a href="/terms" target="_blank" rel="noreferrer">
            Terms
          </a>{' '}
          and{' '}
          <a href="/privacy" target="_blank" rel="noreferrer">
            Privacy Notice
          </a>
          .
        </p>
      )}
      <AuthDivider>or with your email</AuthDivider>
    </>
  );

  if (mode === 'login' && challenge) {
    return (
      <AuthLayout>
        <div className="auth-panel__inner">
          <button
            type="button"
            className="auth-back-link"
            onClick={() => {
              setChallenge(null);
              setCode('');
              setError(null);
            }}
          >
            <ArrowLeft size={14} aria-hidden="true" />
            Back to sign in
          </button>
          <div className="auth-panel__header">
            <span className="auth-icon-mark">
              <ShieldCheck size={20} />
            </span>
            <p className="auth-kicker auth-kicker--panel">Two-step verification</p>
            <h2 className="auth-panel__title">One more check</h2>
            <p className="auth-panel__deck">
              {challenge.emailMasked
                ? `Enter the six-digit code for ${challenge.emailMasked}, or use a recovery code.`
                : 'Enter the six-digit code from your authenticator app, or use a recovery code.'}
            </p>
          </div>
          {error && <AuthNotice tone="error">{error}</AuthNotice>}
          <form className="auth-form" onSubmit={submitTwoFactor} noValidate>
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="auth-code">
                Authentication code
              </label>
              <input
                id="auth-code"
                className="auth-input auth-input--code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                placeholder="000 000"
                maxLength={32}
              />
              <p className="auth-field__hint">
                Lost your authenticator? Use one of the recovery codes you saved.
              </p>
            </div>
            <SubmitButton busy={busy} busyLabel="Checking code…">
              Verify and sign in
            </SubmitButton>
          </form>
          <p className="auth-panel__security">
            <KeyRound size={14} aria-hidden="true" />
            Two-step verification is on for this account.
          </p>
        </div>
      </AuthLayout>
    );
  }

  if (mode === 'login') {
    return (
      <AuthLayout>
        <div className="auth-panel__inner">
          {renderHeader()}
          {error && <AuthNotice tone="error">{error}</AuthNotice>}
          {renderGoogle('Continue with Google')}
          <form className="auth-form" onSubmit={submitLogin} noValidate>
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="login-email">
                Email address
              </label>
              <input
                id="login-email"
                className="auth-input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                autoFocus
                placeholder="you@example.com"
                aria-invalid={Boolean(error && !isValidEmail(email))}
              />
            </div>
            <PasswordField
              label="Password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              placeholder="Your password"
            />
            <div className="auth-form__row">
              <label className="auth-check">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                />
                <span>Keep me signed in for 30 days</span>
              </label>
              <button
                type="button"
                className="auth-inline-link"
                onClick={() => navigate('/forgot-password')}
              >
                Forgot password?
              </button>
            </div>
            <SubmitButton busy={busy} busyLabel="Signing in…">
              Sign in
            </SubmitButton>
          </form>
          <p className="auth-panel__switch">
            New to the Atlas?{' '}
            <button type="button" onClick={() => navigate('/signup')}>
              Create an account
            </button>
          </p>
          <p className="auth-panel__security">
            <ShieldCheck size={14} aria-hidden="true" />
            Protected with Argon2id, session controls and optional two-factor.
          </p>
        </div>
      </AuthLayout>
    );
  }

  if (mode === 'signup') {
    if (sentTo) {
      return (
        <AuthLayout>
          <div className="auth-panel__inner">
            <div className="auth-complete">
              <span className="auth-complete__mark">
                <MailCheck size={26} />
              </span>
              <p className="auth-kicker auth-kicker--panel">Account request received</p>
              <h2 className="auth-panel__title">Check your inbox</h2>
              <p className="auth-panel__deck">
                If this address is new, your confirmation link is on its way. If an
                account already exists, we sent a security notice instead of creating
                a duplicate. You can sign in with the existing account now.
              </p>
              <div className="auth-receipt">
                <span>Sent to</span>
                <strong>{sentTo}</strong>
              </div>
              {devLink && (
                <AuthNotice tone="info">
                  Local development has no mail server, so the link is available here:{' '}
                  <a href={devLink}>open the confirmation link</a>.
                </AuthNotice>
              )}
              <SubmitButton
                type="button"
                busy={false}
                onClick={() => navigate('/login')}
              >
                Continue to sign in
              </SubmitButton>
              <button
                type="button"
                className="auth-text-button"
                onClick={() => {
                  setSentTo(null);
                  setMessage(null);
                  setDevLink(null);
                }}
              >
                Use a different address
              </button>
            </div>
          </div>
        </AuthLayout>
      );
    }

    return (
      <AuthLayout>
        <div className="auth-panel__inner">
          {renderHeader()}
          {error && <AuthNotice tone="error">{error}</AuthNotice>}
          {renderGoogle('Sign up with Google', true)}
          <form className="auth-form" onSubmit={submitSignup} noValidate>
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="signup-name">
                Display name <span>optional</span>
              </label>
              <input
                id="signup-name"
                className="auth-input"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                autoComplete="name"
                placeholder="How your byline reads"
                maxLength={80}
              />
            </div>
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="signup-email">
                Email address
              </label>
              <input
                id="signup-email"
                className="auth-input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                autoFocus
                placeholder="you@example.com"
              />
            </div>
            <PasswordField
              label="Password"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              placeholder={`At least ${minimum} characters`}
            />
            <PasswordStrength password={password} minimum={minimum} email={email} />
            <PasswordField
              label="Confirm password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              placeholder="Repeat your password"
            />
            <div className="auth-honeypot" aria-hidden="true">
              <label htmlFor="signup-website">Website</label>
              <input
                id="signup-website"
                name="website"
                tabIndex={-1}
                autoComplete="off"
                value={website}
                onChange={(event) => setWebsite(event.target.value)}
              />
            </div>
            <label className="auth-check auth-check--terms">
              <input
                type="checkbox"
                checked={terms}
                onChange={(event) => setTerms(event.target.checked)}
              />
              <span>
                I agree to the{' '}
                <a href="/terms" target="_blank" rel="noreferrer">
                  Terms
                </a>{' '}
                and{' '}
                <a href="/privacy" target="_blank" rel="noreferrer">
                  Privacy Notice
                </a>
                .
              </span>
            </label>
            <SubmitButton busy={busy} busyLabel="Creating account…">
              Create account
            </SubmitButton>
          </form>
          <p className="auth-panel__switch">
            Already have a reader account?{' '}
            <button type="button" onClick={() => navigate('/login')}>
              Sign in
            </button>
          </p>
          <p className="auth-panel__security">
            <ShieldCheck size={14} aria-hidden="true" />
            No advertising scripts. No social trackers. No selling reader data.
          </p>
        </div>
      </AuthLayout>
    );
  }

  if (mode === 'forgot') {
    if (sentTo) {
      return (
        <AuthLayout>
          <div className="auth-panel__inner">
            <div className="auth-complete">
              <span className="auth-complete__mark">
                <MailCheck size={26} />
              </span>
              <p className="auth-kicker auth-kicker--panel">Check your inbox</p>
              <h2 className="auth-panel__title">A link is on its way</h2>
              <p className="auth-panel__deck">{message}</p>
              <div className="auth-receipt">
                <span>If registered</span>
                <strong>{sentTo}</strong>
              </div>
              {devLink && (
                <AuthNotice tone="info">
                  Local development has no mail server, so the link is available here:{' '}
                  <a href={devLink}>open the reset link</a>.
                </AuthNotice>
              )}
              <SubmitButton type="button" busy={false} onClick={() => navigate('/login')}>
                Back to sign in
              </SubmitButton>
            </div>
          </div>
        </AuthLayout>
      );
    }
    return (
      <AuthLayout>
        <div className="auth-panel__inner">
          {renderHeader()}
          {error && <AuthNotice tone="error">{error}</AuthNotice>}
          <form className="auth-form" onSubmit={submitForgot} noValidate>
            <div className="auth-field">
              <label className="auth-field__label" htmlFor="forgot-email">
                Email address
              </label>
              <input
                id="forgot-email"
                className="auth-input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                autoFocus
                placeholder="you@example.com"
              />
            </div>
            <SubmitButton busy={busy} busyLabel="Sending link…">
              Send reset link
            </SubmitButton>
          </form>
          <p className="auth-panel__switch">
            <button type="button" onClick={() => navigate('/login')}>
              Back to sign in
            </button>
          </p>
          <p className="auth-panel__security">
            For privacy, this page gives the same answer whether or not an account
            exists.
          </p>
        </div>
      </AuthLayout>
    );
  }

  if (mode === 'reset') {
    if (resetComplete) {
      return (
        <AuthLayout>
          <div className="auth-panel__inner">
            <div className="auth-complete">
              <span className="auth-complete__mark">
                <Check size={26} />
              </span>
              <p className="auth-kicker auth-kicker--panel">Password updated</p>
              <h2 className="auth-panel__title">The account is yours again</h2>
              <p className="auth-panel__deck">
                Every existing session was signed out. Sign in with the new password to
                continue.
              </p>
              <SubmitButton type="button" busy={false} onClick={() => navigate('/login')}>
                Sign in
              </SubmitButton>
            </div>
          </div>
        </AuthLayout>
      );
    }

    return (
      <AuthLayout>
        <div className="auth-panel__inner">
          {renderHeader()}
          {tokenState === 'checking' && (
            <p className="auth-loading-line">
              <Loader2 size={16} className="auth-spinner" />
              Checking the reset link…
            </p>
          )}
          {tokenState === 'invalid' && (
            <AuthNotice tone="error">
              This reset link is invalid, expired or already used.{' '}
              <button
                type="button"
                className="auth-inline-link"
                onClick={() => navigate('/forgot-password')}
              >
                Request a new one
              </button>
              .
            </AuthNotice>
          )}
          {tokenState === 'error' && (
            <AuthNotice tone="error">
              Could not check this reset link. Check your connection and try again.{' '}
              <button
                type="button"
                className="auth-inline-link"
                onClick={() => setTokenAttempt((attempt) => attempt + 1)}
              >
                Retry
              </button>
              .
            </AuthNotice>
          )}
          {error && <AuthNotice tone="error">{error}</AuthNotice>}
          {tokenState === 'valid' && (
            <form className="auth-form" onSubmit={submitReset} noValidate>
              {maskedEmail && (
                <div className="auth-receipt auth-receipt--inline">
                  <span>Resetting</span>
                  <strong>{maskedEmail}</strong>
                </div>
              )}
              <PasswordField
                label="New password"
                value={password}
                onChange={setPassword}
                autoComplete="new-password"
                placeholder={`At least ${minimum} characters`}
                autoFocus
              />
              <PasswordStrength password={password} minimum={minimum} />
              <PasswordField
                label="Confirm new password"
                value={confirmPassword}
                onChange={setConfirmPassword}
                autoComplete="new-password"
                placeholder="Repeat the new password"
              />
              <SubmitButton busy={busy} busyLabel="Updating password…">
                Choose new password
              </SubmitButton>
            </form>
          )}
          <p className="auth-panel__security">
            Resetting the password signs out every device, including this one.
          </p>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <div className="auth-panel__inner">
        {verified ? (
          <div className="auth-complete">
            <span className="auth-complete__mark">
              <Check size={26} />
            </span>
            <p className="auth-kicker auth-kicker--panel">Email confirmed</p>
            <h2 className="auth-panel__title">You are on the record</h2>
            <p className="auth-panel__deck">
              Taking you to your reader account. Your confirmation link has been used
              and cannot be replayed.
            </p>
            <p className="auth-loading-line">
              <Loader2 size={16} className="auth-spinner" />
              Opening your account…
            </p>
          </div>
        ) : (
          <>
            {renderHeader()}
            {tokenState === 'checking' && (
              <p className="auth-loading-line">
                <Loader2 size={16} className="auth-spinner" />
                Checking your confirmation link…
              </p>
            )}
            {tokenState === 'invalid' && (
              <AuthNotice tone="error">
                This confirmation link is invalid, expired or already used. Sign in, then
                request a new link from your account.
              </AuthNotice>
            )}
            {tokenState === 'error' && (
              <AuthNotice tone="error">
                Could not check this confirmation link. Check your connection and try
                again.{' '}
                <button
                  type="button"
                  className="auth-inline-link"
                  onClick={() => setTokenAttempt((attempt) => attempt + 1)}
                >
                  Retry
                </button>
                .
              </AuthNotice>
            )}
            {error && <AuthNotice tone="error">{error}</AuthNotice>}
            {tokenState === 'valid' && (
              <>
                <div className="auth-receipt">
                  <span>Address</span>
                  <strong>{maskedEmail}</strong>
                </div>
                <SubmitButton
                  type="button"
                  busy={busy}
                  busyLabel="Confirming…"
                  onClick={submitVerify}
                >
                  Confirm this email
                </SubmitButton>
                <p className="auth-panel__security">
                  This also signs you in on this device. The link works once.
                </p>
              </>
            )}
            {tokenState === 'invalid' && (
              <SubmitButton type="button" busy={false} onClick={() => navigate('/login')}>
                Go to sign in
              </SubmitButton>
            )}
          </>
        )}
      </div>
    </AuthLayout>
  );
};
