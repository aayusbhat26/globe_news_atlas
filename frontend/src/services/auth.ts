import { API_BASE, ApiError, requestJson } from './api';
import type {
  ActionResponse,
  AuthConfig,
  AuthMessage,
  AuthSessionResponse,
  EmailCheckResponse,
  LoginResponse,
  MeResponse,
  SecurityEvent,
  SessionInfo,
  TotpEnableResponse,
  TotpSetup,
  UserResponse,
} from '../types/auth';

const CSRF_COOKIE = 'gna_csrf';

export function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const chunk of document.cookie.split(';')) {
    const value = chunk.trim();
    if (value.startsWith(prefix)) {
      return decodeURIComponent(value.slice(prefix.length));
    }
  }
  return null;
}

export async function ensureCsrfToken(force = false): Promise<string> {
  if (!force) {
    const existing = readCookie(CSRF_COOKIE);
    if (existing) return existing;
  }
  const data = await requestJson<{ token: string }>('/auth/csrf');
  return data.token;
}

export async function authRequest<T>(path: string, init: RequestInit): Promise<T> {
  const send = async (force: boolean) => {
    const token = await ensureCsrfToken(force);
    return requestJson<T>(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': token,
        ...init.headers,
      },
    });
  };
  try {
    return await send(false);
  } catch (error) {
    if (error instanceof ApiError && error.code === 'csrf_failed') {
      return send(true);
    }
    throw error;
  }
}

function post<T>(path: string, payload: unknown = {}): Promise<T> {
  return authRequest<T>(path, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchAuthConfig(): Promise<AuthConfig> {
  return requestJson<AuthConfig>('/auth/config');
}

export function fetchMe(): Promise<MeResponse> {
  return requestJson<MeResponse>('/auth/me');
}

export interface SignupPayload {
  email: string;
  password: string;
  display_name: string;
  remember: boolean;
  accept_terms: boolean;
  website: string;
}

export function signup(payload: SignupPayload): Promise<AuthMessage> {
  return post('/auth/signup', payload);
}

export function login(
  email: string,
  password: string,
  remember: boolean,
): Promise<LoginResponse> {
  return post('/auth/login', { email, password, remember });
}

export function loginTwoFactor(
  challengeToken: string,
  code: string,
  remember: boolean | null,
): Promise<AuthSessionResponse> {
  return post('/auth/login/2fa', {
    challenge_token: challengeToken,
    code,
    remember,
  });
}

export function logout(): Promise<ActionResponse> {
  return post('/auth/logout');
}

export function verifyEmail(token: string): Promise<AuthSessionResponse> {
  return post('/auth/email/verify', { token });
}

export function checkVerificationToken(token: string): Promise<EmailCheckResponse> {
  return requestJson<EmailCheckResponse>(
    `/auth/email/verify/check?token=${encodeURIComponent(token)}`,
  );
}

export function resendVerification(email?: string): Promise<AuthMessage> {
  return post('/auth/email/resend', email ? { email } : {});
}

export function forgotPassword(email: string): Promise<AuthMessage> {
  return post('/auth/password/forgot', { email });
}

export function checkResetToken(token: string): Promise<EmailCheckResponse> {
  return requestJson<EmailCheckResponse>(
    `/auth/password/reset/check?token=${encodeURIComponent(token)}`,
  );
}

export function resetPassword(token: string, password: string): Promise<ActionResponse> {
  return post('/auth/password/reset', { token, password });
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
  code = '',
): Promise<UserResponse> {
  return post('/auth/password/change', {
    current_password: currentPassword,
    new_password: newPassword,
    code,
  });
}

export function updateProfile(displayName: string): Promise<UserResponse> {
  return post('/auth/profile', { display_name: displayName });
}

export function fetchSessions(): Promise<{ sessions: SessionInfo[] }> {
  return requestJson<{ sessions: SessionInfo[] }>('/auth/sessions');
}

export function revokeSession(sessionId: string): Promise<ActionResponse> {
  return post(`/auth/sessions/${encodeURIComponent(sessionId)}/revoke`);
}

export function revokeOtherSessions(): Promise<ActionResponse> {
  return post('/auth/sessions/revoke-others');
}

export function fetchActivity(): Promise<{ events: SecurityEvent[] }> {
  return requestJson<{ events: SecurityEvent[] }>('/auth/activity');
}

export function setupTwoFactor(password: string): Promise<TotpSetup> {
  return post('/auth/2fa/setup', { password });
}

export function enableTwoFactor(code: string): Promise<TotpEnableResponse> {
  return post('/auth/2fa/enable', { code });
}

export function disableTwoFactor(password: string, code: string): Promise<UserResponse> {
  return post('/auth/2fa/disable', { password, code });
}

export function regenerateRecoveryCodes(
  password: string,
  code: string,
): Promise<{ recovery_codes: string[] }> {
  return post('/auth/2fa/recovery-codes', { password, code });
}

export function googleStartUrl(nextPath: string): string {
  return `${API_BASE}/auth/google/start?next=${encodeURIComponent(nextPath)}`;
}

export async function googleConnectUrl(): Promise<string> {
  const data = await post<{ url: string }>('/auth/google/connect');
  return data.url;
}

export function unlinkGoogle(password: string): Promise<UserResponse> {
  return post('/auth/google/unlink', { password });
}

export function deleteAccount(
  password: string,
  confirmEmail: string,
  code = '',
): Promise<ActionResponse> {
  return post('/auth/account/delete', {
    password,
    confirm_email: confirmEmail,
    code,
  });
}
