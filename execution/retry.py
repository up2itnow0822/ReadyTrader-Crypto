"""
Execution retry helpers (Phase 2D).

We keep this intentionally small:
- retry only transient CCXT/network-style errors
- exponential backoff with jitter (non-crypto randomness)
"""

from __future__ import annotations

import os
import random
import time
from typing import Callable, TypeVar

import ccxt

from errors import AppError, classify_exception

T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or "").strip() or default)
    except Exception:
        return default


def should_retry(e: Exception) -> bool:
    # CCXT transient error categories
    if isinstance(e, (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout)):
        return True
    # Generally do not retry auth/bad symbol/permission etc.
    return False


def with_retry(op: str, fn: Callable[[], T], *, safe_to_retry: bool = True) -> T:
    """
    Run `fn` with standardized retry/backoff on transient CCXT errors.

    Env tuning:
    - CEX_RETRY_MAX_ATTEMPTS (default 3)
    - CEX_RETRY_BASE_DELAY_SEC (default 0.5)
    - CEX_RETRY_MAX_DELAY_SEC (default 5.0)
    """
    max_attempts = max(1, _env_int("CEX_RETRY_MAX_ATTEMPTS", 3)) if safe_to_retry else 1
    base = max(0.05, _env_float("CEX_RETRY_BASE_DELAY_SEC", 0.5))
    max_delay = max(base, _env_float("CEX_RETRY_MAX_DELAY_SEC", 5.0))

    attempt = 0
    last_exc: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if not safe_to_retry and should_retry(e):
                raise AppError("execution_outcome_uncertain", "Mutation outcome is uncertain; no retry was sent.", {"op": op, "attempts": 1}) from e
            if not should_retry(e) or attempt >= max_attempts:
                ae = classify_exception(e)
                raise AppError(
                    ae.code,
                    f"{op} failed after {attempt} attempt(s): {ae.message}",
                    {"attempts": attempt, "op": op},
                ) from e
            # exponential backoff with jitter
            delay = min(max_delay, base * (2 ** (attempt - 1)))
            jitter = 0.5 + (random.random() * 0.5)  # nosec B311 (non-crypto jitter)
            time.sleep(delay * jitter)

    # should never reach
    raise last_exc or RuntimeError("retry_failed")
