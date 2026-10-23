const COMMON_PASSWORDS = new Set([
  'password',
  'password1',
  'password123',
  '123456789012',
  'qwertyuiop',
  'letmein',
  'welcome123',
  'iloveyou',
  'admin123',
  'correcthorsebatterystaple',
]);

export function isValidEmail(value: string): boolean {
  const email = value.trim();
  if (email.length > 254) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);
}

export interface PasswordAssessment {
  score: 0 | 1 | 2 | 3 | 4;
  label: 'Too short' | 'Weak' | 'Fair' | 'Strong' | 'Excellent';
  problems: string[];
}

export function assessPassword(password: string, minimum: number, email = ''): PasswordAssessment {
  const problems: string[] = [];
  if (!password) {
    return { score: 0, label: 'Too short', problems: ['Enter a password.'] };
  }
  if (password.length < minimum) {
    problems.push(`Use at least ${minimum} characters.`);
  }
  if (password.length > 128) {
    problems.push('Use no more than 128 characters.');
  }
  if (COMMON_PASSWORDS.has(password.toLowerCase())) {
    problems.push('This is one of the most common passwords.');
  }
  const local = email.split('@')[0]?.toLowerCase();
  if (local && local.length >= 4 && password.toLowerCase().includes(local)) {
    problems.push('Do not include your email address.');
  }
  if (password.length >= 8 && new Set(password).size <= 2) {
    problems.push('This repeats too few characters.');
  }

  let score = 0;
  if (password.length >= minimum) score += 1;
  if (password.length >= minimum + 4) score += 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) =>
    pattern.test(password),
  ).length;
  if (classes >= 3) score += 1;
  if (classes === 4) score += 1;
  if (password.length >= 20 && classes >= 3) score = 4;
  if (problems.length) score = Math.min(score, 1);
  const bounded = Math.max(0, Math.min(4, score)) as PasswordAssessment['score'];
  const label: PasswordAssessment['label'] =
    bounded === 0 ? 'Too short' : bounded === 1 ? 'Weak' : bounded === 2 ? 'Fair' : bounded === 3 ? 'Strong' : 'Excellent';
  return { score: bounded, label, problems };
}

export function passwordProblems(password: string, minimum: number, email = ''): string[] {
  return assessPassword(password, minimum, email).problems;
}

export function initials(name: string, email: string): string {
  const source = name.trim() || email.split('@')[0] || '?';
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

export function formatAccountDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

export function formatAccountDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function describeAuthMethod(method: string): string {
  switch (method) {
    case 'google':
      return 'Google';
    case 'two_factor':
      return 'Password + 2FA';
    case 'email_verification':
      return 'Email link';
    default:
      return 'Password';
  }
}

export function describeAuthEvent(event: string): string {
  switch (event) {
    case 'signup':
      return 'Account created';
    case 'signup_google':
      return 'Account created with Google';
    case 'signup_duplicate':
      return 'Sign-up attempted for an existing account';
    case 'login':
      return 'Signed in';
    case 'login_failed':
      return 'Failed sign-in attempt';
    case 'logout':
      return 'Signed out';
    case 'verification_sent':
      return 'Confirmation email sent';
    case 'email_verified':
      return 'Email confirmed';
    case 'password_reset_requested':
      return 'Password reset requested';
    case 'password_reset':
      return 'Password reset';
    case 'password_changed':
      return 'Password changed';
    case 'totp_setup_started':
      return 'Authenticator setup started';
    case 'totp_enabled':
      return 'Two-factor authentication turned on';
    case 'totp_disabled':
      return 'Two-factor authentication turned off';
    case 'recovery_codes_regenerated':
      return 'Recovery codes replaced';
    case 'google_linked':
      return 'Google account connected';
    case 'google_unlinked':
      return 'Google account disconnected';
    case 'session_revoked':
      return 'Session signed out';
    case 'sessions_revoked':
      return 'Other sessions signed out';
    case 'profile_updated':
      return 'Profile updated';
    case 'account_deleted':
      return 'Account closed';
    default:
      return event.replace(/_/g, ' ');
  }
}

export function eventMethod(metadata: Record<string, unknown>): string | null {
  const method = metadata.method;
  return typeof method === 'string' ? method : null;
}

export async function copyToClipboard(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* fall through to the selection-based copy path */
  }
  try {
    const field = document.createElement('textarea');
    field.value = value;
    field.setAttribute('readonly', '');
    field.style.position = 'fixed';
    field.style.opacity = '0';
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand('copy');
    field.remove();
    return copied;
  } catch {
    return false;
  }
}
