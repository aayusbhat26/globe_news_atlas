import React, { useId, useState } from 'react';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import { assessPassword } from '../../utils/auth';

interface PasswordFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  placeholder?: string;
  error?: string;
  hint?: string;
  autoFocus?: boolean;
  disabled?: boolean;
}

export const PasswordField: React.FC<PasswordFieldProps> = ({
  label,
  value,
  onChange,
  autoComplete,
  placeholder,
  error,
  hint,
  autoFocus,
  disabled,
}) => {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const [visible, setVisible] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  return (
    <div className={`auth-field${error ? ' auth-field--error' : ''}`}>
      <label className="auth-field__label" htmlFor={id}>
        {label}
      </label>
      <div className="auth-field__control">
        <input
          id={id}
          className="auth-input auth-input--password"
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          disabled={disabled}
          spellCheck={false}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
          onKeyDown={(event) => setCapsLock(event.getModifierState?.('CapsLock') ?? false)}
          onKeyUp={(event) => setCapsLock(event.getModifierState?.('CapsLock') ?? false)}
          onBlur={() => setCapsLock(false)}
        />
        <button
          type="button"
          className="auth-field__reveal"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide password' : 'Show password'}
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
      {capsLock && <p className="auth-field__caps">Caps Lock is on</p>}
      {error ? (
        <p className="auth-field__error" id={errorId}>
          {error}
        </p>
      ) : hint ? (
        <p className="auth-field__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
    </div>
  );
};

interface PasswordStrengthProps {
  password: string;
  minimum: number;
  email?: string;
}

export const PasswordStrength: React.FC<PasswordStrengthProps> = ({
  password,
  minimum,
  email,
}) => {
  if (!password) return null;
  const assessment = assessPassword(password, minimum, email);
  return (
    <div className="password-strength" aria-live="polite">
      <div className="password-strength__head">
        <span>Password strength</span>
        <strong>{assessment.label}</strong>
      </div>
      <div className="password-strength__bars" aria-hidden="true">
        {[1, 2, 3, 4].map((step) => (
          <span
            key={step}
            className={step <= assessment.score ? 'is-filled' : undefined}
          />
        ))}
      </div>
      {assessment.problems.length > 0 && (
        <p className="password-strength__hint">{assessment.problems[0]}</p>
      )}
    </div>
  );
};

export const AuthNotice: React.FC<{
  tone: 'error' | 'success' | 'info';
  children: React.ReactNode;
}> = ({ tone, children }) => (
  <div
    className={`auth-notice auth-notice--${tone}`}
    role={tone === 'error' ? 'alert' : 'status'}
  >
    {children}
  </div>
);

export const SubmitButton: React.FC<{
  busy: boolean;
  children: React.ReactNode;
  busyLabel?: string;
  variant?: 'primary' | 'quiet';
  type?: 'submit' | 'button';
  onClick?: () => void;
  disabled?: boolean;
}> = ({ busy, children, busyLabel, variant = 'primary', type = 'submit', onClick, disabled }) => (
  <button
    className={`auth-submit auth-submit--${variant}`}
    type={type}
    disabled={busy || disabled}
    onClick={onClick}
  >
    {busy ? (
      <>
        <Loader2 size={16} className="auth-spinner" aria-hidden="true" />
        <span>{busyLabel || 'Working…'}</span>
      </>
    ) : (
      children
    )}
  </button>
);

export const GoogleMark: React.FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
    <path
      fill="#4285F4"
      d="M23.49 12.27c0-.79-.07-1.54-.2-2.27H12v4.3h6.45a5.52 5.52 0 0 1-2.39 3.62v3h3.87c2.26-2.09 3.56-5.17 3.56-8.65Z"
    />
    <path
      fill="#34A853"
      d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.87-3c-1.08.72-2.45 1.15-4.06 1.15-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A11.99 11.99 0 0 0 12 24Z"
    />
    <path
      fill="#FBBC05"
      d="M5.27 14.28A7.2 7.2 0 0 1 4.89 12c0-.79.14-1.55.38-2.28V6.63H1.29A11.99 11.99 0 0 0 0 12c0 1.94.47 3.77 1.29 5.37l3.98-3.09Z"
    />
    <path
      fill="#EA4335"
      d="M12 4.75c1.76 0 3.34.61 4.58 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.69 1.29 6.63l3.98 3.09C6.22 6.87 8.87 4.75 12 4.75Z"
    />
  </svg>
);

export const GoogleButton: React.FC<{
  onClick: () => void;
  enabled: boolean;
  label: string;
  hint?: string;
}> = ({ onClick, enabled, label, hint }) => (
  <div className="google-block">
    <button
      type="button"
      className="google-button"
      onClick={onClick}
      disabled={!enabled}
      aria-disabled={!enabled}
    >
      <GoogleMark />
      <span>{label}</span>
    </button>
    {!enabled && hint && <p className="google-block__hint">{hint}</p>}
  </div>
);

export const AuthDivider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="auth-divider">
    <span>{children}</span>
  </div>
);
