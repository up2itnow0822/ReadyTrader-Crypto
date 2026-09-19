import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HealthPill } from "@/components/HealthPill";
import { setRuntimeConfig } from "@/lib/config";

import { HealthProvider } from "./HealthProvider";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPill() {
  return render(
    <HealthProvider>
      <HealthPill />
    </HealthProvider>
  );
}

describe("HealthProvider / HealthPill", () => {
  beforeEach(() => {
    setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows "Mode unknown" with the unknown class while the first fetch is still in flight', () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {})); // never resolves
    renderPill();

    const pill = screen.getByTestId("health-pill");
    expect(pill).toHaveTextContent("Mode unknown");
    expect(pill.className).toContain("health-pill--unknown");
    expect(pill.className).not.toContain("health-pill--paper");
    expect(pill.className).not.toContain("health-pill--live");
  });

  it('shows "Mode unknown" (never live or paper) when the health fetch rejects', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("network down"));
    renderPill();

    await waitFor(() => expect(screen.getByTestId("health-pill")).toHaveTextContent("Mode unknown"));
    const pill = screen.getByTestId("health-pill");
    expect(pill.className).toContain("health-pill--unknown");
    expect(pill.className).not.toContain("health-pill--live");
    expect(pill.className).not.toContain("health-pill--paper");
  });

  it("shows PAPER once the API reports paper mode", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: "ok",
        mode: "paper",
        timestamp: "2026-01-01T00:00:00Z",
        version: "1.0.0",
        trading_halted: true,
        live_enabled: false,
        auth_required: false,
      })
    );
    renderPill();

    await waitFor(() => expect(screen.getByTestId("health-pill")).toHaveTextContent("PAPER"));
    expect(screen.getByTestId("health-pill").className).toContain("health-pill--paper");
    expect(screen.getByText("Trading halted")).toBeInTheDocument();
  });

  it("shows an unmistakable LIVE treatment when the API reports live mode", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: "ok",
        mode: "live",
        timestamp: "2026-01-01T00:00:00Z",
        version: "1.0.0",
        trading_halted: false,
        live_enabled: true,
        auth_required: true,
      })
    );
    renderPill();

    await waitFor(() => expect(screen.getByTestId("health-pill")).toHaveTextContent("LIVE"));
    expect(screen.getByTestId("health-pill").className).toContain("health-pill--live");
    expect(screen.getByText("Trading active")).toBeInTheDocument();
  });
});
