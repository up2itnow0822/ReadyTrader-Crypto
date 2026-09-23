"use client";

import { useHealth } from "@/providers/HealthProvider";

/** A persistent, dismiss-less banner while the API is unreachable. No close button on purpose. */
export function HealthBanner() {
  const health = useHealth();

  if (health.reachable) return null;
  if (!health.loaded) return null; // avoid a flash of "unreachable" before the first attempt finishes

  return (
    <div className="health-banner" role="alert" data-testid="health-banner">
      <span>
        Can&apos;t reach the API at <code>{health.apiUrl}</code>
        {health.lastError ? `: ${health.lastError}` : "."}
      </span>
      <button type="button" onClick={health.retry}>
        Retry
      </button>
    </div>
  );
}
