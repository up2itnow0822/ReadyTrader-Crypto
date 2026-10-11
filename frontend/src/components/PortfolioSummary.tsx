"use client";

import { usePortfolio } from "@/hooks/usePortfolio";
import { formatPercent, formatQuantity, toFiniteNumber } from "@/lib/format";

// The USD stablecoins the server values at 1 USD (paper_engine.USD_STABLES).
const STABLE_ASSETS = new Set(["USD", "USDT", "USDC", "DAI", "BUSD", "FDUSD", "TUSD", "USDP"]);

export function PortfolioSummary() {
  const { portfolio, loading, error } = usePortfolio();

  const balances = portfolio?.balances ?? {};
  const assets = Object.keys(balances).sort();
  const stableTotal = assets.reduce((sum, asset) => {
    if (!STABLE_ASSETS.has(asset.toUpperCase())) return sum;
    const value = toFiniteNumber(balances[asset]);
    return sum + (value ?? 0);
  }, 0);
  const hasNonStable = assets.some((asset) => !STABLE_ASSETS.has(asset.toUpperCase()));

  return (
    <section className="panel" aria-labelledby="portfolio-heading">
      <h2 id="portfolio-heading">Portfolio</h2>

      {error && <p role="alert">{error}</p>}
      {loading && !portfolio ? (
        <p>Loading portfolio…</p>
      ) : (
        <>
          <div className="grid-2">
            <div className="stat">
              <span className="stat__label">Stablecoin balance</span>
              <span className="stat__value">{formatQuantity(stableTotal, 2)} USD</span>
            </div>
            <div className="stat">
              <span className="stat__label">Daily PnL</span>
              <span className="stat__value">{formatPercent(portfolio?.metrics.daily_pnl_pct)}</span>
            </div>
            <div className="stat">
              <span className="stat__label">Drawdown from peak</span>
              <span className="stat__value">{formatPercent(portfolio?.metrics.drawdown_pct)}</span>
            </div>
            <div className="stat">
              <span className="stat__label">Max drawdown</span>
              <span className="stat__value">{formatPercent(portfolio?.metrics.max_drawdown_pct)}</span>
            </div>
          </div>

          {hasNonStable && (
            <p className="stat__label" style={{ marginTop: "0.75rem" }}>
              Non-stablecoin balances are shown at their raw quantity below; no live price feed is wired up
              yet to convert them to a USD total.
            </p>
          )}

          {assets.length > 0 ? (
            <table style={{ marginTop: "0.75rem" }}>
              <caption className="sr-only">Balances by asset</caption>
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Amount</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => (
                  <tr key={asset}>
                    <td>{asset}</td>
                    <td>{formatQuantity(balances[asset])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>No balances yet.</p>
          )}
        </>
      )}
    </section>
  );
}
