import os
import sys

import pytest

# Add root directory to sys.path to allow imports from top-level modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set environment variables BEFORE modules are imported
os.environ["PRIVATE_KEY"] = "0000000000000000000000000000000000000000000000000000000000000001"
os.environ["SIGNER_TYPE"] = "env_private_key"
os.environ["PAPER_MODE"] = "true"
os.environ["EXECUTION_MODE"] = "dex"


@pytest.fixture(autouse=True)
def mock_env_setup():
    # Ensures these are set for every test
    pass


# Paper orders fill at the market price and the Risk Guardian values orders at it. Unit tests never
# reach an exchange for one: the shared market-data bus serves these. A test that needs other prices
# patches global_container.marketdata_bus itself.
FIXED_TEST_PRICES = {
    "BTC/USDT": 50_000.0,
    "ETH/USDT": 2_500.0,
    "ETH/USDC": 2_500.0,
    "SOL/USDT": 150.0,
    "USDC/USDT": 1.0,
}


@pytest.fixture(autouse=True)
def offline_market_prices():
    import app.core.container
    import app.tools.trading
    from marketdata.bus import MarketDataResult

    def fetch_ticker(symbol):
        key = str(symbol or "").strip().upper()
        if key not in FIXED_TEST_PRICES:
            raise ValueError(f"no test price for {symbol!r}")
        return MarketDataResult(source="test_fixed", data={"symbol": key, "last": FIXED_TEST_PRICES[key]}, meta={})

    # Its own MonkeyPatch, so a test's monkeypatch.undo() does not put the network back. Some
    # integration fixtures reload app.core.container, so the container the tools hold and the module's
    # current one can differ: patch both.
    buses = {id(c.marketdata_bus): c.marketdata_bus for c in (app.core.container.global_container, app.tools.trading.global_container)}
    with pytest.MonkeyPatch.context() as mp:
        for bus in buses.values():
            mp.setattr(bus, "fetch_ticker", fetch_ticker)
        yield FIXED_TEST_PRICES


@pytest.fixture
def container():
    from app.core.container import global_container

    return global_container


@pytest.fixture
def backtest_engine(container):
    return container.backtest_engine


@pytest.fixture
def paper_engine(container):
    return container.paper_engine


@pytest.fixture
def policy_engine(container):
    return container.policy_engine


@pytest.fixture
def risk_guardian(container):
    return container.risk_guardian


@pytest.fixture
def marketdata_bus(container):
    return container.marketdata_bus
