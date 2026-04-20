from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastmcp import FastMCP
from web3 import Web3

from app.core.config import settings
from app.core.container import global_container
from execution.cex_executor import CexExecutor
from execution.evm import (
    chain_id_for,
    erc20_decimals,
    get_web3,
    is_hex_address,
    send_raw_transaction,
    to_atomic,
)
from execution.router import venue_allowed
from observability.audit import now_ms

logger = logging.getLogger(__name__)


def _parse_int(v: Any, default: int = 0) -> int:
    """
    Parse numeric fields coming from APIs (often hex strings like "0x0").
    """
    if v is None:
        return int(default)
    if isinstance(v, bool):
        raise ValueError("boolean is not a valid int")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return int(default)
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s, 10)
    return int(v)


def _json_ok(data: Dict[str, Any] | None = None) -> str:
    payload = {"ok": True, "data": data or {}}
    return json.dumps(payload, indent=2, sort_keys=True)


def _json_err(code: str, message: str, data: Dict[str, Any] | None = None) -> str:
    payload = {"ok": False, "error": {"code": code, "message": message, "data": data or {}}}
    return json.dumps(payload, indent=2, sort_keys=True)


def _json_internal_error(
    code: str,
    public_message: str,
    exc: Exception,
    data: Dict[str, Any] | None = None,
) -> str:
    logger.exception("%s: %s", code, exc)
    return _json_err(code, public_message, data)


def _require_live_allowed(*, venue: str) -> None:
    if settings.PAPER_MODE:
        return
    if not settings.LIVE_TRADING_ENABLED:
        raise ValueError("LIVE_TRADING_ENABLED=false (live execution is disabled)")
    if settings.TRADING_HALTED:
        raise ValueError("TRADING_HALTED=true (live execution is halted)")
    if not venue_allowed(settings.EXECUTION_MODE, venue):
        raise ValueError(f"Execution blocked by EXECUTION_MODE={settings.EXECUTION_MODE} for venue={venue}")


def _maybe_propose(kind: str, payload: Dict[str, Any]) -> Optional[str]:
    """
    If approve-each is enabled, create an execution proposal and return its JSON response string.
    """
    if settings.PAPER_MODE:
        return None
    if settings.EXECUTION_APPROVAL_MODE != "approve_each":
        return None
    prop = global_container.execution_store.create(kind=kind, payload=payload, ttl_seconds=120)
    return _json_ok(
        {
            "approval_required": True,
            "request_id": prop.request_id,
            "confirm_token": prop.confirm_token,
            "expires_at": prop.expires_at,
            "kind": prop.kind,
        }
    )


def _resolve_token(chain: str, token: str) -> str:
    addr = global_container.dex_handler.resolve_token(chain, token)
    if addr:
        return addr
    if is_hex_address(token):
        return token
    raise ValueError(f"Unknown token '{token}' for chain '{chain}' (configure TOKEN_MAP or pass 0x address)")


