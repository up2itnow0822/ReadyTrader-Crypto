"use client";

import { useMemo, useState } from "react";

import { useTradeHistory } from "@/hooks/useTradeHistory";
import { formatDateTime, formatQuantity } from "@/lib/format";

const PAGE_SIZE = 25;
const FETCH_LIMIT = 500;

export function HistoryView() {
  const { trades, loading, error } = useTradeHistory(FETCH_LIMIT);
  const [page, setPage] = useState(0);

  const pageCount = Math.max(1, Math.ceil(trades.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageTrades = useMemo(
    () => trades.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE),
    [trades, safePage]
  );

  return (
    <section className="panel" aria-labelledby="history-heading">
      <h2 id="history-heading">Trade history</h2>

      {error && <p role="alert">{error}</p>}

      {loading && trades.length === 0 ? (
        <p>Loading trade history…</p>
      ) : trades.length === 0 ? (
        <p>No trades recorded yet.</p>
      ) : (
        <>
          <table>
            <caption className="sr-only">
              Trade history, page {safePage + 1} of {pageCount}
            </caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Side</th>
                <th scope="col">Symbol</th>
                <th scope="col">Amount</th>
                <th scope="col">Price</th>
                <th scope="col">Total value</th>
              </tr>
            </thead>
            <tbody>
              {pageTrades.map((trade) => (
                <tr key={trade.id}>
                  <td>{formatDateTime(trade.timestamp)}</td>
                  <td>{trade.side}</td>
                  <td>{trade.symbol}</td>
                  <td>{formatQuantity(trade.amount)}</td>
                  <td>{formatQuantity(trade.price)}</td>
                  <td>{formatQuantity(trade.total_value, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <nav className="pagination" aria-label="Trade history pages">
            <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0}>
              Previous
            </button>
            <span>
              Page {safePage + 1} of {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
