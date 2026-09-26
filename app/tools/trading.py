import math
from typing import Any, Dict, Optional, Tuple

from fastmcp import FastMCP

from app.core.config import settings
from app.core.container import global_container
from app.core.jsonio import json_err as _json_err
from app.core.jsonio import json_ok as _json_ok
from app.tools.params import Number
from execution.cex_executor import CexExecutor
from execution.evm import ERC20_MIN_ABI, erc20_decimals, get_web3
from intelligence import get_cached_sentiment
from paper_engine import USD_STABLES
from risk_manager import falling_knife_rules

PAPER_USER = "agent_zero"
# Selling into these is an exit: the proceeds are cash, not a new position. Selling into any other
# quote (ETH/BTC, SOL/ETH) buys the quote asset, and the proceeds count as new exposure.
CASH_QUOTES = USD_STABLES | frozenset({"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "TRY", "BRL", "KRW"})
# Wrapped tokens are priced as what they wrap.
PRICE_ALIASES = {"WETH": "ETH", "WBTC": "BTC"}
NATIVE_COIN_ADDRESS = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

SENTIMENT_HINTS = {
    "no_data": "Call get_social_sentiment(symbol) to load data for the Falling Knife check.",
    "not_configured": "Set TWITTER_BEARER_TOKEN and/or REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET; the Falling Knife check has no data source.",
    "insufficient_data": "The last get_social_sentiment(symbol) call returned too little text to measure; retry later or configure both X and Reddit.",
}


def _sentiment_context(symbol: str) -> Dict[str, Any]:
    """What the Falling Knife check is working from, so a neutral score is never mistaken for a measured one."""
    entry = get_cached_sentiment(symbol)
    if entry is None:
        return {"score": 0.0, "status": "no_data", "texts": 0, "bullish": 0, "bearish": 0, "age_seconds": None, "hint": SENTIMENT_HINTS["no_data"]}
    reading = entry["reading"]
    if not entry["configured"]:
        status = "not_configured"
    elif not reading.sufficient:
        status = "insufficient_data"
    else:
        status = "ok"
    context = {
        "score": reading.score,
        "status": status,
        "texts": reading.texts,
        "bullish": reading.bullish,
        "bearish": reading.bearish,
        "age_seconds": entry["age_seconds"],
    }
    if status != "ok":
        context["hint"] = SENTIMENT_HINTS[status]
    return context


def split_symbol(symbol: Any) -> Tuple[Optional[str], Optional[str]]:
    """BASE/QUOTE (upper case), or (None, None) when the symbol is not a pair. A ccxt contract suffix
    (BTC/USDT:USDT) is dropped."""
    base, sep, quote = str(symbol or "").strip().upper().partition("/")
    quote = quote.split(":", 1)[0].strip()
    if not sep or not base.strip() or not quote:
        return None, None
    return base.strip(), quote


def market_price(symbol: str) -> Optional[float]:
    """The market-data bus's last price for `symbol` (in its quote currency), or None. Never invented."""
    try:
        ticker = global_container.marketdata_bus.fetch_ticker(symbol).data or {}
        price = float(ticker.get("last") or ticker.get("close") or 0.0)
    except Exception:
        return None
    return price if math.isfinite(price) and price > 0 else None


def usd_price(asset: str) -> Optional[float]:
    """The USD value of one unit of `asset`: 1.0 for USD stablecoins, else the bus's ASSET/USDT price."""
    a = str(asset or "").strip().upper()
    a = PRICE_ALIASES.get(a, a)
    if not a:
        return None
    if a in USD_STABLES:
        return 1.0
    return market_price(f"{a}/USDT")


def _paper_equity_usd() -> Optional[float]:
    """The paper account's value in USD, marked to market where the bus has a price (otherwise at
    the last fill price; an asset with neither is left out)."""
    engine = global_container.paper_engine
    if engine is None:
        return None
    try:
        for asset in engine.get_balances(PAPER_USER):
            if asset.upper() not in USD_STABLES:
                price = usd_price(asset)
                if price is not None:
                    engine.mark_price_usd(asset, price)
        return float(engine.get_portfolio_value_usd(PAPER_USER))
    except Exception:
        return None


def _live_totals(exchange: str, market_type: str) -> Optional[Dict[str, float]]:
    """Total balance per asset on the exchange account, or None when it cannot be read."""
    try:
        balance = CexExecutor(exchange_id=exchange, market_type=market_type, auth=True).fetch_balance() or {}
        totals = balance.get("total") or {}
        return {str(k).upper(): float(v or 0.0) for k, v in totals.items()}
    except Exception:
        return None


def _value_usd(totals: Dict[str, float]) -> float:
    """Value of an exchange account's balances; an asset the bus cannot price is left out (so the
    account looks smaller and the size rule stricter, never looser)."""
    total = 0.0
    for asset, qty in totals.items():
        if not qty:
            continue
        price = usd_price(asset)
        if price is not None:
            total += qty * price
    return total


def _dex_wallet_value_usd(chain: str) -> Optional[float]:
    """The signer wallet's value on `chain`: the native coin plus the chain's known tokens
    (DexHandler.TOKEN_MAP), priced through the bus; a token the bus cannot price is left out. None
    when the wallet or the chain cannot be read."""
    try:
        w3 = get_web3(chain)
        owner = w3.to_checksum_address(global_container.signer.get_address())
        total = 0.0
        for token, address in (global_container.dex_handler.TOKEN_MAP.get(str(chain).lower()) or {}).items():
            price = usd_price(token)
            if price is None:
                continue
            if str(address).lower() == NATIVE_COIN_ADDRESS:
                qty = w3.eth.get_balance(owner) / 1e18
            else:
                contract = w3.eth.contract(address=w3.to_checksum_address(address), abi=ERC20_MIN_ABI)
                qty = contract.functions.balanceOf(owner).call() / (10 ** erc20_decimals(chain, address))
            total += float(qty) * price
        return total
    except Exception:
        return None


def exposure_added(side: str, amount: float, position: Optional[float]) -> float:
    """How much of an order opens or adds to exposure in the base asset, in base units. A BUY adds
    all of it. A SELL only reduces what is held; any part beyond the holding (or all of it, when the
    holding cannot be read) counts as new exposure."""
    if str(side).lower() == "buy":
        return float(amount)
    if position is None:
        return float(amount)
    return max(0.0, float(amount) - max(0.0, float(position)))


def _account_state(exchange: str, market_type: str, base: Optional[str], contract: bool = False) -> Dict[str, Any]:
    """equity_usd, position (base units held; None when unknown), daily_pnl_pct, drawdown_pct and the
    rules that could not be measured, for the mode the server runs in. `contract` is True for a
    derivatives symbol (BTC/USDT:USDT): its position is never a spot balance."""
    if settings.PAPER_MODE:
        engine = global_container.paper_engine
        # Mark the account to market first: the drawdown and daily-loss figures include its value now.
        equity = _paper_equity_usd()
        if engine:
            engine.mark_day_open(PAPER_USER)  # the daily-loss baseline, once per UTC day
        metrics = engine.get_risk_metrics(PAPER_USER) if engine else {}
        position = float(engine.get_balance(PAPER_USER, base)) if engine and base else None
        return {
            "equity_usd": equity,
            "position": position,
            "daily_pnl_pct": float(metrics.get("daily_pnl_pct", 0.0)),
            "drawdown_pct": float(metrics.get("drawdown_pct", 0.0)),
            "unmeasured": [],
        }
    totals = _live_totals(exchange, market_type)
    spot = (market_type or "spot").strip().lower() == "spot" and not contract
    return {
        "equity_usd": _value_usd(totals) if totals is not None else None,
        # A spot balance is the position. Margin/derivative positions are not balances, so they are
        # unknown here and every order is sized as new exposure.
        "position": (totals.get(base, 0.0) if base else None) if (totals is not None and spot) else None,
        "daily_pnl_pct": 0.0,
        "drawdown_pct": 0.0,
        "unmeasured": ["daily_loss_limit", "max_drawdown"],
    }


def _guardian(
    *,
    side: str,
    symbol: str,
    amount_usd_added: Optional[float],
    increases_exposure: bool,
    state: Dict[str, Any],
    sentiment: Dict[str, Any],
    missing: Optional[str],
) -> Dict[str, Any]:
    result = global_container.risk_guardian.validate_trade(
        side=side,
        symbol=symbol,
        amount_usd=amount_usd_added or 0.0,
        portfolio_value=state["equity_usd"] or 0.0,
        sentiment_score=sentiment["score"],
        daily_loss_pct=state["daily_pnl_pct"],
        current_drawdown_pct=state["drawdown_pct"],
        increases_exposure=increases_exposure,
    )
    allowed = bool(result.get("allowed", False))
    reason = str(result.get("reason") or "Risk policy violation")
    if allowed and increases_exposure and missing:
        # The size rule needs both numbers; without them it cannot run, so an order that adds exposure
        # fails closed. One that only reduces a position goes through: an exit.
        allowed, reason = False, missing
    return {"allowed": allowed, "reason": reason}


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def pre_trade_check(
    symbol: str,
    side: str,
    amount: float,
    price: Optional[float] = None,
    exchange: str = "binance",
    market_type: str = "spot",
    order_type: str = "market",
) -> Dict[str, Any]:
    """
    The Risk Guardian check every CEX order passes before it is filled, proposed or sent, with the
    account read fresh: paper orders against the paper account, live orders against the exchange
    account. The approval API runs it again at execution time (it re-runs the tool).

    The order is valued at the market-data bus's price, never at a price the caller supplies alone:
    a market order fills at the market whatever price it carries, and a limit order is valued at the
    higher of its limit and the market (a marketable limit fills at the market; a resting one at its
    limit). Without a market price an order that adds exposure is refused.

    Exposure added: a BUY adds all of it; a SELL adds only what it sells beyond the holding, plus -
    on a pair whose quote is not cash (ETH/BTC) - the quote asset it acquires. Returns {allowed,
    reason, reference_price, market_price, equity_usd, position_units, exposure_added_units,
    acquired_quote_usd, exposure_added_usd, sentiment, falling_knife, inactive_rules}.
    """
    base, quote = split_symbol(symbol)
    side_norm = str(side or "").strip().lower()
    kind = str(order_type or "market").strip().lower()
    units = _positive(amount)
    limit = _positive(price) if kind == "limit" else None
    invalid = None
    if units is None:
        invalid = f"amount must be a positive number, got {amount!r}"
    elif side_norm not in ("buy", "sell"):
        invalid = f"side must be 'buy' or 'sell', got {side!r}"
    elif kind == "limit" and limit is None:
        invalid = f"a limit order needs a positive price, got {price!r}"
    if invalid:
        return {
            "allowed": False,
            "reason": f"Risk Guardian cannot size this order: {invalid}.",
            "reference_price": None,
            "market_price": None,
            "equity_usd": None,
            "position_units": None,
            "exposure_added_units": None,
            "acquired_quote_usd": None,
            "exposure_added_usd": None,
            "sentiment": _sentiment_context(symbol),
            "falling_knife": falling_knife_rules(),
            "inactive_rules": [],
        }

    contract = ":" in str(symbol or "")
    state = _account_state(exchange, market_type, base, contract)
    market = market_price(symbol)
    reference = (max(market, limit) if limit else market) if market else None
    quote_usd = usd_price(quote) if quote else None
    added = exposure_added(side_norm, units, state["position"])
    acquires_quote = side_norm == "sell" and bool(quote) and quote not in CASH_QUOTES
    increases = added > 0 or acquires_quote
    # The Falling Knife rule judges what the order buys: the base on a BUY, the quote asset on a SELL
    # into a crypto quote (selling ETH on ETH/BTC buys BTC).
    bought = PRICE_ALIASES.get(quote, quote) if acquires_quote else symbol
    sentiment = _sentiment_context(bought)
    unit_usd = reference * quote_usd if (reference and quote_usd) else None
    acquired_usd = (units * unit_usd if unit_usd is not None else None) if acquires_quote else 0.0
    added_usd = added * unit_usd + acquired_usd if (unit_usd is not None and acquired_usd is not None) else None
    missing = None
    if market is None and increases:
        missing = f"No market price for {symbol}: the Risk Guardian values orders at the market, so an order that adds exposure waits for market data."
    elif added_usd is None:
        missing = f"Could not value {symbol} in USD for the position-size check; retry when market data is available."
    elif state["equity_usd"] is None:
        missing = f"Could not read the {'paper' if settings.PAPER_MODE else exchange} account's value for the position-size check."
    elif state["equity_usd"] <= 0:
        # 5% of nothing is nothing: an empty (or unpriceable) account must not skip the size rule.
        missing = f"The {'paper' if settings.PAPER_MODE else exchange} account has no value to size this order against."
    verdict = _guardian(
        side="buy" if acquires_quote else side_norm,
        symbol=f"{quote}/USD" if acquires_quote else symbol,
        amount_usd_added=added_usd,
        increases_exposure=increases,
        state=state,
        sentiment=sentiment,
        missing=missing,
    )
    return {
        **verdict,
        "reference_price": reference,
        "market_price": market,
        "equity_usd": state["equity_usd"],
        "position_units": state["position"],
        "exposure_added_units": added,
        "acquired_quote_usd": acquired_usd,
        "exposure_added_usd": added_usd,
        "sentiment": sentiment,
        "sentiment_asset": split_symbol(bought)[0] if "/" in str(bought) else bought,
        "falling_knife": falling_knife_rules(),
        "inactive_rules": state["unmeasured"],
    }


def swap_check(from_token: str, to_token: str, amount: float, rate: Optional[float], chain: str = "ethereum") -> Dict[str, Any]:
    """
    The Risk Guardian check for a swap of `amount` FROM into TO (`rate` = TO per FROM). A swap into a
    USD stablecoin only reduces exposure; any other swap buys TO, sized at the USD value of what is
    spent. Paper swaps are checked against the paper account, live swaps against the signer wallet's
    value on the chain (native coin + known tokens); when that cannot be read, a swap that adds
    exposure fails closed.
    """
    src, dst = str(from_token or "").strip().upper(), str(to_token or "").strip().upper()
    sentiment = _sentiment_context(PRICE_ALIASES.get(dst, dst))
    if settings.PAPER_MODE:
        state = _account_state("paper", "spot", None)
    else:
        state = {
            "equity_usd": _dex_wallet_value_usd(chain),
            "position": None,
            "daily_pnl_pct": 0.0,
            "drawdown_pct": 0.0,
            "unmeasured": ["daily_loss_limit", "max_drawdown"],
        }
    increases = dst not in USD_STABLES
    src_usd = usd_price(src)
    added_usd = float(amount) * src_usd if (increases and src_usd is not None) else (0.0 if not increases else None)
    missing = None
    if added_usd is None:
        missing = f"Could not value {src} in USD for the position-size check; retry when market data is available."
    elif state["equity_usd"] is None:
        missing = f"Could not read the {'paper account' if settings.PAPER_MODE else 'signer wallet on ' + str(chain)}'s value for the position-size check."
    elif state["equity_usd"] <= 0:
        missing = f"The {'paper account' if settings.PAPER_MODE else 'signer wallet on ' + str(chain)} has no value to size this swap against."
    verdict = _guardian(
        side="buy" if increases else "sell",
        symbol=f"{dst}/USD",
        amount_usd_added=added_usd,
        increases_exposure=increases,
        state=state,
        sentiment=sentiment,
        missing=missing,
    )
    return {
        **verdict,
        "rate": rate,
        "equity_usd": state["equity_usd"],
        "exposure_added_usd": added_usd,
        "sentiment": sentiment,
        "falling_knife": falling_knife_rules(),
        "inactive_rules": state["unmeasured"],
    }


def deposit_paper_funds(asset: str, amount: Number) -> str:
    """[PAPER MODE] Deposit fake funds into the paper trading wallet."""
    if not settings.PAPER_MODE:
        return _json_err("paper_mode_required", "Paper mode is NOT enabled.")
    import math

    from paper_engine import MAX_MAGNITUDE

    asset = str(asset or "").strip().upper()
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = float("nan")
    if not asset or len(asset) > 32 or "/" in asset:
        return _json_err("invalid_asset", f"Asset must be a ticker like USDT, got {asset!r}")
    if not math.isfinite(value) or value <= 0 or value > MAX_MAGNITUDE:
        return _json_err("invalid_amount", f"Deposit must be a positive number no larger than {MAX_MAGNITUDE:g}, got {amount!r}")
    # Read the engine's structured result: a deposit refused at the accumulated-balance check is
    # rolled back and credits nothing, and must not come back as ok:true with "Deposit refused"
    # sitting in a prose field.
    engine = global_container.paper_engine
    if asset not in USD_STABLES:
        # A deposit is capital added, valued at today's price. One that cannot be valued would later
        # read as a trading gain (and could end a drawdown halt), so it waits for market data.
        price = usd_price(asset)
        if price is None:
            return _json_err(
                "paper_price_required",
                f"No market price for {asset}: a paper deposit is valued at the market price. "
                "Deposit a USD stablecoin, or retry when market data is available.",
                {"asset": asset, "amount": value},
            )
        engine.mark_price_usd(asset, price)
    res = engine.deposit_result("agent_zero", asset, value)
    if not res["ok"]:
        return _json_err(res["code"], res["message"], {"asset": asset, "amount": value})
    return _json_ok({"result": res["message"], "asset": asset, "amount": value, "balance": res["balance"]})


def validate_trade_risk(side: str, symbol: str, amount_usd: Number, portfolio_value: Number) -> str:
    """
    [GUARDIAN] Ask the Risk Guardian about a trade before placing it (the same rules also run on
    every order: place_cex_order and swap_tokens refuse a trade they would refuse).

    Rules: the part of a trade that adds exposure may be at most 5% of the portfolio; after a 5%
    daily loss or a 10% drawdown only trades that reduce exposure pass; a measured sentiment below
    -0.5 blocks BUYs (Falling Knife). There is no price-based Falling Knife rule for crypto
    (`falling_knife` says why; docs/FALLING_KNIFE.md).

    Returns `result` ({allowed, reason}) and `sentiment`, the data the Falling Knife rule used:
    {score, status, texts, bullish, bearish, age_seconds}. status "ok" is a measured score;
    "no_data" / "not_configured" / "insufficient_data" mean a neutral 0.0 that the rule cannot
    act on (a "hint" says why) - call get_social_sentiment(symbol) first. This tool never
    fetches; it only reads the cached score.
    """
    side_norm = str(side or "").strip().lower()
    if side_norm not in ("buy", "sell"):
        return _json_err("invalid_request", f"side must be 'buy' or 'sell', got {side!r}", {"side": side})
    try:
        amount_usd, portfolio_value = float(amount_usd), float(portfolio_value)
    except (TypeError, ValueError):
        return _json_err("invalid_request", "amount_usd and portfolio_value must be numbers", {"amount_usd": amount_usd, "portfolio_value": portfolio_value})
    if not (math.isfinite(amount_usd) and amount_usd > 0 and math.isfinite(portfolio_value) and portfolio_value > 0):
        # A zero portfolio used to skip the size rule and answer "Trade looks safe".
        return _json_err(
            "invalid_request",
            "amount_usd and portfolio_value must be positive numbers",
            {"amount_usd": amount_usd, "portfolio_value": portfolio_value},
        )
    try:
        sentiment = _sentiment_context(symbol)
        daily_loss = 0.0
        drawdown = 0.0

        if settings.PAPER_MODE and global_container.paper_engine:
            _paper_equity_usd()  # marks the account to market, so the metrics include its value now
            global_container.paper_engine.mark_day_open(PAPER_USER)
            metrics = global_container.paper_engine.get_risk_metrics(PAPER_USER)
            daily_loss = metrics.get("daily_pnl_pct", 0.0)
            drawdown = metrics.get("drawdown_pct", 0.0)

        result = global_container.risk_guardian.validate_trade(side_norm, symbol, amount_usd, portfolio_value, sentiment["score"], daily_loss, drawdown)
        return _json_ok(
            {
                "side": side_norm,
                "symbol": symbol,
                "amount_usd": amount_usd,
                "sentiment": sentiment,
                "falling_knife": falling_knife_rules(),
                "result": result,
            }
        )
    except Exception as e:
        return _json_err("risk_validation_error", str(e))


def register_trading_tools(mcp: FastMCP):
    mcp.tool()(deposit_paper_funds)
    mcp.tool()(validate_trade_risk)
