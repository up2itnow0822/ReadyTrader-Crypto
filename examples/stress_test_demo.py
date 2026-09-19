"""
ReadyTrader-Crypto Phase 6 — Synthetic Stress Lab demo (offline, deterministic).

This script runs a randomized synthetic market stress test, then writes exportable artifacts:
- JSON summary report
- CSV scenario metrics
- CSV equity curve for worst-drawdown scenario
- JSON trade log for worst-drawdown scenario

Artifacts are written under ./artifacts/demo_stress/ (gitignored).
"""

import json
from pathlib import Path

_DEMO_STRATEGY_CODE = """
PARAMS = {
  "rsi_buy": 30,
  "rsi_sell": 70,
  "max_alloc_pct": 0.05,
}

def on_candle(close, rsi, state):
    # Minimal RSI strategy for demo purposes.
    # The stress lab is about failure modes, not alpha.
    if rsi < PARAMS["rsi_buy"]:
        return "buy"
    if rsi > PARAMS["rsi_sell"]:
        return "sell"
    return "hold"
""".strip()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    # Allow running from repo root without installing as a package.
    # (If executed from a different CWD, we add the repo root to sys.path.)
    import sys

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from recommendations import recommend_settings
    from stress_test_engine import run_synthetic_stress_test

    out_dir = Path("artifacts") / "demo_stress"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = {
        # Keep small so this runs fast for first-time users.
        "master_seed": 1337,
        "scenarios": 60,
        "length": 500,
        "timeframe": "1h",
        "initial_capital": 10_000.0,
        "start_price": 100.0,
        "base_vol": 0.015,
        "black_swan_prob": 0.03,
        "parabolic_prob": 0.03,
    }

    print("\n=== ReadyTrader-Crypto Synthetic Stress Lab demo ===")
    print("Running stress test… (offline)")
    res = run_synthetic_stress_test(strategy_code=_DEMO_STRATEGY_CODE, config=config)

    summary = res.get("summary", {}) or {}
    artifacts = res.get("artifacts", {}) or {}

    recs = recommend_settings(summary)

    _write_text(out_dir / "summary.json", json.dumps(summary, indent=2))
    _write_text(out_dir / "scenario_metrics.csv", str(artifacts.get("scenario_metrics_csv") or ""))
    _write_text(out_dir / "recommendations.json", json.dumps(recs, indent=2))

    if artifacts.get("worst_drawdown_equity_csv"):
        _write_text(out_dir / "worst_drawdown_equity.csv", str(artifacts["worst_drawdown_equity_csv"]))
    if artifacts.get("worst_drawdown_trades_json"):
        _write_text(out_dir / "worst_drawdown_trades.json", str(artifacts["worst_drawdown_trades_json"]))

    print("\nWrote artifacts:")
    for p in sorted(out_dir.glob("*")):
        print(f"- {p}")

    wd_seed = artifacts.get("worst_drawdown_seed")
    if wd_seed is not None:
        print(f"\nWorst-drawdown replay seed: {wd_seed}")
        print("You can re-run with master_seed=that seed and scenarios=1 to replay deterministically.")

    print(
        "\nDone. `run_synthetic_stress_test` is a Python function (stress_test_engine.run_synthetic_stress_test),"
        " not an MCP tool -- run this script again with a different strategy, or ask your agent to call the"
        " `run_backtest_simulation` MCP tool for a single-path backtest of the same contract."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
