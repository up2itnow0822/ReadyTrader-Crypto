"use client";

import { useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";

export interface UseAuthedJsonResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface State<T> {
  path: string;
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** Small one-shot fetch for read-only status/metrics blocks that don't need polling. */
export function useAuthedJson<T>(path: string): UseAuthedJsonResult<T> {
  const [state, setState] = useState<State<T>>({ path, data: null, loading: true, error: null });

  // Adjust state during render when `path` changes, rather than in an effect: this is
  // the pattern React recommends for resetting state in response to a prop change, and
  // it avoids the extra render an effect-based reset would cost.
  if (state.path !== path) {
    setState({ path, data: null, loading: true, error: null });
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch<T>(path)
      .then((result) => {
        if (cancelled) return;
        setState((prev) => (prev.path === path ? { ...prev, data: result, error: null, loading: false } : prev));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Request failed.";
        setState((prev) => (prev.path === path ? { ...prev, error: message, loading: false } : prev));
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return { data: state.data, loading: state.loading, error: state.error };
}
