#!/usr/bin/env python3
"""Paper BTC/USDT UAT harness — ≥20 trades, risk block, no live orders."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from paper_engine import PaperTradingEngine
    from risk_manager import RiskGuardian

    user_id = "btc_uat"
    trades = 0
    blocks = 0

    with tempfile.TemporaryDirectory() as td:
        engine = PaperTradingEngine(db_path=str(Path(td) / "paper_btc_uat.db"))
        print("=== Paper BTC/USDT UAT ===")

        print(engine.deposit(user_id, "USDT", 100_000.0))

        price = 60_000.0
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            amount = 0.01
            trade_price = price if side == "buy" else price + 50.0
            msg = engine.execute_trade(
                user_id, side, "BTC/USDT", amount=amount, price=trade_price, rationale=f"uat-{i}"
            )
            print(f"{i+1:02d} {side}: {msg}")
            if "Insufficient" not in msg and "Error" not in msg.lower():
                trades += 1
            price += 25.0 if side == "buy" else -10.0

        guardian = RiskGuardian()
        equity = engine.get_portfolio_value_usd(user_id) or 100_000.0
        verdict = guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=50_000.0,
            portfolio_value=equity,
        )
        print(f"risk_block_expected: {verdict}")
        if not verdict.get("allowed", True):
            blocks += 1

        # Halt semantics: live execution allowed only when paper off + live on + not halted
        from app.core import settings as settings_mod

        live_allowed_default = settings_mod.settings.is_live_execution_allowed
        # Defaults: PAPER=true LIVE=false HALTED=true → live must be False
        halt_ok = live_allowed_default is False

        balances = {
            "USDT": engine.get_balance(user_id, "USDT"),
            "BTC": engine.get_balance(user_id, "BTC"),
        }
        result = {
            "trades_ok": trades,
            "risk_blocks": blocks,
            "live_execution_allowed_default": live_allowed_default,
            "halt_gate_ok": halt_ok,
            "balances": balances,
            "equity_usd": equity,
            "pass": trades >= 20 and blocks >= 1 and halt_ok,
        }
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
