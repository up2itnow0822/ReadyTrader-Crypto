import { describe, expect, it } from "vitest";

import {
  formatCountdown,
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatQuantity,
  humanizeKind,
  isExpired,
  MISSING_VALUE,
  toFiniteNumber,
} from "./format";

describe("toFiniteNumber", () => {
  it("accepts finite numbers and numeric strings", () => {
    expect(toFiniteNumber(5)).toBe(5);
    expect(toFiniteNumber("5.25")).toBe(5.25);
    expect(toFiniteNumber(0)).toBe(0);
  });

  it("rejects null, undefined, NaN, Infinity and junk strings", () => {
    expect(toFiniteNumber(null)).toBeNull();
    expect(toFiniteNumber(undefined)).toBeNull();
    expect(toFiniteNumber(NaN)).toBeNull();
    expect(toFiniteNumber(Infinity)).toBeNull();
    expect(toFiniteNumber(-Infinity)).toBeNull();
    expect(toFiniteNumber("not a number")).toBeNull();
    expect(toFiniteNumber({})).toBeNull();
    expect(toFiniteNumber("")).toBeNull();
  });
});

describe("formatCurrency", () => {
  it("formats a normal value", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });

  it("returns the missing placeholder for null/NaN/undefined", () => {
    expect(formatCurrency(null)).toBe(MISSING_VALUE);
    expect(formatCurrency(undefined)).toBe(MISSING_VALUE);
    expect(formatCurrency(NaN)).toBe(MISSING_VALUE);
  });

  it("handles a huge value without throwing or producing NaN", () => {
    const result = formatCurrency(1e21);
    expect(result).not.toContain("NaN");
    expect(result).not.toBe(MISSING_VALUE);
  });

  it("handles a tiny value without throwing", () => {
    const result = formatCurrency(1e-10);
    expect(result).not.toContain("NaN");
  });
});

describe("formatQuantity", () => {
  it("shows up to 8 decimal places", () => {
    expect(formatQuantity(0.123456789)).toBe("0.12345679");
  });

  it("returns the missing placeholder for non-finite input", () => {
    expect(formatQuantity(null)).toBe(MISSING_VALUE);
    expect(formatQuantity(NaN)).toBe(MISSING_VALUE);
    expect(formatQuantity(undefined)).toBe(MISSING_VALUE);
  });

  it("never renders the literal strings NaN or undefined", () => {
    expect(formatQuantity(NaN)).not.toContain("NaN");
    expect(formatQuantity(undefined)).not.toContain("undefined");
  });
});

describe("formatPercent", () => {
  it("formats a fraction as a percentage", () => {
    expect(formatPercent(0.0512)).toBe("5.12%");
    expect(formatPercent(-0.02)).toBe("-2.00%");
  });

  it("returns the missing placeholder for non-finite input", () => {
    expect(formatPercent(null)).toBe(MISSING_VALUE);
    expect(formatPercent(undefined)).toBe(MISSING_VALUE);
  });
});

describe("formatDateTime", () => {
  it("formats an ISO timestamp with a timezone label", () => {
    const result = formatDateTime("2026-01-05T15:04:05Z");
    expect(result).not.toBe(MISSING_VALUE);
    expect(result).toMatch(/2026/);
  });

  it("treats a SQLite-style timestamp (no timezone) as UTC", () => {
    const result = formatDateTime("2026-01-05 15:04:05");
    expect(result).not.toBe(MISSING_VALUE);
    expect(result).not.toBe("Invalid Date");
  });

  it("returns the missing placeholder for null/undefined/garbage", () => {
    expect(formatDateTime(null)).toBe(MISSING_VALUE);
    expect(formatDateTime(undefined)).toBe(MISSING_VALUE);
    expect(formatDateTime("not a date")).toBe(MISSING_VALUE);
  });
});

describe("formatCountdown / isExpired", () => {
  it("counts down in mm:ss", () => {
    const now = 1_000_000;
    const expiresAt = now / 1000 + 90; // 90s from now, in epoch seconds
    expect(formatCountdown(expiresAt, now)).toBe("1:30");
    expect(isExpired(expiresAt, now)).toBe(false);
  });

  it("reports Expired once the deadline passes", () => {
    const now = 1_000_000;
    const expiresAt = now / 1000 - 1;
    expect(formatCountdown(expiresAt, now)).toBe("Expired");
    expect(isExpired(expiresAt, now)).toBe(true);
  });

  it("treats a missing expiry as already expired", () => {
    expect(isExpired(null)).toBe(true);
    expect(isExpired(undefined)).toBe(true);
  });
});

describe("humanizeKind", () => {
  it("turns a snake_case kind into a readable label", () => {
    expect(humanizeKind("place_cex_order")).toBe("Place cex order");
  });
});
