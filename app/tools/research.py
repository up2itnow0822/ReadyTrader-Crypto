from typing import Optional

from fastmcp import FastMCP

from app.core.container import global_container
from app.core.jsonio import json_err as _json_err
from app.core.jsonio import json_ok as _json_ok
from intelligence import analyze_social_sentiment, fetch_financial_news, fetch_rss_news


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
        """Score recent X/Reddit text for the symbol (-1 bearish .. +1 bullish) and cache it for the Risk Guardian."""
        return _json_ok({"symbol": symbol, "social_sentiment": analyze_social_sentiment(symbol)})

    @mcp.tool()
    def get_financial_news(symbol: str) -> str:
        """Get simulated high-tier financial news (Bloomberg/Reuters)."""
        return _json_ok({"symbol": symbol, "financial_news": fetch_financial_news(symbol)})

    @mcp.tool()
    def get_free_news(symbol: str = "") -> str:
        """Get free market news from RSS feeds."""
        # Fix: ensure fetch_rss_news is imported
        try:
            return _json_ok({"symbol": symbol, "news": fetch_rss_news(symbol)})
        except NameError:
            return _json_err("import_error", "fetch_rss_news not available")

    @mcp.tool()
    def post_market_insight(symbol: str, agent_id: str, signal: str, confidence: float, reasoning: str, ttl_seconds: int = 3600) -> str:
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