def swap_tokens(
    from_token: str,
    to_token: str,
    amount: float,
    chain: str = "ethereum",
    rationale: str = "",
    idempotency_key: str = "",
) -> str:
    """
    Swap tokens on a DEX (paper mode or live).

    Live mode:
    - builds a swap transaction using 1inch
    - signs with configured signer (supports remote signer)
    - broadcasts via JSON-RPC
    """
    symbol = f"{from_token}/{to_token}"

    if settings.PAPER_MODE:
        if not global_container.paper_engine:
            return _json_err("paper_engine_missing", "Paper engine not initialized.")
        res = global_container.paper_engine.execute_trade(
            agent_id="agent_zero",
            side="sell",
            symbol=symbol,
            amount=amount,
            price=1.0,
            rationale=rationale or "swap_tokens_paper",
        )
        return _json_ok({"venue": "dex", "mode": "paper", "result": res})

    try:
        _require_live_allowed(venue="dex")
        proposed = _maybe_propose(
            "swap_tokens",
            {
                "from_token": from_token,
                "to_token": to_token,
                "amount": amount,
                "chain": chain,
                "rationale": rationale,
                "idempotency_key": idempotency_key,
            },
        )
        if proposed:
            return proposed

        global_container.policy_engine.validate_swap(chain=chain, from_token=from_token, to_token=to_token, amount=amount)

        if idempotency_key:
            cached = global_container.idempotency_store.get(idempotency_key)
            if cached is not None:
                return _json_ok({"venue": "dex", "mode": "live", "idempotency_key": idempotency_key, **cached})

        chain_id = chain_id_for(chain)
        signer = global_container.signer
        user_address = signer.get_address()
        global_container.policy_engine.validate_signer_address(address=user_address)

        token_in = _resolve_token(chain, from_token)
        token_out = _resolve_token(chain, to_token)

        # Convert amount -> atomic units
        NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        if token_in.lower() == NATIVE:
            decimals = 18
        else:
            decimals = erc20_decimals(chain, token_in)
        amount_atomic = to_atomic(amount, decimals)

        slippage = float((os.getenv("DEX_SLIPPAGE_PCT") or "1.0").strip() or "1.0")
        swap_payload = global_container.dex_handler.build_swap_tx(
            chain,
            token_in,
            token_out,
            str(amount_atomic),
            user_address,
            slippage=slippage,
        )
        if not isinstance(swap_payload, dict):
            raise ValueError("1inch returned non-object payload")
        if swap_payload.get("error"):
            raise ValueError(str(swap_payload.get("error")))
        tx = swap_payload.get("tx")
        if not isinstance(tx, dict):
            raise ValueError("1inch payload missing tx")

        router_to = str(tx.get("to") or "").strip()
        if not router_to:
            raise ValueError("Swap tx missing 'to' (router address)")

        global_container.policy_engine.validate_router_address(chain=chain, router_address=router_to, context={"from_token": from_token, "to_token": to_token})
        global_container.policy_engine.validate_sign_tx(
            chain_id=chain_id,
            to_address=router_to,
            value_wei=_parse_int(tx.get("value"), 0),
            gas=_parse_int(tx.get("gas"), 0) if tx.get("gas") is not None else None,
            gas_price_wei=_parse_int(tx.get("gasPrice"), 0) if tx.get("gasPrice") is not None else None,
            data_hex=str(tx.get("data") or ""),
        )

        # Ensure fields required for signing
        w3 = get_web3(chain)
        tx = dict(tx)

        tx["chainId"] = int(chain_id)

        # Normalize numeric fields that frequently arrive as hex strings from APIs

        if "value" in tx:
            tx["value"] = _parse_int(tx.get("value"), 0)

        if "gas" in tx:
            tx["gas"] = _parse_int(tx.get("gas"), 0)

        if "gasPrice" in tx:
            tx["gasPrice"] = _parse_int(tx.get("gasPrice"), 0)
        if not tx.get("nonce"):
            tx["nonce"] = w3.eth.get_transaction_count(Web3.to_checksum_address(user_address))

        signed = signer.sign_transaction(tx, chain_id=chain_id)
        tx_hash = send_raw_transaction(chain, signed.rawTransaction)

        summary = {
            "chain": chain,
            "from_token": from_token,
            "to_token": to_token,
            "amount": amount,
            "tx_hash": tx_hash,
            "idempotency_key": idempotency_key,
        }
        global_container.audit_log.append(
            ts_ms=now_ms(),
            request_id=idempotency_key or f"dex:{tx_hash}",
            tool="swap_tokens",
            ok=True,
            mode="live",
            venue="dex",
            summary=summary,
        )
        if idempotency_key:
            global_container.idempotency_store.set(idempotency_key, summary)
        return _json_ok({"venue": "dex", "mode": "live", **summary})
    except Exception as e:
        return _json_internal_error("execution_error", "Execution failed.", e)


