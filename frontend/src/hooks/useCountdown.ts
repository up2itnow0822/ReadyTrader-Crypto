"use client";

import { useEffect, useState } from "react";

import { formatCountdown, isExpired } from "@/lib/format";

export interface CountdownResult {
  text: string;
  expired: boolean;
}

/** Ticks once a second so an approval card's countdown-to-expiry stays live. */
export function useCountdown(expiresAtEpochSeconds: number): CountdownResult {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return {
    text: formatCountdown(expiresAtEpochSeconds, now),
    expired: isExpired(expiresAtEpochSeconds, now),
  };
}
