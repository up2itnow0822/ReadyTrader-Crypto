from __future__ import annotations

import contextvars
import json
import logging
import math
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from fastmcp import FastMCP
from web3 import Web3

from app.core.config import settings
from app.core.container import global_container
from app.core.jsonio import json_dumps as _json_dumps
from app.core.jsonio import json_err as _json_err
from app.core.jsonio import json_ok as _json_ok
from app.tools.params import Integer, Number
from app.tools.trading import market_price, pre_trade_check, swap_check, usd_price
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
from policy_engine import PolicyError

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


class LiveGateRefused(ValueError):
    """A live action refused by the operator's switches; `code` is what the tool answers with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_internal_error(
    code: str,
    public_message: str,
    exc: Exception,
    data: Dict[str, Any] | None = None,
) -> str:
    # An operator's own switch or policy saying no is not an exchange failure: say which rule, so an
    # agent can tell the kill switch from an outage. Only unexpected errors keep the fixed message.
    if isinstance(exc, LiveGateRefused):
        logger.info("%s: %s", exc.code, exc)
        return _json_err(exc.code, str(exc), data)
    if isinstance(exc, PolicyError):
        logger.info("%s: %s", exc.code, exc.message)
        return _json_err(exc.code, exc.message, {**(data or {}), **(exc.data or {})})
    logger.exception("%s: %s", code, exc)
    return _json_err(code, public_message, data)


def _require_live_allowed(*, venue: str, allowed_while_halted: bool = False) -> None:
    """The operator's live switches. `allowed_while_halted` is for actions that read the account or
    reduce risk (look up, list, cancel orders): the kill switch stops new orders, and while it is on an
    operator must still be able to see and cancel what is resting on the exchange."""
    if settings.PAPER_MODE:
        return
    if not settings.LIVE_TRADING_ENABLED:
        raise LiveGateRefused("live_trading_disabled", "LIVE_TRADING_ENABLED=false (live execution is disabled)")
    if settings.TRADING_HALTED and not allowed_while_halted:
        raise LiveGateRefused("trading_halted", "TRADING_HALTED=true (live execution is halted)")
    if not venue_allowed(settings.EXECUTION_MODE, venue):
        raise LiveGateRefused("execution_mode_blocked", f"Execution blocked by EXECUTION_MODE={settings.EXECUTION_MODE.value} for venue={venue}")


# True only inside approved_execution(), and only for the thread/task that entered it.
_APPROVED_EXECUTION: contextvars.ContextVar[bool] = contextvars.ContextVar("readytrader_approved_execution", default=False)


@contextmanager
def approved_execution() -> Iterator[None]:
    """
    Run the enclosed tool call as the execution of an ALREADY human-approved proposal.

    Only the HTTP approval endpoint may use this, after ExecutionStore.confirm*(). It replaces the old
    approach of flipping the process-wide EXECUTION_APPROVAL_MODE to "auto" for the duration of the
    exchange round-trip, which switched the approval gate off for every other caller in the process.
    A ContextVar is visible to the current thread/task only. All other gates (live flags, halt,
    execution mode, policy engine) still run for the approved call.
    """
    token = _APPROVED_EXECUTION.set(True)
    try:
        yield
    finally:
        _APPROVED_EXECUTION.reset(token)


def _maybe_propose(kind: str, payload: Dict[str, Any]) -> Optional[str]:
    """
    If approve-each is enabled, create an execution proposal and return its JSON response string.
    The proposal records the mode it was made in; the approval API executes it only in that mode.
    """
    if settings.PAPER_MODE:
        return None
    if _APPROVED_EXECUTION.get():
        return None
    if settings.EXECUTION_APPROVAL_MODE != "approve_each":
        return None
    payload = {**payload, "paper_mode": bool(settings.PAPER_MODE)}
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


def _paper_reference_price(symbol: str) -> float | None:
    """
    The market price a paper order fills at, from the market-data bus. None (never a fabricated
    price) when the bus has no usable ticker for `symbol`: the paper order is then refused.
    """
    return market_price(symbol)


def _swap_rate(from_token: str, to_token: str) -> float | None:
    """Units of TO received per unit of FROM at market: FROM/TO, else 1 / (TO/FROM), else through
    USD (FROM/USDT over TO/USDT). None when the bus cannot price the pair."""
    src, dst = str(from_token or "").strip().upper(), str(to_token or "").strip().upper()
    direct = market_price(f"{src}/{dst}")
    if direct:
        return direct
    inverse = market_price(f"{dst}/{src}")
    if inverse:
        return 1.0 / inverse
    src_usd, dst_usd = usd_price(src), usd_price(dst)
    if src_usd and dst_usd:
        return src_usd / dst_usd
    return None


def _risk_blocked(check: Dict[str, Any], **context: Any) -> str:
    return _json_err("risk_blocked", str(check.get("reason") or "Risk Guardian refused the order."), {**context, "risk": check})


def _paper_mode_refusal(action: str) -> Optional[str]:
    """Paper mode never reaches an exchange account: paper orders fill immediately in the paper
    engine, so there are no exchange orders to look up, cancel or replace."""
    if not settings.PAPER_MODE:
        return None
    return _json_err(
        "paper_mode_not_supported",
        f"{action} works on a live exchange account; paper orders fill immediately and never rest on an exchange. get_cex_balance shows the paper wallet.",
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
    amount: Number,
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
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return _json_err("invalid_amount", f"amount must be a positive number, got {amount!r}", {"symbol": symbol})
    if not math.isfinite(amount) or amount <= 0:
        return _json_err("invalid_amount", f"amount must be a positive number, got {amount!r}", {"symbol": symbol})

    if settings.PAPER_MODE:
        if not global_container.paper_engine:
            return _json_err("paper_engine_missing", "Paper engine not initialized.")
        # A paper swap trades at the market rate. It used to fill at a fixed 1.0: 1 ETH -> 1 USDC.
        rate = _swap_rate(from_token, to_token)
        if rate is None:
            return _json_err(
                "paper_price_required",
                f"No market rate for {symbol} (directly, inverted, or through USDT); a paper swap needs one.",
                {"venue": "dex", "mode": "paper", "symbol": symbol},
            )
        check = swap_check(from_token, to_token, amount, rate)
        if not check["allowed"]:
            return _risk_blocked(check, venue="dex", mode="paper", symbol=symbol)
        res = global_container.paper_engine.execute_trade_result(
            user_id="agent_zero",
            side="sell",
            symbol=symbol,
            amount=amount,
            price=rate,
            rationale=rationale or "swap_tokens_paper",
        )
        if not res["ok"]:
            return _json_err(res["code"], res["message"], {"venue": "dex", "mode": "paper", "symbol": symbol})
        return _json_ok({"venue": "dex", "mode": "paper", "result": res["message"], "fill": res["fill"], "risk": check})

    try:
        _require_live_allowed(venue="dex")
        # Policy, then the Risk Guardian: before a proposal is made and again when an approved
        # proposal executes.
        global_container.policy_engine.validate_swap(chain=chain, from_token=from_token, to_token=to_token, amount=amount)
        check = swap_check(from_token, to_token, amount, None, chain=chain)
        if not check["allowed"]:
            return _risk_blocked(check, venue="dex", mode="live", symbol=symbol)
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


def transfer_eth(to_address: str, amount: Number, chain: str = "ethereum", idempotency_key: str = "") -> str:
    """
    Transfer native currency (ETH/BASE/ARB/OP native token).
    Live mode signs and broadcasts via JSON-RPC.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Native transfers are not supported in paper mode.")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = float("nan")
    if not math.isfinite(amount) or amount <= 0:
        return _json_err("invalid_amount", "amount must be a positive number", {"to_address": to_address, "chain": chain})
    try:
        _require_live_allowed(venue="dex")
        # Policy first, so an operator is never asked to approve a transfer that would be refused.
        global_container.policy_engine.validate_transfer_native(chain=chain, to_address=to_address, amount=amount)
        proposed = _maybe_propose(
            "transfer_eth",
            {"to_address": to_address, "amount": amount, "chain": chain, "idempotency_key": idempotency_key},
        )
        if proposed:
            return proposed

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


