from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd
import ta

from strategy_sandbox import run_strategy
from synthetic_market import generate_synthetic_ohlcv


def _series_points(df: pd.DataFrame) -> List[Tuple[float, float | None]]:
    """(close, rsi) per candle as plain floats; rsi is None during indicator warm-up."""
    closes = [float(v) for v in df["close"].tolist()]
    rsis = [None if pd.isna(v) else float(v) for v in df["rsi"].tolist()]
    return list(zip(closes, rsis))


def _compute_equity_curve(
    df: pd.DataFrame,
    actions: List[str | None],
    *,
    initial_capital: float = 10_000.0,
) -> Tuple[List[float], List[Dict[str, Any]]]:
    """
    Simple 1-position backtest (all-in / all-out) like BacktestEngine, but on supplied df.
    `actions` comes from strategy_sandbox.run_strategy and is aligned 1:1 with df rows
    (None during indicator warm-up). Returns (equity_curve, trades).
    """
    capital = float(initial_capital)
    position = 0.0
    trades: List[Dict[str, Any]] = []
    equity_curve: List[float] = []

    closes = [float(v) for v in df["close"].tolist()]
    timestamps = df["timestamp"].tolist()

    for pos, action in enumerate(actions):
        price = closes[pos]
        if action == "buy" and capital > 0:
            position = capital / price
            capital = 0.0
            trades.append({"type": "buy", "price": price, "idx": int(pos), "ts": str(timestamps[pos])})
        elif action == "sell" and position > 0:
            capital = position * price
            position = 0.0
            trades.append({"type": "sell", "price": price, "idx": int(pos), "ts": str(timestamps[pos])})

        equity = capital if capital > 0 else position * price
        equity_curve.append(float(equity))

    return equity_curve, trades


