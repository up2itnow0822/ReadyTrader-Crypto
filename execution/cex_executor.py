from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Optional

import ccxt

from errors import AppError

from .models import normalize_ccxt_order, normalize_market_type
from .retry import should_retry, with_retry


@dataclass
class CexCredentials:
    exchange_id: str
    api_key: str
    api_secret: str
    api_password: Optional[str] = None


def _env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def load_cex_credentials(exchange_id: str, *, require_auth: bool = True) -> Optional[CexCredentials]:
    """
    Load credentials for a given exchange from env vars.

    Priority:
    1) CEX_<EXCHANGE>_API_KEY / CEX_<EXCHANGE>_API_SECRET / CEX_<EXCHANGE>_API_PASSWORD
    2) CEX_API_KEY / CEX_API_SECRET / CEX_API_PASSWORD (generic)
    """
    ex = exchange_id.strip().lower()
    prefix = f"CEX_{ex.upper()}_"

    api_key = _env(prefix + "API_KEY") or _env("CEX_API_KEY")
    api_secret = _env(prefix + "API_SECRET") or _env("CEX_API_SECRET")
    api_password = _env(prefix + "API_PASSWORD") or _env("CEX_API_PASSWORD")

    if not api_key or not api_secret:
        if not require_auth:
            return None
        raise ValueError(f"Missing CEX credentials for exchange '{exchange_id}'. Set {prefix}API_KEY/{prefix}API_SECRET or CEX_API_KEY/CEX_API_SECRET.")

    return CexCredentials(exchange_id=ex, api_key=api_key, api_secret=api_secret, api_password=api_password)


def _get_proxy() -> Optional[str]:
    return _env("CCXT_PROXY") or _env("HTTPS_PROXY") or _env("HTTP_PROXY")


def _get_default_type() -> Optional[str]:
    dt = _env("CCXT_DEFAULT_TYPE") or _env("CEX_MARKET_TYPE")
    return dt.strip().lower() if dt else None


def _build_exchange(exchange_id: str, *, market_type: str, creds: Optional[CexCredentials]) -> ccxt.Exchange:
    ex_id = exchange_id.strip().lower()
    if not hasattr(ccxt, ex_id):
        raise ValueError(f"Unsupported exchange id for ccxt: {ex_id}")

    ex_cls = getattr(ccxt, ex_id)
    params: Dict[str, Any] = {
        "enableRateLimit": True,
    }
    if creds is not None:
        params["apiKey"] = creds.api_key
        params["secret"] = creds.api_secret
        if creds.api_password:
            params["password"] = creds.api_password

    proxy = _get_proxy()
    if proxy:
        params["proxies"] = {"http": proxy, "https": proxy}

    mt = normalize_market_type(market_type)
    default_type = _get_default_type()
    # Allow per-instance defaultType so we can support spot + swap concurrently by creating distinct executors.
    options: Dict[str, Any] = {}
    if default_type:
        options["defaultType"] = default_type
    if mt and mt != "auto":
        options["defaultType"] = mt
    if options:
        params["options"] = options

    return ex_cls(params)


@lru_cache(maxsize=64)
def _get_public_exchange(exchange_id: str, market_type: str) -> ccxt.Exchange:
    """
    Cached public (unauthenticated) ccxt exchange instance configured from env.
    """
    return _build_exchange(exchange_id, market_type=market_type, creds=None)


@lru_cache(maxsize=64)
def _get_private_exchange(exchange_id: str, market_type: str) -> ccxt.Exchange:
    """
    Cached authenticated ccxt exchange instance configured from env.
    """
    creds = load_cex_credentials(exchange_id, require_auth=True)
    return _build_exchange(exchange_id, market_type=market_type, creds=creds)


