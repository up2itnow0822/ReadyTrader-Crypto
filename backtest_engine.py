from typing import Any, Dict

import pandas as pd
import ta

from exchange_provider import ExchangeProvider
from strategy_sandbox import StrategyError, run_strategy


class BacktestEngine:
    def __init__(self):
        self.exchange = ExchangeProvider()

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> pd.DataFrame:
        """Fetch historical data and return as DataFrame."""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            raise ValueError(f"Error fetching data: {str(e)}")

    def run(
        self,
        strategy_code: str,
        symbol: str,
        timeframe: str = "1h",
        initial_capital: float = 10000.0,
    ) -> Dict[str, Any]:
        """
        Run a backtest using provided strategy code.
        Strategy code must define `def on_candle(price, rsi, state) -> str` returning 'buy', 'sell' or 'hold'.
        It runs in an isolated child process with no access to pandas, ta, files, network or this process.
        """
        try:
            # 1. Fetch Data
            df = self.fetch_ohlcv(symbol, timeframe, limit=500)

            # 2. Add Indicators (Pre-calc for ease)
            df["rsi"] = ta.momentum.rsi(df["close"], window=14)
            df["sma_20"] = ta.trend.sma_indicator(df["close"], window=20)
            df["sma_50"] = ta.trend.sma_indicator(df["close"], window=50)

            # 3. Run the strategy in the isolated sandbox (see strategy_sandbox.py).
            # The strategy never sees pandas/ta or this process: it receives plain floats
            # and returns one action per candle. All capital math stays here.
            closes = [float(v) for v in df["close"].tolist()]
            rsis = [None if pd.isna(v) else float(v) for v in df["rsi"].tolist()]
            try:
                outcome = run_strategy(strategy_code, [list(zip(closes, rsis))])
            except StrategyError as e:
                if e.kind == "runtime":
                    return {"error": f"Runtime error in strategy at row {e.row_idx}: {e.message}"}
                return {"error": e.message, "error_kind": e.kind}
            actions = outcome.actions[0]

            # 4. Simulation Loop
            capital = initial_capital
            position = 0.0  # Amount of asset
            trades = []
            timestamps = df["timestamp"].tolist()

            for pos, action in enumerate(actions):
                # Warm-up rows (RSI not yet defined) carry no action
                if action is None:
                    continue
                current_price = closes[pos]

                if action == "buy" and capital > 0:
                    # Buy All
                    amount = capital / current_price
                    position = amount
                    capital = 0
                    trades.append({"type": "buy", "price": current_price, "time": str(timestamps[pos])})

                elif action == "sell" and position > 0:
                    # Sell All
                    capital = position * current_price
                    position = 0
                    trades.append({"type": "sell", "price": current_price, "time": str(timestamps[pos])})

            # Final Value
            final_value = capital if capital > 0 else position * df.iloc[-1]["close"]
            pnl = final_value - initial_capital
            pnl_percent = (pnl / initial_capital) * 100

            return {
                "symbol": symbol,
                "initial_capital": initial_capital,
                "final_value": round(final_value, 2),
                "pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
                "total_trades": len(trades),
                "trades_log": trades[-5:],  # Show last 5
            }

        except Exception as e:
            return {"error": f"Backtest Engine Error: {str(e)}"}
