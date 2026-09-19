import json
from typing import Any, Dict

from fastmcp import FastMCP

from app.core.config import settings
from app.core.container import global_container
from intelligence import get_cached_sentiment


def _json_ok(data: Dict[str, Any] | None = None) -> str:
    payload = {"ok": True, "data": data or {}}
    return json.dumps(payload, indent=2, sort_keys=True)


def _json_err(code: str, message: str, data: Dict[str, Any] | None = None) -> str:
    payload = {"ok": False, "error": {"code": code, "message": message, "data": data or {}}}
    return json.dumps(payload, indent=2, sort_keys=True)


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


def deposit_paper_funds(asset: str, amount: float) -> str:
    """[PAPER MODE] Deposit fake funds into the paper trading wallet."""
    if not settings.PAPER_MODE:
        return _json_err("paper_mode_required", "Paper mode is NOT enabled.")
    return _json_ok({"result": global_container.paper_engine.deposit("agent_zero", asset, amount)})


def validate_trade_risk(side: str, symbol: str, amount_usd: float, portfolio_value: float) -> str:
    """
    [GUARDIAN] Validate if a trade is safe to execute.

    Returns `result` ({allowed, reason}) and `sentiment`, the data the Falling Knife rule used:
    {score, status, texts, bullish, bearish, age_seconds}. status "ok" is a measured score;
    "no_data" / "not_configured" / "insufficient_data" mean a neutral 0.0 that the rule cannot
    act on (a "hint" says why) - call get_social_sentiment(symbol) first. This tool never
    fetches; it only reads the cached score.
    """
    try:
        sentiment = _sentiment_context(symbol)
        daily_loss = 0.0
        drawdown = 0.0

        if settings.PAPER_MODE and global_container.paper_engine:
            metrics = global_container.paper_engine.get_risk_metrics("agent_zero")
            daily_loss = metrics.get("daily_pnl_pct", 0.0)
            drawdown = metrics.get("drawdown_pct", 0.0)

        result = global_container.risk_guardian.validate_trade(side, symbol, amount_usd, portfolio_value, sentiment["score"], daily_loss, drawdown)
        return _json_ok(
            {
                "side": side,
                "symbol": symbol,
                "amount_usd": amount_usd,
                "sentiment": sentiment,
                "result": result,
            }
        )
    except Exception as e:
        return _json_err("risk_validation_error", str(e))


def register_trading_tools(mcp: FastMCP):
    mcp.tool()(deposit_paper_funds)
    mcp.tool()(validate_trade_risk)
