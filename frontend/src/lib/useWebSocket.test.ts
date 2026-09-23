import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "@/test/mockWebSocket";

import { setRuntimeConfig } from "./config";
import { useWebSocket } from "./useWebSocket";

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.reset();
    setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("connects with a ?token= query string when a token is provided", () => {
    renderHook(() => useWebSocket("abc123", true));
    expect(MockWebSocket.latest().url).toBe("ws://api.test/ws?token=abc123");
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
