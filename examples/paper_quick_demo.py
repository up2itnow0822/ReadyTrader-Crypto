"""
ReadyTrader-Crypto Phase 6 — Paper-mode quick demo (offline).

Goal: give a new user a 1-command way to validate that the paper trading engine works:
- deposits
- limit orders
- fills
- portfolio valuation + basic risk metrics

This script does NOT run the MCP server; it exercises the underlying engine directly so it
works without any MCP client configuration.
"""

import json
import tempfile
from pathlib import Path


def main() -> int:
    # Allow running from repo root without installing as a package.
    # (If executed from a different CWD, we add the repo root to sys.path.)
    import sys

    user_id = "demo_user"

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from paper_engine import PaperTradingEngine

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "paper_demo.db")
        engine = PaperTradingEngine(db_path=db_path)

        print("\n=== ReadyTrader-Crypto paper-mode quick demo ===")

        # ETH/USDT trades against USDT, so we deposit the quote currency (USDT),
        # not USDC — depositing the wrong stablecoin left every step below
        # "insufficient funds" even though the script still exited 0.
        print("\n1) Deposit paper funds")
        print(engine.deposit(user_id, "USDT", 10_000.0))

        print("\n2) Place a limit BUY for ETH/USDT")
        print(engine.place_limit_order(user_id, "buy", "ETH/USDT", amount=1.0, price=2000.0))

        print("\n3) Simulate market moving down and fill open orders")
        fill_msgs = engine.check_open_orders("ETH/USDT", current_price=1950.0)
        print("\n".join(fill_msgs) if fill_msgs else "(no fills)")

        print("\n4) Check balances + portfolio value")
        balances_after_buy = {
            "USDT": engine.get_balance(user_id, "USDT"),
            "ETH": engine.get_balance(user_id, "ETH"),
        }
        print(json.dumps(balances_after_buy, indent=2))
        print(f"Portfolio value (USD): {engine.get_portfolio_value_usd(user_id):.2f}")

        # Verify the fill actually happened by reading balances back, rather than
        # trusting fill_msgs' wording — a message string can look reassuring while
        # the underlying balance never moved.
        if balances_after_buy["ETH"] != 1.0:
            print(f"DEMO FAILED: expected ETH balance == 1.0 after the buy fill, got {balances_after_buy['ETH']!r}")
            return 1

        print("\n5) Execute a market SELL (paper) and re-check portfolio value")
        print(engine.execute_trade(user_id, "sell", "ETH/USDT", amount=1.0, price=2200.0, rationale="Demo exit"))
        print(f"Portfolio value (USD): {engine.get_portfolio_value_usd(user_id):.2f}")

        balances_after_sell = {
            "USDT": engine.get_balance(user_id, "USDT"),
            "ETH": engine.get_balance(user_id, "ETH"),
        }

        if balances_after_sell["ETH"] != 0.0:
            print(f"DEMO FAILED: expected ETH balance == 0 after the sell, got {balances_after_sell['ETH']!r}")
            return 1
        if not (balances_after_sell["USDT"] > balances_after_buy["USDT"]):
            print(
                "DEMO FAILED: expected USDT balance after the sell "
                f"({balances_after_sell['USDT']!r}) to be greater than after the buy "
                f"({balances_after_buy['USDT']!r})"
            )
            return 1

        try:
            metrics = engine.get_risk_metrics(user_id)
        except Exception:
            metrics = {}
        print("\n6) Risk metrics snapshot")
        print(json.dumps(metrics, indent=2))

    print("\nAll balance checks passed.")
    print("\nDone. Next: run `python examples/stress_test_demo.py` for the synthetic stress lab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
