"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { announce } from "@/lib/announce";
import { ApiError, apiFetch } from "@/lib/api";
import { describeApprovalError, describeApprovalSuccess, describeRejectSuccess } from "@/lib/approvalOutcome";
import type { ApproveTradeSuccess, PendingApproval, PendingApprovalsResponse, RejectTradeResponse } from "@/lib/types";
import { useWs } from "@/providers/WebSocketProvider";

export const APPROVALS_POLL_INTERVAL_MS = 5000;

// A proposal stops being "pending" server-side the instant it is confirmed -- whether
// that confirmation went on to execute, fail, or get rejected. The very next poll
// (scheduled in `act()`'s `finally`) would otherwise make its card, and the outcome
// message on it, disappear before the operator has had a chance to read it. This is
// how long a just-acted-on card keeps rendering (with its outcome) after that.
export const OUTCOME_GRACE_MS = 6000;

export interface ApprovalOutcome {
  kind: "success" | "error";
  message: string;
}

export interface UseApprovalsResult {
  approvals: PendingApproval[];
  loading: boolean;
  error: string | null;
  outcomes: Record<string, ApprovalOutcome>;
  isPending: (requestId: string) => boolean;
  act: (requestId: string, approve: boolean) => Promise<void>;
  refresh: () => void;
}

export function useApprovals(): UseApprovalsResult {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, ApprovalOutcome>>({});
  const [, forceRender] = useState(0);
  const pendingIdsRef = useRef<Set<string>>(new Set());
  const approvalsRef = useRef<PendingApproval[]>([]);
  // Approvals the operator just acted on, kept rendered (with their outcome) for
  // OUTCOME_GRACE_MS after the server stops listing them as pending. Real state (not a
  // ref) because `visibleApprovals` below reads it during render.
  const [completed, setCompleted] = useState<Record<string, PendingApproval>>({});
  // Timer handles for `completed`'s entries. A ref, not state: only ever read/written
  // from effects and event handlers, never during render.
  const completedTimeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const ws = useWs();

  useEffect(() => {
    approvalsRef.current = approvals;
  }, [approvals]);

  useEffect(
    () => () => {
      for (const timeoutId of completedTimeoutsRef.current.values()) clearTimeout(timeoutId);
    },
    []
  );

  const refresh = useCallback(() => {
    apiFetch<PendingApprovalsResponse>("/api/pending-approvals")
      .then((data) => {
        setApprovals(data.pending);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Could not load approvals.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, APPROVALS_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // The server's own pending list, plus any just-acted-on approval still in its grace
  // period -- see OUTCOME_GRACE_MS above.
  const visibleApprovals = useMemo(() => {
    const seen = new Set(approvals.map((a) => a.request_id));
    const stillFading = Object.values(completed).filter((a) => !seen.has(a.request_id));
    return stillFading.length ? [...approvals, ...stillFading] : approvals;
  }, [approvals, completed]);

  // Belt-and-braces: also refresh immediately on any WS message that looks like an
  // approval-lifecycle event, if/when the server ever emits one.
  useEffect(
    () =>
      ws.subscribe((data) => {
        if (data && typeof data === "object") {
          const type = (data as Record<string, unknown>).type;
          if (typeof type === "string" && type.toLowerCase().includes("approval")) {
            refresh();
          }
        }
      }),
    [ws, refresh]
  );

  const isPending = useCallback((requestId: string) => pendingIdsRef.current.has(requestId), []);

  const act = useCallback(
    async (requestId: string, approve: boolean) => {
      // Synchronous guard: a second click/Enter before this line's caller re-renders
      // still sees the id already in the set and is dropped -- exactly one request.
      if (pendingIdsRef.current.has(requestId)) return;
      pendingIdsRef.current.add(requestId);
      forceRender((v) => v + 1);
      setOutcomes((prev) => {
        if (!(requestId in prev)) return prev;
        const next = { ...prev };
        delete next[requestId];
        return next;
      });

      // Snapshot the approval now, while it is still known: once confirmed it drops out
      // of the server's pending list on the very next refresh (see `finally` below),
      // so this is the last point this hook has the object to keep rendering.
      const snapshot = approvalsRef.current.find((item) => item.request_id === requestId) ?? null;
      const keepVisibleForGracePeriod = () => {
        if (!snapshot) return;
        const existingTimeout = completedTimeoutsRef.current.get(requestId);
        if (existingTimeout) clearTimeout(existingTimeout);
        setCompleted((prev) => ({ ...prev, [requestId]: snapshot }));
        const timeoutId = setTimeout(() => {
          completedTimeoutsRef.current.delete(requestId);
          setCompleted((prev) => {
            if (!(requestId in prev)) return prev;
            const next = { ...prev };
            delete next[requestId];
            return next;
          });
        }, OUTCOME_GRACE_MS);
        completedTimeoutsRef.current.set(requestId, timeoutId);
      };

      try {
        if (approve) {
          const result = await apiFetch<ApproveTradeSuccess>("/api/approve-trade", {
            method: "POST",
            body: { request_id: requestId, approve: true },
          });
          const message = describeApprovalSuccess(result.data);
          setOutcomes((prev) => ({ ...prev, [requestId]: { kind: "success", message } }));
          announce(message);
        } else {
          await apiFetch<RejectTradeResponse>("/api/approve-trade", {
            method: "POST",
            body: { request_id: requestId, approve: false },
          });
          const message = describeRejectSuccess();
          setOutcomes((prev) => ({ ...prev, [requestId]: { kind: "success", message } }));
          announce(message);
        }
        keepVisibleForGracePeriod();
      } catch (err) {
        const message = err instanceof ApiError ? describeApprovalError(err) : "Something went wrong.";
        setOutcomes((prev) => ({ ...prev, [requestId]: { kind: "error", message } }));
        announce(message);
        keepVisibleForGracePeriod();
      } finally {
        pendingIdsRef.current.delete(requestId);
        forceRender((v) => v + 1);
        refresh(); // always refresh the list afterwards, on success or failure
      }
    },
    [refresh]
  );

  return { approvals: visibleApprovals, loading, error, outcomes, isPending, act, refresh };
}