def _order_args(symbol: str, side: Any, amount: Any, order_type: Any, price: Any, market_type: Any = "spot") -> Tuple[Optional[str], Dict[str, Any]]:
    """Validate an order's side, type, amount and price. Returns (error JSON or None, normalised
    {side, order_type, amount, price}); price is None when none was given (None or 0)."""
    if ":" in str(symbol or "") and str(market_type or "spot").strip().lower() == "spot":
        # ccxt routes a contract symbol (BTC/USDT:USDT) to the derivatives account whatever
        # market_type says, so a "spot" order on one would dodge the market-type allowlist and the
        # spot position check.
        return _json_err(
            "invalid_symbol",
            f"{symbol} is a contract (perpetual/futures) symbol: pass market_type='swap' or 'future', or use the spot pair.",
            {"symbol": symbol},
        ), {}
    side_norm = str(side or "").strip().lower()
    order_type_norm = str(order_type or "market").strip().lower()
    if side_norm not in ("buy", "sell"):
        return _json_err("invalid_side", f"side must be 'buy' or 'sell', got {side!r}", {"symbol": symbol}), {}
    if order_type_norm not in ("market", "limit"):
        return _json_err("invalid_order_type", f"order_type must be 'market' or 'limit', got {order_type!r}", {"symbol": symbol}), {}
    try:
        units = float(amount)
    except (TypeError, ValueError):
        units = float("nan")
    if not math.isfinite(units) or units <= 0:
        return _json_err("invalid_amount", f"amount must be a positive number, got {amount!r}", {"symbol": symbol}), {}
    # None or 0 means "no price given". Anything else must be a real price.
    try:
        explicit = float(price) if price not in (None, 0, 0.0) else None
    except (TypeError, ValueError):
        return _json_err("invalid_price", f"Price must be a positive number, got {price!r}", {"symbol": symbol}), {}
    if explicit is not None and not (math.isfinite(explicit) and explicit > 0):
        return _json_err("invalid_price", f"Price must be a positive number, got {price!r}", {"symbol": symbol}), {}
    if order_type_norm == "limit" and explicit is None:
        return _json_err("invalid_price", "A limit order needs a positive price.", {"symbol": symbol}), {}
    return None, {"side": side_norm, "order_type": order_type_norm, "amount": units, "price": explicit}


