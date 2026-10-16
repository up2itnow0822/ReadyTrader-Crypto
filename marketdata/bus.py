from __future__ import annotations

import json
import logging  # Added logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .providers import MarketDataProvider

logger = logging.getLogger(__name__)  # Setup logger


@dataclass(frozen=True)
class MarketDataResult:
    source: str
    data: Any
    meta: Dict[str, Any]

    def acceptable_price(self) -> float:
        """Return a price only while its original freshness and anomaly evidence is valid."""
        if self.meta.get("stale") is not False or self.meta.get("outlier") is not False:
            raise ValueError("marketdata_not_acceptable: missing or failed quality metadata")
        timestamp = self.meta.get("timestamp_ms")
        max_age = self.meta.get("max_age_ms")
        if not _finite_number(timestamp) or not _finite_number(max_age) or float(max_age) <= 0:
            raise ValueError("marketdata_not_acceptable: missing or invalid freshness bounds")
        age = _now_ms() - float(timestamp)
        if not 0 <= age <= float(max_age):
            raise ValueError("marketdata_not_acceptable: stale or future timestamp")
        ok, reason = _sane_ticker(self.data)
        if not ok:
            raise ValueError(f"marketdata_not_acceptable: {reason}")
        return float(self.data["last"])


def _finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _now_ms() -> int:
    return int(time.time() * 1000)


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


