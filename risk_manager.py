from typing import Any, Dict, Optional

MAX_DRAWDOWN_PCT = 0.10
DAILY_LOSS_LIMIT_PCT = -0.05
MAX_POSITION_PCT = 0.05
FALLING_KNIFE_SENTIMENT = -0.5


class RiskGuardian:
    def __init__(self):
        pass

    def validate_trade(
        self,
        side: str,
        symbol: str,
        amount_usd: float,
        portfolio_value: float,
        sentiment_score: float = 0.0,
        daily_loss_pct: float = 0.0,
        current_drawdown_pct: float = 0.0,
        increases_exposure: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Validate a trade against safety rules.

        `increases_exposure` says whether the order opens or adds to a position. The order path
        (app/tools/trading.pre_trade_check) works it out from the current holding and passes it:
        selling what is held is an exit, and `amount_usd` is then the value of the part that adds
        exposure. The drawdown, daily-loss and sentiment rules refuse only orders that add exposure.
        Without it (the advisory validate_trade_risk tool) a BUY is taken to add exposure and a SELL
        not.
        """
        adds_exposure = (str(side).lower() == "buy") if increases_exposure is None else bool(increases_exposure)
        halted = "Orders that add exposure are halted; orders that reduce or close a position are allowed."

        # Rule 0: account state. A drawdown of 10% from the account's best value, or a 5% loss today,
        # halts new exposure until the condition clears.
        if current_drawdown_pct >= MAX_DRAWDOWN_PCT and adds_exposure:
            return {"allowed": False, "reason": f"Max Drawdown Limit Hit ({current_drawdown_pct:.1%}). {halted}"}
        if daily_loss_pct <= DAILY_LOSS_LIMIT_PCT and adds_exposure:
            return {"allowed": False, "reason": f"Daily Loss Limit Hit ({daily_loss_pct:.1%}). {halted}"}

        # Rule 1: position sizing. The part of an order that adds exposure may be at most 5% of the
        # account's value.
        if portfolio_value > 0:
            trade_pct = amount_usd / portfolio_value
            if trade_pct > MAX_POSITION_PCT:
                return {"allowed": False, "reason": f"Position size too large ({trade_pct:.1%}). Max allowed is {MAX_POSITION_PCT:.0%}."}

        # Rule 2: "Don't Catch Falling Knives" (sentiment). A measured bull-bear spread below -0.5
        # blocks BUYs that add exposure. Crypto has no price-based Falling Knife rule: both
        # pre-registered crypto price rules failed held-out validation (docs/FALLING_KNIFE.md).
        if str(side).lower() == "buy" and adds_exposure and sentiment_score < FALLING_KNIFE_SENTIMENT:
            return {"allowed": False, "reason": "Guardian blocked BUY due to Extreme Bearish sentiment (Falling Knife protection)."}

        return {"allowed": True, "reason": "Trade looks safe."}


def falling_knife_rules() -> Dict[str, Any]:
    """What the Falling Knife check is made of for crypto, for tool responses."""
    return {
        "sentiment": {"active": True, "threshold": FALLING_KNIFE_SENTIMENT},
        "price": {
            "active": False,
            "reason": "No price-based Falling Knife rule ships for crypto: both pre-registered rules failed held-out validation (docs/FALLING_KNIFE.md).",
        },
    }
