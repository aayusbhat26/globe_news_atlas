export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  has_password: boolean;
  totp_enabled: boolean;
  google_linked: boolean;
  recovery_codes_remaining: number;
  created_at: string | null;
  last_login_at: string | null;
}

export interface AuthConfig {
  google_enabled: boolean;
  email_delivery: 'resend' | 'smtp' | 'dev' | string;
  environment: string;
  password_min_length: number;
  terms_version: string;
}

export interface AuthSessionResponse {
  user: AuthUser;
  expires_at: string;
  two_factor_required: false;
}

export interface TwoFactorChallenge {
  two_factor_required: true;
  challenge_token: string;
  expires_in: number;
  email_masked: string;
}

export type LoginResponse = AuthSessionResponse | TwoFactorChallenge;

export interface MeResponse {
  user: AuthUser | null;
  expires_at: string | null;
}

export interface AuthMessage {
  status: string;
  message: string;
  dev_verification_link?: string | null;
  dev_reset_link?: string | null;
}

export interface EmailCheckResponse {
  valid: boolean;
  email_masked: string | null;
  expired: boolean;
}

export interface SessionInfo {
  id: string;
  current: boolean;
  device: string;
  ip: string | null;
  auth_method: string;
  remember: boolean;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
}

export interface SecurityEvent {
  event: string;
  ip: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_data_uri: string | null;
  expires_in: number;
}

export interface TotpEnableResponse {
  user: AuthUser;
  recovery_codes: string[];
}

export interface UserResponse {
  user: AuthUser;
  message: string;
}

export interface ActionResponse {
  status: string;
  message: string;
}
