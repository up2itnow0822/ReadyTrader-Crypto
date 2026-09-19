"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useTradeHistory } from "@/hooks/useTradeHistory";
import { formatDateTime, formatQuantity, toFiniteNumber } from "@/lib/format";

interface ChartPoint {
  label: string;
  price: number;
}

/**
 * Fill price over time from real executed trades (`/api/trades/history`). Each point is
 * independent -- unlike a running/cumulative total, one bad row cannot poison the rest
 * of the series with NaN.
 */
export function PriceChart() {
  const { trades, loading, error } = useTradeHistory(100);

  const points: ChartPoint[] = trades
    .slice()
    .reverse() // API returns newest-first; charts read left-to-right, oldest-first
    .map((trade) => {
      const price = toFiniteNumber(trade.price);
      if (price === null) return null;
      return { label: formatDateTime(trade.timestamp), price };
    })
    .filter((point): point is ChartPoint => point !== null);

  return (
    <section className="panel" aria-labelledby="price-chart-heading">
      <h2 id="price-chart-heading">Fill price history</h2>
      {error && <p role="alert">{error}</p>}
      {loading && points.length === 0 ? (
        <p>Loading chart…</p>
      ) : points.length === 0 ? (
        <p>No executed trades yet.</p>
      ) : (
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="label" hide />
              <YAxis
                width={70}
                tickFormatter={(value: number) => formatQuantity(value, 2)}
                stroke="var(--color-text-muted)"
              />
              <Tooltip
                formatter={(value) => formatQuantity(typeof value === "number" ? value : Number(value))}
                labelFormatter={(label) => String(label ?? "")}
              />
              <Line type="monotone" dataKey="price" stroke="var(--color-accent)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