def place_cex_order(
    symbol: str,
    side: str,
    amount: Number,
    order_type: str = "market",
    price: Number | None = None,
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

    error, args = _order_args(symbol, side, amount, order_type, price, market_type)
    if error:
        return error
    side_norm, order_type_norm, amount, explicit = args["side"], args["order_type"], args["amount"], args["price"]

    if settings.PAPER_MODE:
        if not global_container.paper_engine:
            return _json_err("paper_engine_missing", "Paper engine not initialized.")
        # Paper fills at the market price, as an exchange would: a market order ignores any price it
        # is given, and a limit order fills (at the market) only when it is marketable. Resting limit
        # orders are not simulated. Filling at the caller's price let one round trip invent profit.
        market = _paper_reference_price(symbol)
        if market is None:
            return _json_err(
                "paper_price_required",
                f"No market price is available for {symbol}; paper orders fill at the market price. Check get_crypto_price({symbol!r}).",
                {"venue": "cex", "mode": "paper", "symbol": symbol},
            )
        if order_type_norm == "limit" and ((side_norm == "buy" and market > explicit) or (side_norm == "sell" and market < explicit)):
            return _json_err(
                "limit_not_marketable",
                f"Limit {side_norm.upper()} at {explicit} would rest on the book (market {market}); "
                "paper mode fills only marketable orders and does not simulate resting orders.",
                {"venue": "cex", "mode": "paper", "symbol": symbol, "limit_price": explicit, "market_price": market},
            )
        # It fills now, at the market: sized as a market order.
        check = pre_trade_check(symbol, side_norm, amount, exchange=exchange, market_type=market_type, order_type="market")
        if not check["allowed"]:
            return _risk_blocked(check, venue="cex", mode="paper", symbol=symbol)
        res = global_container.paper_engine.execute_trade_result(
            user_id="agent_zero",
            side=side_norm,
            symbol=symbol,
            amount=amount,
            price=market,
            rationale="cex_order_paper",
        )
        if not res["ok"]:
            return _json_err(res["code"], res["message"], {"venue": "cex", "mode": "paper", "symbol": symbol})
        return _json_ok({"venue": "cex", "mode": "paper", "result": res["message"], "fill": res["fill"], "risk": check})

    try:
        _require_live_allowed(venue="cex")
        # The policy and the Risk Guardian run before a proposal is made (so an operator is never
        # asked to approve an order that would be refused) and again when an approved proposal
        # executes (the approval API re-runs this tool): the account and market move while it waits.
        global_container.policy_engine.validate_cex_order(
            exchange_id=exchange,
            symbol=symbol,
            market_type=market_type,
            side=side_norm,
            amount=amount,
            order_type=order_type_norm,
            price=price,
        )
        check = pre_trade_check(symbol, side_norm, amount, explicit, exchange=exchange, market_type=market_type, order_type=order_type_norm)
        if not check["allowed"]:
            return _risk_blocked(check, venue="cex", mode="live", symbol=symbol)
        proposed = _maybe_propose(
            "place_cex_order",
            {
                "symbol": symbol,
                "side": side_norm,
                "amount": amount,
                "order_type": order_type_norm,
                "price": price,
                "exchange": exchange,
                "market_type": market_type,
                "idempotency_key": idempotency_key,
            },
        )
        if proposed:
            return proposed

        if idempotency_key:
            cached = global_container.idempotency_store.get(idempotency_key)
            if cached is not None:
                return _json_ok({"venue": "cex", "mode": "live", "idempotency_key": idempotency_key, **cached})

        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        params = {"clientOrderId": idempotency_key} if idempotency_key else None
        order = ex.place_order(
            symbol=symbol,
            side=side_norm,
            amount=float(amount),
            order_type=order_type_norm,
            price=float(price) if price is not None else None,
            params=params,
        )
        normalized = ex.normalize_order(order)
        summary = {
            "exchange": exchange,
            "market_type": market_type,
            "symbol": symbol,
            "side": side_norm,
            "amount": amount,
            "order_type": order_type_norm,
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

    In paper mode, returns the paper wallet's balances and does not require CEX
    credentials. Live mode requires CEX credentials configured via environment
    variables (CEX_API_KEY, CEX_API_SECRET).
    """
    if settings.PAPER_MODE:
        if not global_container.paper_engine:
            return _json_err("paper_engine_missing", "Paper engine not initialized.")
        return _json_ok(
            {
                "exchange": exchange,
                "market_type": market_type,
                "mode": "paper",
                "balance": global_container.paper_engine.get_balances("agent_zero"),
            }
        )
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
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
    refused = _paper_mode_refusal("get_cex_order")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
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
    refused = _paper_mode_refusal("cancel_cex_order")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
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


def list_cex_open_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: Integer = 100) -> str:
    """
    List all currently open (unfilled) orders on a centralized exchange.

    Returns orders that are pending execution. Can be filtered by symbol.
    Useful for monitoring active positions and managing order book exposure.
    """
    refused = _paper_mode_refusal("list_cex_open_orders")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        orders = ex.fetch_open_orders(symbol=(symbol or None))
        normalized = [ex.normalize_order(o) for o in (orders or [])][-max(0, int(limit)) :]
        return _json_ok({"exchange": exchange, "market_type": market_type, "orders": normalized})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def list_cex_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: Integer = 100) -> str:
    """
    List recent orders (open, filled, and cancelled) from a centralized exchange.

    Returns order history including both active and completed orders. Useful
    for reviewing trading activity and reconciling execution history.
    """
    refused = _paper_mode_refusal("list_cex_orders")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
        global_container.policy_engine.validate_cex_access(exchange_id=exchange)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        orders = ex.fetch_orders(symbol=(symbol or None), limit=int(limit) if limit else None)
        normalized = [ex.normalize_order(o) for o in (orders or [])]
        return _json_ok({"exchange": exchange, "market_type": market_type, "orders": normalized})
    except Exception as e:
        return _json_internal_error("cex_error", "Exchange operation failed.", e)


def get_cex_my_trades(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: Integer = 100) -> str:
    """
    Fetch executed trades (fills) from a centralized exchange.

    Returns actual trade executions with price, quantity, and fee information.
    Useful for P&L calculation, tax reporting, and execution analysis.
    """
    refused = _paper_mode_refusal("get_cex_my_trades")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
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
    refused = _paper_mode_refusal("cancel_all_cex_orders")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
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
    amount: Number,
    order_type: str = "limit",
    price: Number | None = None,
    market_type: str = "spot",
) -> str:
    """
    Replace (edit) an existing order on a centralized exchange.

    Atomically cancels the existing order and places a new one with updated
    parameters. Useful for adjusting limit prices without losing queue position.
    Note: not all exchanges support this operation.
    """
    refused = _paper_mode_refusal("replace_cex_order")
    if refused:
        return refused
    error, args = _order_args(symbol, side, amount, order_type, price, market_type)
    if error:
        return error
    try:
        _require_live_allowed(venue="cex")
        if settings.EXECUTION_APPROVAL_MODE == "approve_each" and not _APPROVED_EXECUTION.get():
            # A replacement is a new order. It used to skip the approval gate entirely.
            return _json_err(
                "approval_required",
                "replace_cex_order cannot go through EXECUTION_APPROVAL_MODE=approve_each: cancel_cex_order, then place_cex_order (which returns a proposal).",
                {"exchange": exchange, "order_id": order_id},
            )
        # The replacement order passes the same policy and Risk Guardian checks as place_cex_order.
        global_container.policy_engine.validate_cex_order(
            exchange_id=exchange,
            symbol=symbol,
            market_type=market_type,
            side=args["side"],
            amount=args["amount"],
            order_type=args["order_type"],
            price=float(price) if price is not None else None,
        )
        check = pre_trade_check(symbol, args["side"], args["amount"], args["price"], exchange=exchange, market_type=market_type, order_type=args["order_type"])
        if not check["allowed"]:
            return _risk_blocked(check, venue="cex", mode="live", symbol=symbol)
        ex = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True)
        res = ex.replace_order(
            order_id=order_id,
            symbol=symbol,
            side=args["side"],
            amount=args["amount"],
            order_type=args["order_type"],
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
    timeout_sec: Integer = 30,
    poll_interval_sec: Number = 2.0,
) -> str:
    """
    Wait for an order to reach a terminal state (filled, cancelled, rejected).

    Polls the exchange at regular intervals until the order completes or
    the timeout is reached. Useful for synchronous execution flows.
    Returns the final order state.
    """
    refused = _paper_mode_refusal("wait_for_cex_order")
    if refused:
        return refused
    try:
        _require_live_allowed(venue="cex", allowed_while_halted=True)
        deadline = time.time() + max(1.0, float(timeout_sec))
        while True:
            res = json.loads(get_cex_order(order_id, symbol=symbol, exchange=exchange, market_type=market_type))
            if not res.get("ok"):
                return _json_dumps(res)
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
    Requires live execution to be allowed (LIVE_TRADING_ENABLED=true, TRADING_HALTED=false).

    Supports native WebSocket for: Binance, Kraken, Coinbase.
    For other exchanges, falls back to REST polling.
    Provides real-time notifications of order fills and status changes.
    """
    if settings.PAPER_MODE:
        return _json_err("paper_mode_not_supported", "Private updates are not supported in paper mode.")
    try:
        _require_live_allowed(venue="cex")
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


def list_cex_private_updates(exchange: str = "binance", market_type: str = "spot", limit: Integer = 100) -> str:
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
