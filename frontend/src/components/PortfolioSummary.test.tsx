import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioSummary } from "./PortfolioSummary";

vi.mock("@/hooks/usePortfolio", () => ({
  usePortfolio: () => ({
    portfolio: {
      balances: { USDT: 100, FDUSD: 50, BTC: 0.1 },
      metrics: { daily_pnl_pct: -0.01, drawdown_pct: 0.02, max_drawdown_pct: 0.12 },
    },
    loading: false,
    error: null,
    refresh: () => {},
  }),
}));

describe("PortfolioSummary", () => {
  it("labels the current drawdown and the record separately", () => {
    render(<PortfolioSummary />);
    expect(screen.getByText("Drawdown from peak").nextSibling?.textContent).toBe("2.00%");
    expect(screen.getByText("Max drawdown").nextSibling?.textContent).toBe("12.00%");
  });

  it("counts every USD stablecoin the server values at 1 USD", () => {
    render(<PortfolioSummary />);
    expect(screen.getByText("Stablecoin balance").nextSibling?.textContent).toBe("150 USD");
  });
});
