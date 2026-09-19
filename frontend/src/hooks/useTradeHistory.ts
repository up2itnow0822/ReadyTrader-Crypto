"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import type { TradeHistoryResponse, TradeRecord } from "@/lib/types";

export interface UseTradeHistoryResult {
  trades: TradeRecord[];
  mode: string | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/** `limit` is the server-side cap; pagination on top of the returned array is client-side. */
export function useTradeHistory(limit: number): UseTradeHistoryResult {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    apiFetch<TradeHistoryResponse>(`/api/trades/history?limit=${limit}`)
      .then((data) => {
        setTrades(Array.isArray(data.trades) ? data.trades : []);
        setMode(data.mode ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Could not load trade history.");
      })
      .finally(() => setLoading(false));
  }, [limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { trades, mode, loading, error, refresh };
}
