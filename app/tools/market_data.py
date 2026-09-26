from datetime import datetime, timezone

import pandas as pd
from fastmcp import FastMCP

from app.core.container import global_container
from app.core.jsonio import json_err as _json_err
from app.core.jsonio import json_ok as _json_ok
from app.tools.params import Integer


def register_market_tools(mcp: FastMCP):
    @mcp.tool()
    def get_sentiment() -> str:
        """Get the current Crypto Fear & Greed Index (alternative.me; no key needed)."""
        from intelligence import SourceError, fear_greed_index

        try:
            return _json_ok({"sentiment": fear_greed_index()})
        except SourceError as e:
            return _json_err(e.code, e.message)

    @mcp.tool()
    def get_news() -> str:
        """Hot crypto market news from CryptoPanic (needs CRYPTOPANIC_API_KEY)."""
        from intelligence import SourceError, market_news

        try:
            return _json_ok({"news": market_news()})
        except SourceError as e:
            return _json_err(e.code, e.message)

    @mcp.tool()
    def get_crypto_price(symbol: str, exchange: str = "binance") -> str:
        """
        Get the current price of a cryptocurrency.
        """
        try:
            res = global_container.marketdata_bus.fetch_ticker(symbol)
            ticker = res.data
            last_price = ticker.get("last")
            timestamp_ms = ticker.get("timestamp_ms")
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat() if timestamp_ms is not None else None
            return _json_ok(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "result": f"The current price of {symbol} is {last_price} (Source: {res.source})",
                    "price": float(last_price) if last_price is not None else None,
                    "source": res.source,
                    "timestamp": timestamp,
                }
            )
        except Exception as e:
            return _json_err("fetch_price_error", str(e), {"symbol": symbol})

    @mcp.tool()
    def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: Integer = 24) -> str:
        """
        Fetch historical OHLCV data.
        """
        try:
            df = global_container.backtest_engine.fetch_ohlcv(symbol, timeframe, limit)
            records = []
            for row in df.to_dict(orient="records"):
                ts = pd.Timestamp(row["timestamp"])
                ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                records.append(
                    {
                        "timestamp": ts.isoformat(),
                        "timestamp_ms": int(ts.value // 1_000_000),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                    }
                )
            return _json_ok(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit,
                    "data": records,
                }
            )
        except Exception as e:
            return _json_err("fetch_ohlcv_error", str(e))
