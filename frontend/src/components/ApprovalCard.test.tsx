import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setRuntimeConfig } from "@/lib/config";
import type { PendingApproval } from "@/lib/types";
import { HealthProvider } from "@/providers/HealthProvider";

import { ApprovalCard } from "./ApprovalCard";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function healthBody(mode: "paper" | "live") {
  return {
    status: "ok",
    mode,
    timestamp: "2026-01-01T00:00:00Z",
    version: "1.0.0",
    trading_halted: mode === "paper",
    live_enabled: mode === "live",
    auth_required: false,
  };
}

const BASE_APPROVAL: PendingApproval = {
  request_id: "req-1",
  kind: "place_cex_order",
  created_at: Math.floor(Date.now() / 1000) - 5,
  expires_at: Math.floor(Date.now() / 1000) + 300,
  summary: {
    symbol: "BTC/USDT",
    side: "buy",
    amount: 0.01,
    order_type: "limit",
    price: 50000,
    exchange: "binance",
    market_type: "spot",
  },
};

function renderCard(approval: PendingApproval, mode: "paper" | "live" = "paper", onAct = vi.fn()) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(healthBody(mode))));
  setRuntimeConfig({ apiUrl: "http://api.test", wsUrl: "ws://api.test/ws" });
  return {
    onAct,
    ...render(
      <HealthProvider>
        <ul>
          <ApprovalCard approval={approval} pending={false} onAct={onAct} />
        </ul>
      </HealthProvider>
    ),
  };
}

describe("ApprovalCard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("builds the human sentence from the summary", () => {
    renderCard(BASE_APPROVAL);
    expect(screen.getByText("Buy 0.01 BTC/USDT at 50,000 (limit) on binance spot")).toBeInTheDocument();
  });

  it("disables Approve/Reject once the countdown reaches zero", () => {
    vi.useFakeTimers();
    const expired: PendingApproval = { ...BASE_APPROVAL, expires_at: Math.floor(Date.now() / 1000) + 1 };
    renderCard(expired);

    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("opens a confirm dialog that restates the trade and the current mode (PAPER)", async () => {
    const user = userEvent.setup();
    renderCard(BASE_APPROVAL, "paper");

    await user.click(screen.getByRole("button", { name: "Approve" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Buy 0.01 BTC/USDT at 50,000 (limit) on binance spot");
    await waitFor(() => expect(dialog).toHaveTextContent("PAPER"));
    expect(screen.getByRole("button", { name: "Approve and execute" })).toBeInTheDocument();
    // Initial focus goes to Cancel, not the executing action.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it('shows "LIVE — real funds" in the dialog when the API reports live mode', async () => {
    const user = userEvent.setup();
    renderCard(BASE_APPROVAL, "live");

    await user.click(screen.getByRole("button", { name: "Approve" }));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("LIVE — real funds"));
  });

  it("Esc cancels the dialog without calling onAct", async () => {
    const user = userEvent.setup();
    const { onAct } = renderCard(BASE_APPROVAL);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onAct).not.toHaveBeenCalled();
  });

  it("calls onAct exactly once when the confirm button is clicked", async () => {
    const user = userEvent.setup();
    const { onAct } = renderCard(BASE_APPROVAL);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(await screen.findByRole("button", { name: "Approve and execute" }));

    expect(onAct).toHaveBeenCalledTimes(1);
    expect(onAct).toHaveBeenCalledWith("req-1", true);
  });

  it("renders an XSS rationale as inert plain text (no injected <img>)", () => {
    const swap: PendingApproval = {
      request_id: "req-xss",
      kind: "swap_tokens",
      created_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 300,
      summary: {
        from_token: "ETH",
        to_token: "USDC",
        amount: 1.5,
        chain: "ethereum",
        rationale: '<img src=x onerror=alert(1)>',
      },
    };
    const { container } = renderCard(swap);

    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
