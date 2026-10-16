from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class RateLimitError(Exception):
    code: str
    message: str
    data: Dict[str, object]


class FixedWindowRateLimiter:
    """
    Simple fixed-window limiter: max N events per window_seconds per key.
    In-memory only (resets on restart), with bounded keys and expiry cleanup.
    At capacity, refuse new keys rather than evicting an active caller's budget.
    """

    def __init__(self, *, max_keys: int = 4096) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self._max_keys = max_keys
        # key -> (monotonic window expiry, count)
        self._lock = threading.Lock()
        self._state: Dict[str, Tuple[int, int]] = {}
        self._next_sweep = 0

    def check(self, *, key: str, limit: int, window_seconds: int) -> None:
        if limit <= 0:
            return
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if len(key) > 256:
            raise RateLimitError(code="rate_limited", message="Rate limit key too long.", data={"limit": limit, "window_seconds": window_seconds})
        with self._lock:
            now = int(time.monotonic())
            if now >= self._next_sweep:
                self._state = {k: v for k, v in self._state.items() if v[0] > now}
                self._next_sweep = now + 1
            window_end = now - (now % window_seconds) + window_seconds
            prev = self._state.get(key)
            if not prev or prev[0] <= now:
                if prev is None and len(self._state) >= self._max_keys:
                    raise RateLimitError(
                        code="rate_limited",
                        message="Rate limiter capacity reached.",
                        data={"limit": limit, "window_seconds": window_seconds},
                    )
                self._state[key] = (window_end, 1)
                return
            count = min(prev[1] + 1, limit + 1)
            self._state[key] = (prev[0], count)
            if count > limit:
                raise RateLimitError(
                    code="rate_limited",
                    message="Rate limit exceeded.",
                    data={"key": key, "limit": limit, "window_seconds": window_seconds, "count": count},
                )