def transfer_eth(to_address: str, amount: float, chain: str = "ethereum", idempotency_key: str = "") -> str:
    """
    Transfer native currency (ETH/BASE/ARB/OP native token).
    Live mode signs and broadcasts via JSON-RPC.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Native transfers are not supported in paper mode.")
    try:
        _require_live_allowed(venue="dex")
        proposed = _maybe_propose(
            "transfer_eth",
            {"to_address": to_address, "amount": amount, "chain": chain, "idempotency_key": idempotency_key},
        )
        if proposed:
            return proposed

        global_container.policy_engine.validate_transfer_native(chain=chain, to_address=to_address, amount=amount)
        if idempotency_key:
            cached = global_container.idempotency_store.get(idempotency_key)
            if cached is not None:
                return _json_ok({"venue": "dex", "mode": "live", "idempotency_key": idempotency_key, **cached})

        chain_id = chain_id_for(chain)
        w3 = get_web3(chain)
        signer = global_container.signer
        from_addr = signer.get_address()
        global_container.policy_engine.validate_signer_address(address=from_addr)

        to_checksum = w3.to_checksum_address(to_address)
        value_wei = int(to_atomic(amount, 18))
        nonce = w3.eth.get_transaction_count(w3.to_checksum_address(from_addr))
        gas = 21000
        gas_price = int(w3.eth.gas_price)

        tx = {
            "to": to_checksum,
            "value": value_wei,
            "gas": gas,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": int(chain_id),
        }
        global_container.policy_engine.validate_sign_tx(
            chain_id=chain_id,
            to_address=str(to_checksum),
            value_wei=value_wei,
            gas=gas,
            gas_price_wei=gas_price,
            data_hex="0x",
        )
        signed = signer.sign_transaction(tx, chain_id=chain_id)
        tx_hash = send_raw_transaction(chain, signed.rawTransaction)

        summary = {
            "chain": chain,
            "to_address": to_address,
            "amount": amount,
            "tx_hash": tx_hash,
            "idempotency_key": idempotency_key,
        }
        global_container.audit_log.append(
            ts_ms=now_ms(),
            request_id=idempotency_key or f"native:{tx_hash}",
            tool="transfer_eth",
            ok=True,
            mode="live",
            venue="dex",
            summary=summary,
        )
        if idempotency_key:
            global_container.idempotency_store.set(idempotency_key, summary)
        return _json_ok({"venue": "dex", "mode": "live", **summary})
    except Exception as e:
        return _json_internal_error("transfer_error", "Transfer failed.", e)


def place_cex_order(
    symbol: str,
    side: str,
    amount: float,
    order_type: str = "market",
    price: float | None = None,
    exchange: str = "binance",
    market_type: str = "spot",
    idempotency_key: str = "",
) -> str:
    """
    Place an order on a CEX using CCXT authenticated credentials.

    In paper mode, this routes to the paper engine and does NOT require CEX credentials.
    """
    if settings.EXECUTION_MODE == "dex":
        return _json_err("execution_mode_blocked", "CEX execution disabled by EXECUTION_MODE=dex")

    if settings.PAPER_MODE:
        if not global_container.paper_engine:
            return _json_err("paper_engine_missing", "Paper engine not initialized.")
        res = global_container.paper_engine.execute_trade(
            agent_id="agent_zero",
            side=side,
            symbol=symbol,
            amount=amount,
            price=float(price or 0.0) if (price or 0.0) > 0 else 100000.0,
            rationale="cex_order_paper",
        )
        return _json_ok({"venue": "cex", "mode": "paper", "result": res})

    try:
        _require_live_allowed(venue="cex")
        proposed = _maybe_propose(
            "place_cex_order",
            {
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "order_type": order_type,
                "price": price,
                "exchange": exchange,
                "market_type": market_type,
                "idempotency_key": idempotency_key,
            },
        )
        if proposed:
            return proposed

        global_container.policy_engine.validate_cex_order(
            exchange_id=exchange,
            symbol=symbol,
            market_type=market_type,
            side=side,
            amount=amount,
            order_type=order_type,
            price=price,
        )

        if idempotency_key:
            cached = global_container.idempotency_store.get(idempotency_key)
            if cached is not None:
                return _json_ok({"venue": "cex", "mode": "live", "idempotency_key": idempotency_key, **cached})

        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        params = {"clientOrderId": idempotency_key} if idempotency_key else None
        order = ex.place_order(
            symbol=symbol,
            side=side,
            amount=float(amount),
            order_type=order_type,
            price=float(price) if price is not None else None,
            params=params,
        )
        normalized = ex.normalize_order(order)
        summary = {
            "exchange": exchange,
            "market_type": market_type,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "order_type": order_type,
            "price": price,
            "order": normalized,
        }
        global_container.audit_log.append(
            ts_ms=now_ms(),
            request_id=idempotency_key or f"cex:{exchange}:{normalized.get('id')}",
            tool="place_cex_order",
            ok=True,
            mode="live",
            venue="cex",
            exchange=exchange,
            market_type=market_type,
            summary=summary,
        )
        if idempotency_key:
            global_container.idempotency_store.set(idempotency_key, summary)
        return _json_ok({"venue": "cex", "mode": "live", **summary})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def get_cex_balance(exchange: str = "binance", market_type: str = "spot") -> str:
    """
    Fetch account balance from a centralized exchange.

    Returns the balance of all assets in the account. Requires CEX credentials
    configured via environment variables (CEX_API_KEY, CEX_API_SECRET).
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        bal = ex.fetch_balance()
        return _json_ok({"exchange": exchange, "market_type": market_type, "balance": bal})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def get_cex_order(order_id: str, symbol: str = "", exchange: str = "binance", market_type: str = "spot") -> str:
    """
    Fetch details of a specific order from a centralized exchange.

    Retrieves the current state of an order including fill status, executed
    quantity, and average price. Useful for tracking order execution.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        raw = ex.fetch_order(order_id=order_id, symbol=(symbol or None))
        return _json_ok({"exchange": exchange, "market_type": market_type, "order": ex.normalize_order(raw)})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def cancel_cex_order(order_id: str, symbol: str = "", exchange: str = "binance", market_type: str = "spot") -> str:
    """
    Cancel an open order on a centralized exchange.

    Attempts to cancel an unfilled or partially filled order. Returns the
    cancellation result. Note: orders may fill before cancellation completes.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        raw = ex.cancel_order(order_id=order_id, symbol=(symbol or None))
        return _json_ok({"exchange": exchange, "market_type": market_type, "result": raw})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def get_cex_capabilities(exchange: str = "binance", symbol: str = "", market_type: str = "spot") -> str:
    """
    Query exchange capabilities and market information.

    Returns supported features, order types, timeframes, and market metadata
    for the specified exchange. Useful for determining available functionality
    before placing orders. Does not require authentication.
    """
    try:
        # capabilities are safe; allow even if trading halted
        if settings.EXECUTION_MODE == "dex":
            return _json_err("execution_mode_blocked", "CEX disabled by EXECUTION_MODE=dex")
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=False)
        cap = ex.get_capabilities(symbol=symbol or "")
        return _json_ok({"capabilities": cap})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def list_cex_open_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str:
    """
    List all currently open (unfilled) orders on a centralized exchange.

    Returns orders that are pending execution. Can be filtered by symbol.
    Useful for monitoring active positions and managing order book exposure.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        orders = ex.fetch_open_orders(symbol=(symbol or None))
        normalized = [ex.normalize_order(o) for o in (orders or [])][-max(0, int(limit)) :]
        return _json_ok({"exchange": exchange, "market_type": market_type, "orders": normalized})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def list_cex_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str:
    """
    List recent orders (open, filled, and cancelled) from a centralized exchange.

    Returns order history including both active and completed orders. Useful
    for reviewing trading activity and reconciling execution history.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        orders = ex.fetch_orders(symbol=(symbol or None), limit=int(limit) if limit else None)
        normalized = [ex.normalize_order(o) for o in (orders or [])]
        return _json_ok({"exchange": exchange, "market_type": market_type, "orders": normalized})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def get_cex_my_trades(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str:
    """
    Fetch executed trades (fills) from a centralized exchange.

    Returns actual trade executions with price, quantity, and fee information.
    Useful for P&L calculation, tax reporting, and execution analysis.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        trades = ex.fetch_my_trades(symbol=(symbol or None), limit=int(limit) if limit else None)
        return _json_ok({"exchange": exchange, "market_type": market_type, "trades": trades})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def cancel_all_cex_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot") -> str:
    """
    Cancel all open orders on a centralized exchange.

    Emergency function to cancel all pending orders. Can be filtered by symbol.
    Useful for risk management and rapid position unwinding.
    Note: not all exchanges support this operation.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        res = ex.cancel_all_orders(symbol=(symbol or None))
        return _json_ok({"exchange": exchange, "market_type": market_type, "result": res})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def replace_cex_order(
    exchange: str,
    order_id: str,
    symbol: str,
    side: str,
    amount: float,
    order_type: str = "limit",
    price: float | None = None,
    market_type: str = "spot",
) -> str:
    """
    Replace (edit) an existing order on a centralized exchange.

    Atomically cancels the existing order and places a new one with updated
    parameters. Useful for adjusting limit prices without losing queue position.
    Note: not all exchanges support this operation.
    """
    try:
        _require_live_allowed(venue="cex")
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        res = ex.replace_order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            amount=float(amount),
            order_type=order_type,
            price=float(price) if price is not None else None,
            params=None,
        )
        return _json_ok({"exchange": exchange, "market_type": market_type, "order": ex.normalize_order(res)})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def wait_for_cex_order(
    exchange: str,
    order_id: str,
    symbol: str = "",
    market_type: str = "spot",
    timeout_sec: int = 30,
    poll_interval_sec: float = 2.0,
) -> str:
    """
    Wait for an order to reach a terminal state (filled, cancelled, rejected).

    Polls the exchange at regular intervals until the order completes or
    the timeout is reached. Useful for synchronous execution flows.
    Returns the final order state.
    """
    try:
        _require_live_allowed(venue="cex")
        deadline = time.time() + max(1.0, float(timeout_sec))
        while True:
            res = json.loads(get_cex_order(order_id, symbol=symbol, exchange=exchange, market_type=market_type))
            if not res.get("ok"):
                return json.dumps(res, indent=2, sort_keys=True)
            order = (res.get("data") or {}).get("order") or {}
            status = str(order.get("status") or "").lower()
            if status in {"closed", "canceled", "cancelled", "rejected", "expired"}:
                return _json_ok({"exchange": exchange, "market_type": market_type, "order": order})
            if time.time() >= deadline:
                return _json_err("timeout", "Timed out waiting for order terminal status.", {"order": order})
            time.sleep(max(0.25, float(poll_interval_sec)))
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def start_cex_private_ws(exchange: str = "binance", market_type: str = "spot") -> str:
    """
    Start a private WebSocket stream for real-time order/execution updates.

    Supports native WebSocket for: Binance, Kraken, Coinbase.
    For other exchanges, falls back to REST polling.
    Provides real-time notifications of order fills and status changes.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Private updates are not supported in paper mode.")
    try:
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = (exchange or "").strip().lower()
        mt = (market_type or "spot").strip().lower()

        # Native WebSocket support for major exchanges
        if ex == "binance":
            global_container.binance_user_streams.start(market_type=mt)
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "status": "started"})

        if ex == "kraken":
            global_container.kraken_user_streams.start()
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "status": "started"})

        if ex in ("coinbase", "coinbasepro", "coinbaseadvanced"):
            global_container.coinbase_user_streams.start()
            return _json_ok({"mode": "ws", "exchange": "coinbase", "market_type": mt, "status": "started"})

        # Fallback to REST polling for other exchanges
        poll = float((os.getenv("CEX_PRIVATE_POLL_INTERVAL_SEC") or "2.0").strip() or "2.0")
        global_container.cex_private_updates.start(exchange=ex, market_type=mt, poll_interval_sec=poll)
        return _json_ok({"mode": "poll", "exchange": ex, "market_type": mt, "status": "started"})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def stop_cex_private_ws(exchange: str = "binance", market_type: str = "spot") -> str:
    """
    Stop a private WebSocket stream for order/execution updates.

    Cleanly disconnects from the exchange's private update channel.
    Should be called when monitoring is no longer needed.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Private updates are not supported in paper mode.")
    try:
        ex = (exchange or "").strip().lower()
        mt = (market_type or "spot").strip().lower()

        if ex == "binance":
            global_container.binance_user_streams.stop(market_type=mt)
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "status": "stopped"})

        if ex == "kraken":
            global_container.kraken_user_streams.stop()
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "status": "stopped"})

        if ex in ("coinbase", "coinbasepro", "coinbaseadvanced"):
            global_container.coinbase_user_streams.stop()
            return _json_ok({"mode": "ws", "exchange": "coinbase", "market_type": mt, "status": "stopped"})

        global_container.cex_private_updates.stop(exchange=ex, market_type=mt)
        return _json_ok({"mode": "poll", "exchange": ex, "market_type": mt, "status": "stopped"})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def list_cex_private_updates(exchange: str = "binance", market_type: str = "spot", limit: int = 100) -> str:
    """
    List recent private updates (order fills, status changes) from exchange.

    Returns buffered events from the active private update stream.
    Events include order executions, status changes, and account updates.
    Requires start_cex_private_ws to be called first.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Private updates are not supported in paper mode.")
    try:
        ex = (exchange or "").strip().lower()
        mt = (market_type or "spot").strip().lower()

        if ex == "binance":
            events = global_container.binance_user_streams.list_events(market_type=mt, limit=int(limit))
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "events": events})

        if ex == "kraken":
            events = global_container.kraken_user_streams.list_events(limit=int(limit))
            return _json_ok({"mode": "ws", "exchange": ex, "market_type": mt, "events": events})

        if ex in ("coinbase", "coinbasepro", "coinbaseadvanced"):
            events = global_container.coinbase_user_streams.list_events(limit=int(limit))
            return _json_ok({"mode": "ws", "exchange": "coinbase", "market_type": mt, "events": events})

        events = global_container.cex_private_updates.list_events(exchange=ex, market_type=mt, limit=int(limit))
        return _json_ok({"mode": "poll", "exchange": ex, "market_type": mt, "events": events})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def register_execution_tools(mcp: FastMCP):
    # DEX / on-chain
    mcp.tool()(swap_tokens)
    mcp.tool()(transfer_eth)

    # CEX execution & account tools
    mcp.tool()(place_cex_order)
    mcp.tool()(get_cex_balance)
    mcp.tool()(get_cex_order)
    mcp.tool()(cancel_cex_order)
    mcp.tool()(wait_for_cex_order)
    mcp.tool()(get_cex_capabilities)
    mcp.tool()(list_cex_open_orders)
    mcp.tool()(list_cex_orders)
    mcp.tool()(get_cex_my_trades)
    mcp.tool()(cancel_all_cex_orders)
    mcp.tool()(replace_cex_order)

    # Private updates
    mcp.tool()(start_cex_private_ws)
    mcp.tool()(stop_cex_private_ws)
    mcp.tool()(list_cex_private_updates)