class CexExecutor:
    def __init__(self, exchange_id: str = "binance", *, market_type: str = "spot", auth: bool = True) -> None:
        self.exchange_id = exchange_id.strip().lower()
        self.market_type = normalize_market_type(market_type)
        self.auth = bool(auth)
        self._ex = _get_private_exchange(self.exchange_id, self.market_type) if self.auth else _get_public_exchange(self.exchange_id, self.market_type)

    def _require_auth(self, op: str) -> None:
        if not self.auth:
            raise ValueError(f"{op} requires authenticated CEX credentials")

    def supports(self, feature: str) -> bool:
        """
        CCXT feature flag helper.
        """
        has = getattr(self._ex, "has", {}) or {}
        return bool(has.get(feature))

    def fetch_balance(self) -> Dict[str, Any]:
        self._require_auth("fetch_balance")
        return with_retry(f"{self.exchange_id}.fetch_balance", lambda: self._ex.fetch_balance())

    def _load_markets(self) -> Dict[str, Any]:
        return with_retry(f"{self.exchange_id}.load_markets", lambda: self._ex.load_markets())

    def resolve_symbol(self, symbol: str) -> str:
        """
        Resolve a user symbol to the exchange-listed symbol for the configured market_type.

        Example:
        - user: BTC/USDT + market_type=swap
        - exchange: BTC/USDT:USDT
        """
        sym = symbol.strip().upper()
        markets = self._load_markets()
        if sym in markets:
            # If the exact symbol exists but doesn't match the configured market type,
            # prefer a base/quote match that does (e.g., spot BTC/USDT vs swap BTC/USDT:USDT).
            m = markets.get(sym)
            mt = self.market_type
            if mt == "auto":
                return sym
            if isinstance(m, dict):
                if mt == "spot" and m.get("spot") is True:
                    return sym
                if mt == "swap" and m.get("swap") is True:
                    return sym
                if mt == "future" and m.get("future") is True:
                    return sym
        if "/" not in sym:
            return sym

        base, quote = sym.split("/", 1)
        mt = self.market_type
        for m in markets.values():
            if not isinstance(m, dict):
                continue
            mb = str(m.get("base") or "").upper()
            mq = str(m.get("quote") or "").upper()
            ms = str(m.get("symbol") or "")
            if not ms or mb != base or mq != quote:
                continue
            if mt == "spot" and m.get("spot") is True:
                return ms
            if mt == "swap" and m.get("swap") is True:
                return ms
            if mt == "future" and m.get("future") is True:
                return ms

        # If nothing matched market type, return original.
        return sym

    def get_capabilities(self, *, symbol: str = "") -> Dict[str, Any]:
        """
        Return exchange capability info and (optional) market metadata for a given symbol.
        """
        cap = {
            "exchange_id": getattr(self._ex, "id", self.exchange_id),
            "market_type": self.market_type,
            "has": getattr(self._ex, "has", {}),
            "timeframes": getattr(self._ex, "timeframes", None),
        }
        try:
            markets = self._load_markets()
        except Exception:
            markets = {}
        if symbol:
            resolved = self.resolve_symbol(symbol)
            m = markets.get(resolved) or markets.get(symbol.strip().upper()) or None
            cap["symbol"] = symbol
            cap["resolved_symbol"] = resolved
            cap["market"] = m
        return cap

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._require_auth("place_order")
        s = self.resolve_symbol(symbol)
        t = order_type.strip().lower()
        sd = side.strip().lower()

        if t not in {"market", "limit"}:
            raise ValueError("order_type must be 'market' or 'limit'")
        if sd not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if amount <= 0:
            raise ValueError("amount must be > 0")
        if t == "limit" and (price is None or price <= 0):
            raise ValueError("price must be provided for limit orders and be > 0")

        # Ensure markets are loaded (symbol validation + normalization).
        # Some exchanges intermittently fail load_markets; order placement can still succeed.
        try:
            self._load_markets()
        except Exception:
            _ = False

        # Never retry a mutating create after a lost response. Even exchanges with
        # client IDs may permit reuse after an order fills. Reconcile read-only.
        p = dict(params or {})
        try:
            return self._ex.create_order(s, t, sd, amount, None if t == "market" else price, p)
        except Exception as exc:
            if not should_retry(exc):
                raise
            client_id = str(p.get("clientOrderId") or "")
            if client_id:
                try:
                    existing = self.reconcile_order(client_order_id=client_id, symbol=s)
                    if existing is not None:
                        return existing
                except Exception:
                    # A failed lookup (including not-found) never proves no fill.
                    pass
            raise AppError(
                "execution_outcome_uncertain",
                "Order submission outcome is uncertain. Reconcile before any new order; no retry was sent.",
                {"client_order_id": client_id, "exchange": self.exchange_id},
            ) from exc

    def reconcile_order(self, *, client_order_id: str, symbol: str) -> Dict[str, Any] | None:
        """Read-only reconciliation for explicitly supported exchange semantics.

        Unsupported exchanges do not get a guessed query or a second submission.
        """
        if self.exchange_id not in {"binance", "binanceus", "binanceusdm", "binancecoinm"}:
            return None
        if not self.supports("fetchOrder"):
            return None
        result = with_retry(
            f"{self.exchange_id}.fetch_order_by_client_id",
            lambda: self._ex.fetch_order(None, symbol, {"origClientOrderId": client_order_id}),
        )
        if isinstance(result, dict) and result.get("id") and result.get("clientOrderId") == client_order_id and result.get("symbol") == symbol:
            return result
        return None

    def cancel_order(self, *, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        self._require_auth("cancel_order")
        if symbol:
            try:
                self._load_markets()
            except Exception:
                _ = False
            return with_retry(
                f"{self.exchange_id}.cancel_order",
                lambda: self._ex.cancel_order(order_id, self.resolve_symbol(symbol)),
            )
        return with_retry(f"{self.exchange_id}.cancel_order", lambda: self._ex.cancel_order(order_id))

    def fetch_order(self, *, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        self._require_auth("fetch_order")
        if symbol:
            try:
                self._load_markets()
            except Exception:
                _ = False
            return with_retry(
                f"{self.exchange_id}.fetch_order",
                lambda: self._ex.fetch_order(order_id, self.resolve_symbol(symbol)),
            )
        return with_retry(f"{self.exchange_id}.fetch_order", lambda: self._ex.fetch_order(order_id))

    def fetch_open_orders(self, *, symbol: Optional[str] = None) -> list[Dict[str, Any]]:
        self._require_auth("fetch_open_orders")
        sym = self.resolve_symbol(symbol) if symbol else None
        if sym:
            return with_retry(f"{self.exchange_id}.fetch_open_orders", lambda: self._ex.fetch_open_orders(sym))
        return with_retry(f"{self.exchange_id}.fetch_open_orders", lambda: self._ex.fetch_open_orders())

    def fetch_orders(self, *, symbol: Optional[str] = None, limit: Optional[int] = None) -> list[Dict[str, Any]]:
        self._require_auth("fetch_orders")
        sym = self.resolve_symbol(symbol) if symbol else None
        if sym:
            if limit:
                return with_retry(
                    f"{self.exchange_id}.fetch_orders",
                    lambda: self._ex.fetch_orders(sym, limit=limit),
                )
            return with_retry(f"{self.exchange_id}.fetch_orders", lambda: self._ex.fetch_orders(sym))
        if limit:
            return with_retry(f"{self.exchange_id}.fetch_orders", lambda: self._ex.fetch_orders(limit=limit))
        return with_retry(f"{self.exchange_id}.fetch_orders", lambda: self._ex.fetch_orders())

    def fetch_my_trades(self, *, symbol: Optional[str] = None, limit: Optional[int] = None) -> list[Dict[str, Any]]:
        self._require_auth("fetch_my_trades")
        sym = self.resolve_symbol(symbol) if symbol else None
        if sym:
            if limit:
                return with_retry(
                    f"{self.exchange_id}.fetch_my_trades",
                    lambda: self._ex.fetch_my_trades(sym, limit=limit),
                )
            return with_retry(f"{self.exchange_id}.fetch_my_trades", lambda: self._ex.fetch_my_trades(sym))
        if limit:
            return with_retry(f"{self.exchange_id}.fetch_my_trades", lambda: self._ex.fetch_my_trades(limit=limit))
        return with_retry(f"{self.exchange_id}.fetch_my_trades", lambda: self._ex.fetch_my_trades())

    def normalize_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        return normalize_ccxt_order(exchange=self.exchange_id, market_type=self.market_type, order=order).to_dict()

    def cancel_all_orders(self, *, symbol: Optional[str] = None) -> Any:
        """
        Best-effort cancel-all wrapper (capability-gated).
        """
        self._require_auth("cancel_all_orders")
        if not self.supports("cancelAllOrders"):
            raise ValueError(f"{self.exchange_id} does not support cancelAllOrders")
        sym = self.resolve_symbol(symbol) if symbol else None
        if sym:
            return with_retry(
                f"{self.exchange_id}.cancel_all_orders",
                lambda: self._ex.cancel_all_orders(sym),
            )
        return with_retry(f"{self.exchange_id}.cancel_all_orders", lambda: self._ex.cancel_all_orders())

    def replace_order(
        self,
        *,
        order_id: str,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "limit",
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Best-effort edit/replace wrapper (capability-gated).
        """
        self._require_auth("replace_order")
        if not self.supports("editOrder"):
            raise ValueError(f"{self.exchange_id} does not support editOrder")
        s = self.resolve_symbol(symbol)
        t = order_type.strip().lower()
        sd = side.strip().lower()
        p = params or {}
        return with_retry(
            f"{self.exchange_id}.edit_order",
            lambda: self._ex.edit_order(order_id, s, t, sd, amount, price, p),
            safe_to_retry=False,
        )
