import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./api";
import { __resetAuthStoreForTests, getToken, setToken } from "./authStore";
import { setRuntimeConfig } from "./config";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiFetch", () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the Authorization header from the auth store", async () => {
    setToken("secret-token");
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch("/api/thing");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("does not attach a header when skipAuth is set", async () => {
    setToken("secret-token");
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch("/api/health", { skipAuth: true });

    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBeNull();
  });

  it("normalizes the {ok:false,error} tool envelope", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ ok: false, error: { code: "EXEC_310", message: "Proposal expired", suggestion: "Try again" } }, 410)
    );

    await expect(apiFetch("/api/approve-trade")).rejects.toMatchObject({
      status: 410,
      code: "EXEC_310",
      message: "Proposal expired",
      suggestion: "Try again",
    });
  });

  it("normalizes FastAPI's {detail} shape", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Authentication required" }, 401));

    await expect(apiFetch("/api/portfolio")).rejects.toMatchObject({
      status: 401,
      message: "Authentication required",
    });
  });

  it("clears the stored token and reports ApiError on a 401", async () => {
    setToken("secret-token");
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Token has expired" }, 401));

    await expect(apiFetch("/api/portfolio")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
  });

  it("does not clear the token on a non-401 error", async () => {
    setToken("secret-token");
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Admin access required" }, 403));

    await expect(apiFetch("/api/audit/export")).rejects.toMatchObject({ status: 403 });
    expect(getToken()).toBe("secret-token");
  });

  it("normalizes a network failure without throwing an unrecognized error", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiFetch("/api/health")).rejects.toMatchObject({
      status: 0,
      code: "NETWORK_ERROR",
    });
  });

  it("aborts and reports a timeout after the configured duration", async () => {
    vi.mocked(fetch).mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = (init as RequestInit).signal;
          signal?.addEventListener("abort", () => {
            const err = new DOMException("Aborted", "AbortError");
            reject(err);
          });
        })
    );

    await expect(apiFetch("/api/health", { timeoutMs: 5 })).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
    });
  });
});