def _priority_map(providers: List[MarketDataProvider]) -> Dict[str, int]:
    """
    Compute a provider_id -> priority mapping.

    Lower number == higher priority.

    Env override (JSON object):
      MARKETDATA_PROVIDER_PRIORITY_JSON='{\"exchange_ws\":0,\"ingest\":1,\"ccxt_rest\":2}'
    """
    raw = (os.getenv("MARKETDATA_PROVIDER_PRIORITY_JSON") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out = {}
                for k, v in data.items():
                    iv: Optional[int] = None
                    if isinstance(v, int) and not isinstance(v, bool):
                        iv = v
                    elif isinstance(v, str):
                        s = v.strip()
                        if s and (s.isdigit() or (s.startswith("-") and s[1:].isdigit())):
                            iv = int(s)
                    if iv is not None:
                        out[str(k)] = iv
                return out
        except Exception:
            _ = False

    # Default priorities
    out = {p.provider_id: 9 for p in providers}
    out["exchange_ws"] = 0
    out["ingest"] = 1
    out["ccxt_rest"] = 2
    return out


def _max_age_ms_for(provider_id: str) -> int:
    """
    Staleness threshold. If age_ms <= threshold, data is considered fresh.

    Env:
    - MARKETDATA_MAX_AGE_MS (default 30000)
    - MARKETDATA_MAX_AGE_MS_<PROVIDERID> (e.g. MARKETDATA_MAX_AGE_MS_EXCHANGE_WS)
    """
    default_ms = _env_int("MARKETDATA_MAX_AGE_MS", 30_000)
    key = f"MARKETDATA_MAX_AGE_MS_{provider_id.upper()}"
    return _env_int(key, default_ms)


def _sane_ticker(t: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        last = t.get("last")
        if not _finite_number(last) or float(last) <= 0.0:
            return False, "invalid_last"
        bid = t.get("bid")
        ask = t.get("ask")
        if bid is not None and (not _finite_number(bid) or float(bid) <= 0.0):
            return False, "invalid_bid"
        if ask is not None and (not _finite_number(ask) or float(ask) <= 0.0):
            return False, "invalid_ask"
        if bid is not None and ask is not None and float(ask) < float(bid):
            return False, "ask_lt_bid"
        return True, "ok"
    except Exception:
        return False, "ticker_parse_error"


def _extract_ts_ms(t: Dict[str, Any]) -> Optional[int]:
    ts = t.get("timestamp_ms")
    if ts is None:
        ts = t.get("timestamp")
    if ts is None:
        ts = t.get("ingested_at_ms")
    if not _finite_number(ts):
        return None
    try:
        return int(ts)
    except Exception:
        return None


class MarketDataBus:
    """
    Market data router with freshness scoring + source priority (Phase 3).

    Provider order matters. A typical ordering is:
    1) Public websocket store ("exchange_ws") (opt-in)
    2) Ingested data ("ingest") (user-supplied feed / other MCP)
    3) CCXT REST fallback ("ccxt_rest")
    """

    def __init__(self, providers: List[MarketDataProvider]) -> None:
        self._providers = list(providers)
        self._priority = _priority_map(self._providers)
        self._lock = threading.Lock()
        # symbol -> (last, ts_ms) for cheap outlier checks without fetching multiple sources
        self._last_good: Dict[str, Tuple[float, int]] = {}

    def fetch_ticker(self, symbol: str) -> MarketDataResult:
        sym = (symbol or "").strip().upper()
        now_ms = _now_ms()

        # Live data cannot fall back to stale/anomalous quotes, regardless of mutable env flags.
        from app.core.config import settings
        from app.core.settings import _parse_bool

        enforce_fresh = (
            settings.LIVE_TRADING_ENABLED
            or not settings.PAPER_MODE
            or settings.MARKETDATA_FAIL_CLOSED
            or _parse_bool(os.getenv("MARKETDATA_FAIL_CLOSED", "false"))
        )

        # Outlier detection config
        outlier_pct = _env_float("MARKETDATA_OUTLIER_MAX_PCT", 20.0)
        outlier_window_ms = _env_int("MARKETDATA_OUTLIER_WINDOW_MS", 10_000)

        providers = sorted(self._providers, key=lambda p: self._priority.get(p.provider_id, 9))
        candidates: List[Dict[str, Any]] = []
        candidate_tickers: Dict[str, Dict[str, Any]] = {}
        chosen: Optional[Dict[str, Any]] = None
        last_err: Exception | None = None

        for p in providers:
            pid = p.provider_id
            try:
                t = p.fetch_ticker(sym)
                # A provider may produce a quote while its network request is in flight.
                # Measure freshness after it returns, not against request-start time.
                now_ms = _now_ms()
                ok, reason = _sane_ticker(t)
                candidate_tickers[pid] = t
                ts_ms = _extract_ts_ms(t)
                age_ms = (now_ms - ts_ms) if ts_ms is not None else None
                max_age_ms = _max_age_ms_for(pid)
                stale = (age_ms is None) or not (0 <= age_ms <= max_age_ms)
                cand = {
                    "provider_id": pid,
                    "priority": self._priority.get(pid, 9),
                    "ok": ok,
                    "reason": reason,
                    "timestamp_ms": ts_ms,
                    "age_ms": age_ms,
                    "max_age_ms": max_age_ms,
                    "stale": stale,
                    "last": float(t.get("last") or 0.0),
                }
                candidates.append(cand)
                if ok and not stale and chosen is None:
                    chosen = {"provider_id": pid, "ticker": t, "age_ms": age_ms, "timestamp_ms": ts_ms}
                    break
            except Exception as e:
                last_err = e
                # Explicit logging for failover
                logger.warning(f"MarketDataBus: Provider {pid} failed for {sym}: {e}. Trying next provider...")
                candidates.append(
                    {
                        "provider_id": pid,
                        "priority": self._priority.get(pid, 9),
                        "ok": False,
                        "reason": "provider_error",
                        "error": str(e),
                    }
                )
                continue

        # If nothing was both ok+fresh, pick best-effort: lowest priority then freshest.
        if chosen is None:
            best_pid = None
            best_age = None
            best_ticker = None
            best_ts = None
            # Keep the exact validated observation; never refetch after choosing a candidate.
            for c in candidates:
                if not c.get("ok"):
                    continue
                pid = c.get("provider_id")
                age = c.get("age_ms")
                # prefer lower priority
                if best_pid is None:
                    best_pid, best_age = pid, age
                    continue
                if self._priority.get(pid, 9) < self._priority.get(best_pid, 9):
                    best_pid, best_age = pid, age
                    continue
                if self._priority.get(pid, 9) == self._priority.get(best_pid, 9):
                    if best_age is None:
                        best_pid, best_age = pid, age
                        continue
                    if age is not None and age < best_age:
                        best_pid, best_age = pid, age

            if best_pid is not None:
                if best_pid in candidate_tickers:
                    best_ticker = candidate_tickers[best_pid]
                    best_ts = _extract_ts_ms(best_ticker)
                    best_age = (now_ms - best_ts) if best_ts is not None else None
                    chosen = {
                        "provider_id": best_pid,
                        "ticker": best_ticker,
                        "age_ms": best_age,
                        "timestamp_ms": best_ts,
                    }

        if chosen is None:
            raise ValueError(f"All providers failed to fetch ticker for {sym}. Last error: {last_err}")

        ticker = chosen["ticker"]
        provider_id = str(chosen["provider_id"])
        ts_ms = chosen.get("timestamp_ms")
        now_ms = _now_ms()
        age_ms = (now_ms - ts_ms) if ts_ms is not None else None
        max_age_ms = _max_age_ms_for(provider_id)
        stale = (age_ms is None) or not (0 <= age_ms <= max_age_ms)

        # Cheap outlier check vs last good value
        outlier = False
        outlier_reason = None
        try:
            last = float(ticker.get("last") or 0.0)
            with self._lock:
                prev = self._last_good.get(sym)
            if prev is not None and ts_ms is not None:
                prev_last, prev_ts = prev
                if (now_ms - prev_ts) <= outlier_window_ms and prev_last > 0:
                    pct = abs((last - prev_last) / prev_last) * 100.0
                    if pct > outlier_pct:
                        outlier = True
                        outlier_reason = f"pct_move_{round(pct, 3)}"
            if not stale and not outlier and ts_ms is not None:
                with self._lock:
                    self._last_good[sym] = (last, ts_ms)
        except Exception:
            _ = False

        if enforce_fresh and (stale or outlier):
            raise ValueError(f"marketdata_not_acceptable: stale={stale} outlier={outlier} provider={provider_id} age_ms={age_ms}")

        meta = {
            "symbol": sym,
            "provider_id": provider_id,
            "priority": self._priority.get(provider_id, 9),
            "timestamp_ms": ts_ms,
            "age_ms": age_ms,
            "max_age_ms": max_age_ms,
            "stale": stale,
            "outlier": outlier,
            "outlier_reason": outlier_reason,
            "candidates": candidates,
        }
        result = MarketDataResult(source=provider_id, data=ticker, meta=meta)
        if enforce_fresh:
            result.acceptable_price()
        return result

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> MarketDataResult:
        last_err: Exception | None = None
        for p in self._providers:
            try:
                return MarketDataResult(
                    source=p.provider_id,
                    data=p.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit),
                    meta={"provider_id": p.provider_id},
                )
            except Exception as e:
                last_err = e
                logger.warning(f"MarketDataBus: Provider {p.provider_id} OHLCV failed: {e}. Trying next...")
                continue
        raise ValueError(f"All providers failed to fetch OHLCV for {symbol}. Last error: {last_err}")

    def status(self) -> Dict[str, Any]:
        providers = []
        for p in sorted(self._providers, key=lambda x: self._priority.get(x.provider_id, 9)):
            try:
                providers.append(
                    {
                        "provider_id": p.provider_id,
                        "priority": self._priority.get(p.provider_id, 9),
                        "status": p.status(),
                    }
                )
            except Exception as e:
                providers.append(
                    {
                        "provider_id": p.provider_id,
                        "priority": self._priority.get(p.provider_id, 9),
                        "status_error": str(e),
                    }
                )
        return {"providers": providers}
