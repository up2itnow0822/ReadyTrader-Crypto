import json
from unittest.mock import patch

# If FastMCP wraps them, we might need to access `.fn` or just call them if they act as proxies.
# Assuming standard python decorators, they are callable.
from app.core.config import settings
from app.core.container import global_container
from app.core.settings import ExecutionMode

# Import the specific functions from the new modules
from app.tools.execution import place_cex_order, start_cex_private_ws, swap_tokens


def test_fetch_price():
    # This was tested in test_market_tools? We can skip or reimplement.
    pass


def test_swap_tokens_real():
    """Opaque aggregator transactions cannot reach signing, even on an allowed router."""
    with (
        patch.object(global_container, "signer") as signer,
        patch.object(global_container.dex_handler, "build_swap_tx") as builder,
        patch.multiple(settings, PAPER_MODE=False, LIVE_TRADING_ENABLED=True, TRADING_HALTED=False, EXECUTION_MODE=ExecutionMode.DEX),
    ):
        res = json.loads(swap_tokens("USDC", "WETH", 1.0, chain="ethereum"))
    assert res["ok"] is False
    assert res["error"]["code"] == "unsupported_swap_semantics"
    signer.sign_transaction.assert_not_called()
    builder.assert_not_called()


def test_place_cex_order_blocked_when_mode_dex():
    with patch.dict("os.environ", {"EXECUTION_MODE": "dex"}):
        # Reload settings? settings loading is cached. We must patch the settings object.
        with patch.object(settings, "EXECUTION_MODE", "dex"):
            res_str = place_cex_order("BTC/USDT", "buy", 0.01, exchange="binance")
            res = json.loads(res_str)
            assert res["ok"] is False
            assert res["error"]["code"] == "execution_mode_blocked"


def test_place_cex_order_paper_mode():
    with patch.object(settings, "PAPER_MODE", True):
        with patch.object(settings, "EXECUTION_MODE", "auto"):
            with patch.object(global_container, "paper_engine") as mock_engine:
                # The Risk Guardian reads the account first: a 100,000 USDT account with no history.
                mock_engine.get_risk_metrics.return_value = {"daily_pnl_pct": 0.0, "drawdown_pct": 0.0}
                mock_engine.get_portfolio_value_usd.return_value = 100_000.0
                mock_engine.get_balances.return_value = {"USDT": 100_000.0}
                mock_engine.get_balance.return_value = 0.0
                # The tool reads the engine's structured result (execute_trade_result), not the prose string.
                mock_engine.execute_trade_result.return_value = {
                    "ok": True,
                    "message": "Paper Trade Executed",
                    "fill": {"side": "buy", "symbol": "BTC/USDT", "amount": 0.01, "price": 50_000.0, "total_value": 500.0, "quote": "USDT"},
                }

                # Explicit price: paper price resolution has its own tests and
                # must not make this routing test depend on the market-data bus.
                res_str = place_cex_order("BTC/USDT", "buy", 0.01, price=50_000.0)
                res = json.loads(res_str)

                assert res["ok"] is True
                assert res["data"]["mode"] == "paper"
                assert "Paper Trade Executed" in res["data"]["result"]


def test_private_ws_paper_mode_blocked():
    with patch.object(settings, "PAPER_MODE", True):
        res_str = start_cex_private_ws("binance", "spot")
        res = json.loads(res_str)
        assert res["ok"] is False
        assert res["error"]["code"] == "paper_mode_not_supported"


def test_private_ws_kraken():
    """Test Kraken WebSocket stream start - now supports native WS."""
    with patch.multiple(
        settings,
        PAPER_MODE=False,
        LIVE_TRADING_ENABLED=True,
        TRADING_HALTED=False,
        EXECUTION_MODE=ExecutionMode.CEX,
    ):
        res_str = start_cex_private_ws("kraken", "spot")
        res = json.loads(res_str)
        assert res["ok"] is True
        # Kraken now has native WS support
        assert res["data"]["mode"] == "ws"
