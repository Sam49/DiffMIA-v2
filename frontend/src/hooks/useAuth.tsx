import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api, clearAuth, getStoredUser, setAuth, setStoredUser, type UserShape } from "../services/api";

interface AuthState {
  user: UserShape | null;
  login: (username: string, password: string) => Promise<UserShape>;
  register: (username: string, email: string, password: string) => Promise<{ user: UserShape; verified: boolean }>;
  loginWithGoogleToken: (token: string) => Promise<UserShape>;
  /** Re-read the current account (e.g. after linking a Google identity). */
  refreshUser: () => Promise<UserShape>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserShape | null>(() => getStoredUser<UserShape>());

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login(username, password);
    setAuth(response.access_token);
    setStoredUser(response.user);
    setUser(response.user);
    return response.user;
  }, []);

  const register = useCallback(async (username: string, email: string, password: string) => {
    const response = await api.register(username, email, password);
    if (response.verification?.required) {
      // Email verification outstanding: the session token would be rejected
      // by every endpoint, so don't establish one.
      return { user: response.user, verified: false };
    }
    setAuth(response.access_token);
    setStoredUser(response.user);
    setUser(response.user);
    return { user: response.user, verified: true };
  }, []);

  const loginWithGoogleToken = useCallback(async (handoffToken: string) => {
    // Exchange the one-time fragment token for a normal session token.
    setAuth(handoffToken);
    try {
      const response = await api.oauthExchange(handoffToken);
      setAuth(response.access_token);
      setStoredUser(response.user);
      setUser(response.user);
      return response.user;
    } catch (err) {
      clearAuth();
      throw err;
    }
  }, []);

  const refreshUser = useCallback(async () => {
    const fresh = await api.me();
    setStoredUser(fresh);
    setUser(fresh);
    return fresh;
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, login, register, loginWithGoogleToken, refreshUser, logout }),
    [user, login, register, loginWithGoogleToken, refreshUser, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useCan(action: "write" | "admin"): boolean {
  const { user } = useAuth();
  if (!user) return false;
  if (action === "admin") return user.role === "ADMIN";
  return user.role === "ADMIN" || user.role === "RESEARCHER";
}
