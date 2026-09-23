"use client";

import { useHealth } from "@/providers/HealthProvider";

const STATUS_LABEL: Record<string, string> = {
  unknown: "Mode unknown",
  paper: "PAPER",
  live: "LIVE",
};

/**
 * The one persistent mode indicator. Renders "Mode unknown" in a neutral grey style
 * whenever the API is unreachable or hasn't answered yet -- it must never fall back to
 * paper or live styling in that state (a wrong "LIVE" default here is the dangerous
 * direction to be wrong in).
 */
export function HealthPill() {
  const health = useHealth();
  const label = STATUS_LABEL[health.status] ?? "Mode unknown";
  const className = `health-pill health-pill--${health.status}`;

  return (
    <div className="health-pill-group">
      <span className={className} data-testid="health-pill">
        {/* Color is never the only signal: the text itself always states the mode. */}
        {label}
      </span>
      <span className={`halt-pill halt-pill--${health.tradingHalted === false ? "active" : "halted"}`}>
        {health.tradingHalted === false ? "Trading active" : "Trading halted"}
      </span>
      {health.stale && (
        <span className="stale-pill" title="Showing the last data received before the API stopped responding">
          Stale
        </span>
      )}
    </div>
  );
}
