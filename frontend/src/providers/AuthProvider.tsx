"use client";

import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import { announce } from "@/lib/announce";
import { ApiError, apiFetch } from "@/lib/api";
import { clearToken, getToken, setToken as storeSetToken, subscribeToken } from "@/lib/authStore";
import type { LoginResponse } from "@/lib/types";

import { useHealth } from "./HealthProvider";

export type AuthPhase = "checking" | "no-auth" | "unauthenticated" | "authenticated";

export interface AuthState {
  phase: AuthPhase;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  loginError: string | null;
  loginPending: boolean;
  /** Set when the previous session ended because the token expired or was rejected, not by clicking Logout. */
  sessionNotice: string | null;
}

const AuthContext = createContext<AuthState | null>(null);

const getServerToken = () => null;

export function AuthProvider({ children }: { children: ReactNode }) {
  const health = useHealth();
  // The token lives in the authStore module (memory + sessionStorage), not React
  // state; useSyncExternalStore is the correct way to read an external store like
  // this one, and it handles server/client hydration without an extra effect.
  const token = useSyncExternalStore((onChange) => subscribeToken(() => onChange()), getToken, getServerToken);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginPending, setLoginPending] = useState(false);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  // Subscribing to an external system (the auth store) and calling setState from its
  // callback -- not synchronously in the effect body -- is exactly the pattern React
  // recommends for this.
  useEffect(() => {
    return subscribeToken((next, reason) => {
      if (next === null && reason === "expired") {
        setSessionNotice("Your session expired. Please sign in again.");
      }
    });
  }, []);

  const phase: AuthPhase = (() => {
    if (!health.loaded) return "checking";
    if (health.authRequired === false) return "no-auth";
    // authRequired is also `null` when the API has never once answered (health.loaded
    // is "an attempt finished", not "it succeeded"). Treat that the same as "auth is
    // required", the fail-closed default: otherwise an operator whose first load
    // happens to land during an outage would be stuck on "Connecting to the API…"
    // forever, with no way to even reach the sign-in form once it recovers.
    return token ? "authenticated" : "unauthenticated";
  })();

  const login = useCallback(async (username: string, password: string) => {
    setLoginPending(true);
    setLoginError(null);
    try {
      const data = await apiFetch<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: { username, password },
        skipAuth: true,
      });
      storeSetToken(data.access_token);
      setSessionNotice(null);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Login failed. Please try again.";
      setLoginError(message);
      throw err;
    } finally {
      setLoginPending(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearToken("manual");
    setSessionNotice(null);
    announce("Signed out.");
  }, []);

  const value: AuthState = {
    phase,
    login,
    logout,
    loginError,
    loginPending,
    sessionNotice,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
