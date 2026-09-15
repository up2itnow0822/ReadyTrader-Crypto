import json
from unittest.mock import MagicMock, patch

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
    # Mock DexHandler and Signer in global_container
    with patch.object(global_container, "dex_handler") as mock_dex:
        with patch.object(global_container, "signer") as mock_signer:
            with (
                patch.object(global_container, "policy_engine"),
                patch.multiple(
                    settings,
                    PAPER_MODE=False,
                    LIVE_TRADING_ENABLED=True,
                    TRADING_HALTED=False,
                    EXECUTION_MODE=ExecutionMode.DEX,
                ),
            ):
                mock_dex.resolve_token.side_effect = ["0xFROM", "0xTO"]
                mock_dex.build_swap_tx.return_value = {
                    "tx": {
                        "to": "0x0000000000000000000000000000000000000002",
                        "data": "0x",
                        "value": "0x0",
                        "gas": "0x5208",
                        "gasPrice": "0x3b9aca00",
                    }
                }

                signed_mock = MagicMock()
                signed_mock.rawTransaction = b"\x01\x02"
                mock_signer.sign_transaction.return_value = signed_mock
                mock_signer.get_address.return_value = "0x0000000000000000000000000000000000000001"

                # Avoid network: mock nonce fetch + broadcast + decimals lookup
                with patch("app.tools.execution.get_web3") as mock_get_web3:
                    mock_w3 = MagicMock()
                    mock_w3.eth.get_transaction_count.return_value = 123
                    mock_get_web3.return_value = mock_w3
                    with patch("app.tools.execution.send_raw_transaction", return_value="0xHASH"):
                        with patch("app.tools.execution.erc20_decimals", return_value=6):
                            # Run
                            res_str = swap_tokens(from_token="USDC", to_token="WETH", amount=1.0, chain="ethereum")
                            res = json.loads(res_str)

                # Verify
                assert res["ok"] is True
                assert res["data"]["mode"] == "live"
                assert res["data"]["venue"] == "dex"
                assert res["data"]["tx_hash"] == "0xHASH"


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
                mock_engine.execute_trade.return_value = "Paper Trade Executed"

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
