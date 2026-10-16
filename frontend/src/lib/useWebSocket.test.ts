import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "@/test/mockWebSocket";

import { __resetAuthStoreForTests, getToken, setToken } from "./authStore";
import { setRuntimeConfig } from "./config";
import { useWebSocket } from "./useWebSocket";

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.reset();
    __resetAuthStoreForTests();
    setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("exchanges the admin JWT by POST and sends only a single-use ticket in the handshake header", async () => {
    setToken("admin-jwt");
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ticket: "short-ticket", expires_in: 30 })));
    vi.stubGlobal("fetch", fetch);
    await act(async () => { renderHook(() => useWebSocket("admin-jwt", true)); });
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/auth/ws-ticket", expect.objectContaining({ method: "POST" }));
    const request = fetch.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer admin-jwt");
    expect(MockWebSocket.latest().url).toBe("ws://api.test/ws");
    expect(MockWebSocket.latest().protocols).toEqual(["readytrader", "ticket.short-ticket"]);
  });

  it("gets a fresh ticket before reconnecting", async () => {
    setToken("admin-jwt");
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticket: "first", expires_in: 30 })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticket: "second", expires_in: 30 })));
    vi.stubGlobal("fetch", fetch);
    await act(async () => { renderHook(() => useWebSocket("admin-jwt", true)); });
    act(() => MockWebSocket.latest().simulateClose(1006));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.latest().protocols).toEqual(["readytrader", "ticket.second"]);
  });

  it("stops on ticket authentication failure and preserves apiFetch logout behavior", async () => {
    setToken("expired-jwt");
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Token has expired" }), { status: 401 }));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useWebSocket("expired-jwt", true));
    await act(async () => {});
    expect(result.current.status).toBe("unauthorized");
    expect(getToken()).toBeNull();
    expect(MockWebSocket.instances).toHaveLength(0);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("backs off and retries ticket issuance after temporary server errors", async () => {
    setToken("admin-jwt");
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Temporarily unavailable" }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticket: "recovered", expires_in: 30 }))));
    const { result } = renderHook(() => useWebSocket("admin-jwt", true));
    await act(async () => {});
    expect(result.current.status).toBe("closed");
    expect(MockWebSocket.instances).toHaveLength(0);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.latest().protocols).toEqual(["readytrader", "ticket.recovered"]);
  });

  it("never opens a socket with a malformed ticket response", async () => {
    setToken("admin-jwt");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ expires_in: 30 }))));
    const { result } = renderHook(() => useWebSocket("admin-jwt", true));
    await act(async () => {});
    expect(result.current.status).toBe("closed");
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("does not connect when an old ticket request finishes after unmount", async () => {
    setToken("admin-jwt");
    let resolve: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
    const { unmount } = renderHook(() => useWebSocket("admin-jwt", true));
    expect(resolve).toBeDefined();
    unmount();
    await act(async () => { resolve?.(new Response(JSON.stringify({ ticket: "late", expires_in: 30 }))); });
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("ignores the previous session's ticket after the token changes", async () => {
    setToken("old-jwt");
    let finishOld: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((done) => { finishOld = done; }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticket: "new-ticket", expires_in: 30 }))));
    const { rerender } = renderHook(({ token }) => useWebSocket(token, true), { initialProps: { token: "old-jwt" } });
    expect(finishOld).toBeDefined();
    setToken("new-jwt");
    await act(async () => { rerender({ token: "new-jwt" }); });
    await act(async () => { finishOld?.(new Response(JSON.stringify({ ticket: "old-ticket", expires_in: 30 }))); });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.latest().protocols).toEqual(["readytrader", "ticket.new-ticket"]);
  });

  it("connects with no query string when there is no token", () => {
    renderHook(() => useWebSocket(null, true));
    expect(MockWebSocket.latest().url).toBe("ws://api.test/ws");
  });

  it("reports open once the socket opens", () => {
    const { result } = renderHook(() => useWebSocket(null, true));
    expect(result.current.status).toBe("connecting");
    act(() => MockWebSocket.latest().simulateOpen());
    expect(result.current.status).toBe("open");
  });

  it("reconnects with backoff after a normal close, and resets attempts on success", () => {
    renderHook(() => useWebSocket(null, true));
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => MockWebSocket.latest().simulateClose(1006));
    // Nothing new yet -- reconnect is scheduled, not immediate.
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1500); // first backoff window is ~1s (+jitter up to 1.5x)
    });
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it("stops retrying and reports unauthorized on a 1008 close", () => {
    const { result } = renderHook(() => useWebSocket(null, true));
    act(() => MockWebSocket.latest().simulateClose(1008));
    expect(result.current.status).toBe("unauthorized");

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1); // no reconnect attempt was made
  });

  it("closes the socket and stops reconnecting on unmount", () => {
    const { unmount } = renderHook(() => useWebSocket(null, true));
    const first = MockWebSocket.latest();
    act(() => unmount());
    expect(first.close).toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("does not connect at all when disabled", () => {
    renderHook(() => useWebSocket(null, false));
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
