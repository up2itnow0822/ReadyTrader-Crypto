"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import type { PaperPortfolioResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 15000;

export interface UsePortfolioResult {
  portfolio: PaperPortfolioResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function usePortfolio(): UsePortfolioResult {
  const [portfolio, setPortfolio] = useState<PaperPortfolioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    apiFetch<PaperPortfolioResponse>("/api/portfolio")
      .then((data) => {
        setPortfolio(data);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Could not load the portfolio.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { portfolio, loading, error, refresh };
}
