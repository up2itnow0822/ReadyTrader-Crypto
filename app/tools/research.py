from typing import Optional

from fastmcp import FastMCP

from app.core.container import global_container
from app.core.jsonio import json_err as _json_err
from app.core.jsonio import json_ok as _json_ok
from app.tools.params import Integer, Number
from intelligence import SourceError, financial_news, get_cached_sentiment, rss_news, social_sentiment_report


def _rate_limit(tool_name: str) -> Optional[str]:
    # Shim to use the global rate limiter
    try:
        global_container.rate_limiter.check(key=f"tool:{tool_name}", limit=120, window_seconds=60)
        return None
    except Exception as e:
        return _json_err("rate_limited", str(e))


def register_research_tools(mcp: FastMCP):
    @mcp.tool()
    def get_social_sentiment(symbol: str) -> str:
        """Score recent X/Reddit text for the symbol (-1 bearish .. +1 bullish) and cache it for the Risk Guardian.
        Answers not_configured when neither TWITTER_BEARER_TOKEN nor REDDIT_CLIENT_ID/SECRET is set, and
        source_unavailable when every configured source failed."""
        text, sources = social_sentiment_report(symbol)
        entry = get_cached_sentiment(symbol)
        if entry is not None and not entry["configured"]:
            # The Guardian still records "not_configured" (validate_trade_risk reports it); the agent
            # gets an error, not a text that reads like a result.
            return _json_err("not_configured", text, {"symbol": symbol})
        configured = [state for state in sources.values() if state != "not_configured"]
        if configured and all(state == "error" for state in configured):
            return _json_err("source_unavailable", text, {"symbol": symbol, "sources": sources})
        return _json_ok({"symbol": symbol, "social_sentiment": text, "sources": sources})

    @mcp.tool()
    def get_financial_news(symbol: str) -> str:
        """Headlines about the symbol from NewsAPI (needs NEWSAPI_KEY)."""
        try:
            return _json_ok({"symbol": symbol, "financial_news": financial_news(symbol)})
        except SourceError as e:
            return _json_err(e.code, e.message, {"symbol": symbol})

    @mcp.tool()
    def get_free_news(symbol: str = "") -> str:
        """Get free market news from RSS feeds (CoinDesk, Cointelegraph); no key needed."""
        try:
            return _json_ok({"symbol": symbol, "news": rss_news(symbol)})
        except SourceError as e:
            return _json_err(e.code, e.message, {"symbol": symbol})

    @mcp.tool()
    def post_market_insight(symbol: str, agent_id: str, signal: str, confidence: Number, reasoning: str, ttl_seconds: Integer = 3600) -> str:
        """[PHASE 3] Share a market insight with other agents."""
        insight = global_container.insight_store.post_insight(symbol, agent_id, signal, confidence, reasoning, ttl_seconds)
        return _json_ok({"insight": vars(insight)})

    @mcp.tool()
    def get_latest_insights(symbol: str = "") -> str:
        """[PHASE 3] Get the most recent high-signal insights."""
        insights = global_container.insight_store.get_latest_insights(symbol if symbol else None)
        return _json_ok({"insights": [vars(i) for i in insights]})

    @mcp.tool()
    def run_backtest_simulation(strategy_code: str, symbol: str, timeframe: str = "1h") -> str:
        """Run a strategy simulation against historical data."""
        result = global_container.backtest_engine.run(strategy_code, symbol, timeframe)
        return _json_ok({"result": result})

    @mcp.tool()
    def get_market_regime(symbol: str, timeframe: str = "1d") -> str:
        """Detect the current market regime (TRENDING, RANGING, VOLATILE)."""
        try:
            df = global_container.backtest_engine.fetch_ohlcv(symbol, timeframe, limit=100)
            result = global_container.regime_detector.detect(df)
            return _json_ok({"symbol": symbol, "timeframe": timeframe, "result": result})
        except Exception as e:
            return _json_err("market_regime_error", str(e), {"symbol": symbol, "timeframe": timeframe})
