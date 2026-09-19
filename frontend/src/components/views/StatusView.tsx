"use client";

import { useAuthedJson } from "@/hooks/useAuthedJson";
import { formatDateTime } from "@/lib/format";
import { useHealth } from "@/providers/HealthProvider";
import { useWs } from "@/providers/WebSocketProvider";

export function StatusView() {
  const health = useHealth();
  const ws = useWs();
  const metrics = useAuthedJson<Record<string, unknown>>("/api/metrics");
  const marketdata = useAuthedJson<Record<string, unknown>>("/api/marketdata/status");

  return (
    <>
      <section className="panel" aria-labelledby="status-health-heading">
        <h2 id="status-health-heading">Health</h2>
        <dl className="field-list">
          <dt>Reachable</dt>
          <dd>{health.reachable ? "Yes" : "No"}</dd>
          <dt>Mode</dt>
          <dd>{health.status}</dd>
          <dt>Trading halted</dt>
          <dd>{health.tradingHalted === null ? "—" : health.tradingHalted ? "Yes" : "No"}</dd>
          <dt>Live trading enabled</dt>
          <dd>{health.liveEnabled === null ? "—" : health.liveEnabled ? "Yes" : "No"}</dd>
          <dt>Auth required</dt>
          <dd>{health.authRequired === null ? "—" : health.authRequired ? "Yes" : "No"}</dd>
          <dt>Version</dt>
          <dd>{health.version ?? "—"}</dd>
          <dt>Last updated</dt>
          <dd>{health.lastUpdatedAt ? formatDateTime(health.lastUpdatedAt) : "—"}</dd>
          <dt>Live feed</dt>
          <dd>{ws.status}</dd>
          <dt>API URL</dt>
          <dd>{health.apiUrl}</dd>
        </dl>
      </section>

      <section className="panel" aria-labelledby="status-marketdata-heading">
        <h2 id="status-marketdata-heading">Market data status</h2>
        {marketdata.error && <p role="alert">{marketdata.error}</p>}
        {marketdata.loading && !marketdata.data ? (
          <p>Loading…</p>
        ) : (
          <pre className="raw-json">{JSON.stringify(marketdata.data, null, 2)}</pre>
        )}
      </section>

      <section className="panel" aria-labelledby="status-metrics-heading">
        <h2 id="status-metrics-heading">Metrics</h2>
        {metrics.error && <p role="alert">{metrics.error}</p>}
        {metrics.loading && !metrics.data ? (
          <p>Loading…</p>
        ) : (
          <pre className="raw-json">{JSON.stringify(metrics.data, null, 2)}</pre>
        )}
      </section>
    </>
  );
}
