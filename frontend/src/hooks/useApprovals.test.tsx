import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setRuntimeConfig } from "@/lib/config";
import type { PendingApproval } from "@/lib/types";

vi.mock("@/providers/WebSocketProvider", () => ({
  useWs: () => ({ status: "open", subscribe: () => () => {} }),
}));

import { OUTCOME_GRACE_MS, useApprovals } from "./useApprovals";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const APPROVAL: PendingApproval = {
  request_id: "req-1",
  kind: "place_cex_order",
  created_at: 1_700_000_000,
  expires_at: 1_900_000_000,
  summary: { symbol: "BTC/USDT", side: "buy", amount: 0.01, order_type: "limit", price: 50000, exchange: "binance", market_type: "spot" },
};

describe("useApprovals", () => {
  beforeEach(() => {
    setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function mockFetchWithApproveResponse(approveResponse: () => Promise<Response>) {
    let listCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/pending-approvals")) {
          listCalls += 1;
          return Promise.resolve(jsonResponse({ pending: listCalls === 1 ? [APPROVAL] : [] }));
        }
        if (String(url).includes("/api/approve-trade")) {
          return approveResponse();
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      })
    );
  }

  it("loads the pending list", async () => {
    mockFetchWithApproveResponse(() => Promise.resolve(jsonResponse({ ok: true })));
    const { result } = renderHook(() => useApprovals());

    await waitFor(() => expect(result.current.approvals).toHaveLength(1));
    expect(result.current.approvals[0].request_id).toBe("req-1");
  });

  it("sends exactly one approve request even if act() is called twice back-to-back", async () => {
    let approveCallCount = 0;
    let resolveApprove: (() => void) | null = null;
    mockFetchWithApproveResponse(
      () =>
        new Promise((resolve) => {
          approveCallCount += 1;
          resolveApprove = () => resolve(jsonResponse({ ok: true, data: {} }));
        })
    );

    const { result } = renderHook(() => useApprovals());
    await waitFor(() => expect(result.current.approvals).toHaveLength(1));

    let firstCall!: Promise<void>;
    let secondCall!: Promise<void>;
    act(() => {
      firstCall = result.current.act("req-1", true);
      secondCall = result.current.act("req-1", true); // simulates a double click / double Enter
    });

    expect(approveCallCount).toBe(1);

    await act(async () => {
      resolveApprove?.();
      await firstCall;
      await secondCall;
    });
  });

  const statusCases: Array<{ status: number; body: unknown; expectSubstring: string }> = [
    { status: 403, body: { ok: false, error: { code: "AUTH_604", message: "not allowed" } }, expectSubstring: "Not allowed" },
    { status: 404, body: { ok: false, error: { code: "EXEC_309", message: "unknown" } }, expectSubstring: "no longer exists" },
    { status: 409, body: { ok: false, error: { code: "EXEC_308", message: "already executed" } }, expectSubstring: "already handled" },
    { status: 410, body: { ok: false, error: { code: "EXEC_310", message: "expired" } }, expectSubstring: "expired" },
    {
      status: 422,
      body: { ok: false, error: { code: "insufficient_funds", message: "Insufficient fund. Have 0 USDT, need 500" } },
      expectSubstring: "refused",
    },
  ];

  for (const { status, body, expectSubstring } of statusCases) {
    it(`maps HTTP ${status} to a message containing "${expectSubstring}"`, async () => {
      mockFetchWithApproveResponse(() => Promise.resolve(jsonResponse(body, status)));
      const { result } = renderHook(() => useApprovals());
      await waitFor(() => expect(result.current.approvals).toHaveLength(1));

      await act(async () => {
        await result.current.act("req-1", true);
      });

      await waitFor(() => expect(result.current.outcomes["req-1"]).toBeDefined());
      expect(result.current.outcomes["req-1"].kind).toBe("error");
      expect(result.current.outcomes["req-1"].message.toLowerCase()).toContain(expectSubstring.toLowerCase());
    });
  }

  it("maps a network error to a network-error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/pending-approvals")) {
          return Promise.resolve(jsonResponse({ pending: [APPROVAL] }));
        }
        if (String(url).includes("/api/approve-trade")) {
          return Promise.reject(new TypeError("network down"));
        }
        return Promise.reject(new Error("unexpected"));
      })
    );
    const { result } = renderHook(() => useApprovals());
    await waitFor(() => expect(result.current.approvals).toHaveLength(1));

    await act(async () => {
      await result.current.act("req-1", true);
    });

    await waitFor(() => expect(result.current.outcomes["req-1"]).toBeDefined());
    expect(result.current.outcomes["req-1"].message.toLowerCase()).toContain("network");
  });

  it("keeps the executed card (with its outcome) visible for a grace period after it drops off the server's pending list, then removes it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockFetchWithApproveResponse(() =>
      Promise.resolve(
        jsonResponse({
          ok: true,
          data: { fill: { side: "buy", symbol: "BTC/USDT", amount: 0.01, price: 50000, total_value: 500, quote: "USDT" } },
        })
      )
    );
    const { result } = renderHook(() => useApprovals());
    await waitFor(() => expect(result.current.approvals).toHaveLength(1));

    await act(async () => {
      await result.current.act("req-1", true);
    });

    // The very next poll (fired in act()'s `finally`) already reports it gone from the
    // server's pending list -- but the card must still be visible, with its outcome, in
    // the meantime.
    expect(result.current.approvals).toHaveLength(1);
    expect(result.current.outcomes["req-1"]?.kind).toBe("success");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(OUTCOME_GRACE_MS + 1000);
    });

    expect(result.current.approvals).toHaveLength(0);
    vi.useRealTimers();
  });

  it("shows executed fill numbers on a 200 success", async () => {
    mockFetchWithApproveResponse(() =>
      Promise.resolve(
        jsonResponse({
          ok: true,
          data: { fill: { side: "buy", symbol: "BTC/USDT", amount: 0.01, price: 50000, total_value: 500, quote: "USDT" } },
        })
      )
    );
    const { result } = renderHook(() => useApprovals());
    await waitFor(() => expect(result.current.approvals).toHaveLength(1));

    await act(async () => {
      await result.current.act("req-1", true);
    });

    await waitFor(() => expect(result.current.outcomes["req-1"]).toBeDefined());
    expect(result.current.outcomes["req-1"].kind).toBe("success");
    expect(result.current.outcomes["req-1"].message).toContain("50,000");
  });
});
