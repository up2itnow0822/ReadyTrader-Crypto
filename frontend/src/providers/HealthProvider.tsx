"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import type { HealthResponse } from "@/lib/types";

export type HealthStatus = "unknown" | "paper" | "live";

export const HEALTH_POLL_INTERVAL_MS = 5000;

export interface HealthState {
  /** Never "paper" or "live" while unreachable or still loading -- see AGENTS.md's "unknown never live" rule. */
  status: HealthStatus;
  reachable: boolean;
  /** True once at least one poll has completed (success or failure). */
  loaded: boolean;
  /** True when the data below is from a previous successful poll, not the current one. */
  stale: boolean;
  tradingHalted: boolean | null;
  liveEnabled: boolean | null;
  authRequired: boolean | null;
  version: string | null;
  apiUrl: string;
  lastUpdatedAt: number | null;
  lastError: string | null;
  retry: () => void;
}

const HealthContext = createContext<HealthState | null>(null);

export function HealthProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<HealthResponse | null>(null);
  const [reachable, setReachable] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const poll = useCallback(() => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    apiFetch<HealthResponse>("/api/health", { skipAuth: true })
      .then((data) => {
        setSnapshot(data);
        setReachable(true);
        setLastError(null);
        setLastUpdatedAt(Date.now());
      })
      .catch((err: unknown) => {
        setReachable(false);
        setLastError(err instanceof ApiError ? err.message : "Could not reach the API.");
      })
      .finally(() => {
        setLoaded(true);
        inFlightRef.current = false;
      });
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, HEALTH_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const status: HealthStatus = reachable && snapshot ? snapshot.mode : "unknown";

  const value: HealthState = {
    status,
    reachable,
    loaded,
    stale: !reachable && snapshot !== null,
    tradingHalted: snapshot?.trading_halted ?? null,
    liveEnabled: snapshot?.live_enabled ?? null,
    authRequired: snapshot?.auth_required ?? null,
    version: snapshot?.version ?? null,
    apiUrl: getRuntimeConfig().apiUrl,
    lastUpdatedAt,
    lastError,
    retry: poll,
  };

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthState {
  const ctx = useContext(HealthContext);
  if (!ctx) throw new Error("useHealth must be used within a HealthProvider");
  return ctx;
}
