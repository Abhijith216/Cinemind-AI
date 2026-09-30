"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError, setAuthToken, type UserOut } from "@/lib/api";

/**
 * Client-side auth for CineMind.
 *
 * Token storage: `localStorage` under "cinemind.token". For this app that is
 * the right tradeoff — the backend has no cookie/session endpoint and no XSS-
 * hardened CSP yet; localStorage keeps the SPA simple across reloads. The
 * known cost: any XSS can read the token. When we add a backend session/
 * refresh flow, swap storage here for an HttpOnly cookie without touching
 * call sites — everything goes through this provider.
 *
 * Identity is never trusted from storage alone: on load we call
 * GET /api/auth/me with the stored token. If the token is expired or the
 * user was deleted, we clear the session and treat the visitor as signed out.
 */

const TOKEN_STORAGE_KEY = "cinemind.token";

interface AuthContextValue {
  /** Signed-in user, or null when signed out. */
  user: UserOut | null;
  /** True once the stored token (if any) has been validated against /me. */
  hydrated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null; // storage unavailable (private mode etc.) — stay signed out
  }
}

function storeToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* non-fatal: session just won't survive reloads */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Validate any stored token on mount: /me is the source of truth.
  useEffect(() => {
    const token = readStoredToken();
    setAuthToken(token);
    if (!token) {
      setHydrated(true);
      return;
    }
    let cancelled = false;
    api.auth
      .me()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) {
          storeToken(null);
          setAuthToken(null);
        }
      })
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const token = await api.auth.login(email, password);
    storeToken(token.access_token);
    setAuthToken(token.access_token);
    setUser(token.user);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const token = await api.auth.register(email, password);
    storeToken(token.access_token);
    setAuthToken(token.access_token);
    setUser(token.user);
  }, []);

  const logout = useCallback(() => {
    storeToken(null);
    setAuthToken(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, hydrated, login, register, logout }),
    [user, hydrated, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}

/** A request failed because the JWT is expired/invalid → end the session. */
export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
