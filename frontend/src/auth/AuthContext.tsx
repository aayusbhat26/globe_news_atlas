import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ensureCsrfToken,
  fetchAuthConfig,
  fetchMe,
  logout as logoutRequest,
} from '../services/auth';
import { ApiError } from '../services/api';
import type { AuthConfig, AuthUser } from '../types/auth';

const AUTH_PING_KEY = 'gna_auth_ping';

const DEFAULT_CONFIG: AuthConfig = {
  google_enabled: false,
  email_delivery: 'dev',
  environment: 'production',
  password_min_length: 12,
  terms_version: '2026-10',
};

interface AuthContextValue {
  user: AuthUser | null;
  expiresAt: string | null;
  loading: boolean;
  config: AuthConfig;
  refresh: () => Promise<AuthUser | null>;
  signOut: () => Promise<void>;
  setUser: (user: AuthUser) => void;
  notifyAuthChange: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function notifyAuthChange(): void {
  try {
    localStorage.setItem(AUTH_PING_KEY, String(Date.now()));
  } catch {
    /* storage may be unavailable in private mode */
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AuthConfig>(DEFAULT_CONFIG);
  const lastRefresh = useRef(0);

  const refresh = useCallback(async (): Promise<AuthUser | null> => {
    try {
      const me = await fetchMe();
      setUser(me.user);
      setExpiresAt(me.expires_at);
      lastRefresh.current = Date.now();
      return me.user;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        setExpiresAt(null);
      }
      return null;
    }
  }, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [configResult, meResult] = await Promise.allSettled([
        fetchAuthConfig(),
        fetchMe(),
      ]);
      if (!active) return;
      if (configResult.status === 'fulfilled') {
        setConfig(configResult.value);
      }
      if (meResult.status === 'fulfilled') {
        setUser(meResult.value.user);
        setExpiresAt(meResult.value.expires_at);
      } else {
        setUser(null);
      }
      setLoading(false);
      ensureCsrfToken().catch(() => undefined);
    };
    load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!expiresAt) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (remaining <= 0) {
      setUser(null);
      setExpiresAt(null);
      return;
    }
    const timer = window.setTimeout(() => {
      refresh();
    }, Math.min(remaining + 1000, 2_147_000_000));
    return () => window.clearTimeout(timer);
  }, [expiresAt, refresh]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === AUTH_PING_KEY) {
        refresh();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [refresh]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      if (Date.now() - lastRefresh.current < 60_000) return;
      if (!user) return;
      refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refresh, user]);

  const signOut = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setExpiresAt(null);
      notifyAuthChange();
    }
  }, []);

  const updateUser = useCallback((nextUser: AuthUser) => {
    setUser(nextUser);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      expiresAt,
      loading,
      config,
      refresh,
      signOut,
      setUser: updateUser,
      notifyAuthChange,
    }),
    [user, expiresAt, loading, config, refresh, signOut, updateUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}