def _max_drawdown(equity: List[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return float(mdd)


def _final_return(equity: List[float], initial: float) -> float:
    if not equity or initial <= 0:
        return 0.0
    return float((equity[-1] - initial) / initial)


@dataclass
class ScenarioResult:
    seed: int
    final_return: float
    max_drawdown: float
    trades: int
    meta: Dict[str, Any]


def run_synthetic_stress_test(
    *,
    strategy_code: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Runs many synthetic scenarios and aggregates stress metrics.

    The returned dict is designed for MCP JSON output:
    - `summary`: aggregate metrics + worst-case scenarios (seed + events)
    - `artifacts`: CSV/JSON blobs for replay/debugging (deterministic by seed)
    """
    master_seed = int(config.get("master_seed", 1))
    scenarios = int(config.get("scenarios", 200))
    length = int(config.get("length", 500))
    timeframe = str(config.get("timeframe", "1h"))
    initial_capital = float(config.get("initial_capital", 10_000.0))
    start_price = float(config.get("start_price", 100.0))
    base_vol = float(config.get("base_vol", 0.01))
    black_swan_prob = float(config.get("black_swan_prob", 0.02))
    parabolic_prob = float(config.get("parabolic_prob", 0.02))

    # Deterministic per-scenario seeds
    seeds = [master_seed + i for i in range(scenarios)]

    results: List[ScenarioResult] = []
    worst_by_dd: List[ScenarioResult] = []
    generated: List[Tuple[int, pd.DataFrame, Dict[str, Any]]] = []

    for s in seeds:
        gen = generate_synthetic_ohlcv(
            seed=s,
            length=length,
            timeframe=timeframe,
            start_price=start_price,
            base_vol=base_vol,
            black_swan_prob=black_swan_prob,
            parabolic_prob=parabolic_prob,
        )
        df = gen["df"]
        # Indicators aligned with BacktestEngine
        df = df.copy()
        df["rsi"] = ta.momentum.rsi(df["close"], window=14)
        df["sma_20"] = ta.trend.sma_indicator(df["close"], window=20)
        df["sma_50"] = ta.trend.sma_indicator(df["close"], window=50)

        generated.append((s, df, gen["meta"]))

    # One isolated child process runs the strategy over every scenario (state resets per scenario).
    # Raises strategy_sandbox.StrategyError if the code is rejected, fails, or exceeds its limits.
    outcome = run_strategy(strategy_code, [_series_points(df) for _, df, _ in generated])
    strategy_params = outcome.params
    actions_by_seed: Dict[int, List[str | None]] = {}

    for (s, df, meta), actions in zip(generated, outcome.actions):
        actions_by_seed[s] = actions
        equity, trades = _compute_equity_curve(df, actions, initial_capital=initial_capital)
        fr = _final_return(equity, initial_capital)
        dd = _max_drawdown(equity)
        results.append(ScenarioResult(seed=s, final_return=fr, max_drawdown=dd, trades=len(trades), meta=meta))

    # aggregate metrics
    returns = [r.final_return for r in results]
    drawdowns = [r.max_drawdown for r in results]
    trades = [r.trades for r in results]

    def pct(vals: List[float], p: float) -> float:
        if not vals:
            return 0.0
        vs = sorted(vals)
        k = int((len(vs) - 1) * p)
        return float(vs[k])

    worst_by_dd = sorted(results, key=lambda r: r.max_drawdown, reverse=True)[:5]
    worst_by_ret = sorted(results, key=lambda r: r.final_return)[:5]

    summary = {
        "scenarios": scenarios,
        "length": length,
        "timeframe": timeframe,
        "initial_capital": initial_capital,
        "master_seed": master_seed,
        "seeds": seeds,
        "metrics": {
            "return_mean": float(statistics.mean(returns)) if returns else 0.0,
            "return_median": float(statistics.median(returns)) if returns else 0.0,
            "return_p05": pct(returns, 0.05),
            "return_p95": pct(returns, 0.95),
            "max_drawdown_mean": float(statistics.mean(drawdowns)) if drawdowns else 0.0,
            "max_drawdown_p95": pct(drawdowns, 0.95),
            "max_drawdown_max": max(drawdowns) if drawdowns else 0.0,
            "trades_mean": float(statistics.mean(trades)) if trades else 0.0,
            "trades_p95": pct(trades, 0.95),
        },
        "worst_drawdown_scenarios": [
            {
                "seed": r.seed,
                "max_drawdown": r.max_drawdown,
                "final_return": r.final_return,
                "events": r.meta.get("events", []),
            }
            for r in worst_by_dd
        ],
        "worst_return_scenarios": [
            {
                "seed": r.seed,
                "max_drawdown": r.max_drawdown,
                "final_return": r.final_return,
                "events": r.meta.get("events", []),
            }
            for r in worst_by_ret
        ],
        "strategy_params_detected": strategy_params,
    }

    # Minimal artifacts: per-scenario summary CSV and worst-case equity curve/trades for replay
    per_scenario_rows = [{"seed": r.seed, "final_return": r.final_return, "max_drawdown": r.max_drawdown, "trades": r.trades} for r in results]
    scenario_df = pd.DataFrame(per_scenario_rows)
    artifacts = {
        "scenario_metrics_csv": scenario_df.to_csv(index=False),
    }

    # Include worst-drawdown scenario detailed replay artifacts
    if worst_by_dd:
        replay_seed = worst_by_dd[0].seed
        gen = generate_synthetic_ohlcv(
            seed=replay_seed,
            length=length,
            timeframe=timeframe,
            start_price=start_price,
            base_vol=base_vol,
            black_swan_prob=black_swan_prob,
            parabolic_prob=parabolic_prob,
        )
        df = gen["df"].copy()
        df["rsi"] = ta.momentum.rsi(df["close"], window=14)
        df["sma_20"] = ta.trend.sma_indicator(df["close"], window=20)
        df["sma_50"] = ta.trend.sma_indicator(df["close"], window=50)
        # Scenarios are deterministic by seed, so the actions from the batch run above apply unchanged.
        equity, trades_log = _compute_equity_curve(df, actions_by_seed[replay_seed], initial_capital=initial_capital)
        eq_df = pd.DataFrame(
            {
                "timestamp": df["timestamp"],
                "equity": equity,
                "close": df["close"],
                "regime": df.get("regime"),
            }
        )
        artifacts["worst_drawdown_seed"] = replay_seed
        artifacts["worst_drawdown_equity_csv"] = eq_df.to_csv(index=False)
        artifacts["worst_drawdown_trades_json"] = json.dumps(trades_log, indent=2)

    return {"summary": summary, "artifacts": artifacts}
