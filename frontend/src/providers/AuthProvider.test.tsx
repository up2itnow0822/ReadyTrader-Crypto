import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetAuthStoreForTests } from "@/lib/authStore";
import { MockWebSocket } from "@/test/mockWebSocket";

import { AppProviders } from "./AppProviders";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function healthBody(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    status: "ok",
    mode: "paper",
    timestamp: "2026-01-01T00:00:00Z",
    version: "1.0.0",
    trading_halted: true,
    live_enabled: false,
    auth_required: true,
    ...overrides,
  };
}

describe("AuthProvider (via AppProviders)", () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
    window.sessionStorage.clear();
    __resetAuthStoreForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lets the user straight in, with a dev note, when auth is not required", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/health")) {
          return Promise.resolve(jsonResponse(healthBody({ auth_required: false })));
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      })
    );

    render(
      <AppProviders config={{ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" }}>
        <div data-testid="dashboard-content">Dashboard</div>
      </AppProviders>
    );

    await waitFor(() => expect(screen.getByTestId("dashboard-content")).toBeInTheDocument());
    expect(screen.getByText("auth disabled (dev)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("shows a real login screen when auth is required and there is no token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/health")) return Promise.resolve(jsonResponse(healthBody()));
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      })
    );

    render(
      <AppProviders config={{ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" }}>
        <div data-testid="dashboard-content">Dashboard</div>
      </AppProviders>
    );

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeInTheDocument());
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
  });

  it("falls back to the login screen (not a stuck 'Connecting…' screen) when the API has never once answered", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("network down")))
    );

    render(
      <AppProviders config={{ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" }}>
        <div data-testid="dashboard-content">Dashboard</div>
      </AppProviders>
    );

    // Not stuck on "Connecting to the API…": authRequired is unknown, so this fails
    // closed to the real sign-in form rather than hanging forever or opening the
    // dashboard outright.
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeInTheDocument());
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
  });

  it("shows the server's error message on a bad password and never touches storage", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/health")) return Promise.resolve(jsonResponse(healthBody()));
        if (String(url).includes("/api/auth/login")) return Promise.resolve(jsonResponse({ detail: "Invalid credentials" }, 401));
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      })
    );

    render(
      <AppProviders config={{ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" }}>
        <div data-testid="dashboard-content">Dashboard</div>
      </AppProviders>
    );

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
    expect(window.sessionStorage.getItem("readytrader.auth.token")).toBeNull();
  });

  it("on success stores the token in sessionStorage (never localStorage) and shows the dashboard", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/health")) return Promise.resolve(jsonResponse(healthBody()));
        if (String(url).includes("/api/auth/login")) {
          return Promise.resolve(jsonResponse({ access_token: "jwt-abc", token_type: "bearer", expires_in: 3600 }));
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      })
    );

    render(
      <AppProviders config={{ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" }}>
        <div data-testid="dashboard-content">Dashboard</div>
      </AppProviders>
    );

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByTestId("dashboard-content")).toBeInTheDocument());
    expect(window.sessionStorage.getItem("readytrader.auth.token")).toBe("jwt-abc");
    expect(window.localStorage.getItem("readytrader.auth.token")).toBeNull();
  });
});
