/**
 * Null-safe formatters used everywhere numbers/dates are rendered. Every function here
 * returns a plain string and never throws; anything it cannot make sense of becomes the
 * "—" placeholder instead of `NaN`, `undefined`, or `[object Object]`.
 */

export const MISSING_VALUE = "—";

export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function formatCurrency(value: unknown, currency = "USD"): string {
  const n = toFiniteNumber(value);
  if (n === null) return MISSING_VALUE;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return MISSING_VALUE;
  }
}

/** Quantities (order sizes, balances) can be tiny -- show up to 8 decimal places. */
export function formatQuantity(value: unknown, maxFractionDigits = 8): string {
  const n = toFiniteNumber(value);
  if (n === null) return MISSING_VALUE;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: 0,
  }).format(n);
}

/** `value` is a fraction (0.05 -> "5.00%"), matching what the API returns (daily_pnl_pct, drawdown_pct). */
export function formatPercent(value: unknown, fractionDigits = 2): string {
  const n = toFiniteNumber(value);
  if (n === null) return MISSING_VALUE;
  return `${(n * 100).toFixed(fractionDigits)}%`;
}

const SQLITE_TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$/;

function coerceToDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === "") return null;
  let date: Date;
  if (typeof value === "number") {
    // Heuristic: epoch seconds (health/approvals) vs epoch milliseconds.
    date = new Date(Math.abs(value) < 1e12 ? value * 1000 : value);
  } else if (typeof value === "string") {
    // SQLite's CURRENT_TIMESTAMP has no timezone suffix and is UTC; without the "Z" some
    // JS engines parse it as local time. Make it explicit.
    const normalized = SQLITE_TIMESTAMP.test(value) ? `${value.replace(" ", "T")}Z` : value;
    date = new Date(normalized);
  } else {
    return null;
  }
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Date + time-of-day + timezone label, e.g. "Jan 5, 2026, 3:04:05 PM GMT+0". */
export function formatDateTime(value: unknown): string {
  const date = coerceToDate(value);
  if (!date) return MISSING_VALUE;
  try {
    // Intl doesn't allow mixing dateStyle/timeStyle with timeZoneName, so this spells
    // out the individual components instead.
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    }).format(date);
  } catch {
    return MISSING_VALUE;
  }
}

/** `expiresAtEpochSeconds` -> "3:12" (mm:ss) remaining, or "Expired". */
export function formatCountdown(expiresAtEpochSeconds: unknown, nowMs: number = Date.now()): string {
  const expires = toFiniteNumber(expiresAtEpochSeconds);
  if (expires === null) return MISSING_VALUE;
  const remainingMs = expires * 1000 - nowMs;
  if (remainingMs <= 0) return "Expired";
  const totalSeconds = Math.ceil(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function isExpired(expiresAtEpochSeconds: unknown, nowMs: number = Date.now()): boolean {
  const expires = toFiniteNumber(expiresAtEpochSeconds);
  if (expires === null) return true;
  return expires * 1000 <= nowMs;
}

/** Title-cases a snake_case proposal kind: "place_cex_order" -> "Place cex order". */
export function humanizeKind(kind: string): string {
  if (!kind) return MISSING_VALUE;
  const spaced = kind.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
