"""Regression coverage for security findings 5, 10, and 12 (no external execution)."""

from __future__ import annotations

import copy
import math
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketdata.bus import MarketDataBus, MarketDataResult
from risk_manager import RiskGuardian

BOOL_FIELDS = (
    "PAPER_MODE",
    "LIVE_TRADING_ENABLED",
    "TRADING_HALTED",
    "DEV_MODE",
    "API_AUTH_REQUIRED",
    "RATE_LIMIT_ENABLED",
    "SIGNER_POLICY_ENABLED",
    "SIGNER_DISALLOW_CONTRACT_CREATION",
    "MARKETDATA_FAIL_CLOSED",
    "REMOTE_SIGNER_REQUIRE_TLS",
)


def _settings(monkeypatch, **overrides):
    import app.core.settings as config

    for name in BOOL_FIELDS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("SIGNER_TYPE", "null")
    monkeypatch.setenv("DEV_MODE", "true")
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    return config


@pytest.mark.parametrize("field", BOOL_FIELDS)
@pytest.mark.parametrize("value", ["treu", "", "2"])
def test_unrecognized_safety_boolean_refuses_settings(monkeypatch, field, value):
    config = _settings(monkeypatch, **{field: value})
    with pytest.raises(config.SettingsValidationError, match=field):
        config.Settings()


@pytest.mark.parametrize("field", ["EXECUTION_MODE", "EXECUTION_APPROVAL_MODE", "RISK_PROFILE", "SIGNER_TYPE"])
@pytest.mark.parametrize("value", ["typo", ""])
def test_unrecognized_safety_enum_refuses_settings(monkeypatch, field, value):
    config = _settings(monkeypatch, **{field: value})
    with pytest.raises(config.SettingsValidationError, match=field):
        config.Settings()


def test_settings_aggregate_invalid_fields(monkeypatch):
    config = _settings(monkeypatch, TRADING_HALTED="treu", EXECUTION_MODE="cexx", EXECUTION_APPROVAL_MODE="approve_ech")
    with pytest.raises(config.SettingsValidationError) as error:
        config.Settings()
    assert all(field in str(error.value) for field in ("TRADING_HALTED", "EXECUTION_MODE", "EXECUTION_APPROVAL_MODE"))


@pytest.mark.parametrize(
    "value, expected", [("true", True), ("1", True), ("yes", True), ("on", True), ("false", False), ("0", False), ("no", False), ("off", False)]
)
def test_documented_boolean_aliases_work(monkeypatch, value, expected):
    config = _settings(monkeypatch, TRADING_HALTED=value)
    assert config.Settings().TRADING_HALTED is expected


@pytest.mark.parametrize("field", ["PAPER_MODE", "TRADING_HALTED", "EXECUTION_MODE", "EXECUTION_APPROVAL_MODE"])
def test_direct_constructor_invalid_safety_values_are_refused(monkeypatch, field):
    config = _settings(monkeypatch)
    with pytest.raises(config.SettingsValidationError, match=field):
        config.Settings(**{field: "typo"})


def test_live_mode_cannot_disable_market_data_guard(monkeypatch):
    config = _settings(monkeypatch, PAPER_MODE="false", LIVE_TRADING_ENABLED="true", MARKETDATA_FAIL_CLOSED="false")
    with pytest.raises(config.SettingsValidationError, match="MARKETDATA_FAIL_CLOSED"):
        config.Settings()


def test_live_mode_defaults_to_fail_closed_market_data(monkeypatch):
    config = _settings(monkeypatch, PAPER_MODE="false", LIVE_TRADING_ENABLED="true")
    assert config.Settings().MARKETDATA_FAIL_CLOSED is True


def test_live_compose_requires_fresh_market_data_for_api_and_mcp():
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.live.yml").read_text())
    for name in ("api", "mcp"):
        assert "MARKETDATA_FAIL_CLOSED=true" in compose["services"][name]["environment"]


class Provider:
    provider_id = "test"

    def __init__(self, ticker):
        self.ticker = ticker

    def fetch_ticker(self, symbol):
        return dict(self.ticker)


def test_quote_generated_during_provider_request_is_not_future(monkeypatch):
    import marketdata.bus as module

    clock = [1_000_000]
    monkeypatch.setattr(module, "_now_ms", lambda: clock[0])
    monkeypatch.setenv("MARKETDATA_FAIL_CLOSED", "true")

    class DelayedProvider(Provider):
        def fetch_ticker(self, symbol):
            clock[0] += 100
            return {"last": 100.0, "timestamp_ms": clock[0] - 10}

    result = module.MarketDataBus([DelayedProvider({})]).fetch_ticker("BTC/USDT")
    assert result.meta["stale"] is False
    assert result.meta["age_ms"] == 10


@pytest.mark.parametrize("field", ["last", "bid", "ask"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0, True])
def test_market_data_never_returns_invalid_numeric_quotes(monkeypatch, field, value):
    ticker = {"last": 100.0, "bid": 99.0, "ask": 101.0, "timestamp_ms": int(time.time() * 1000), field: value}
    with pytest.raises(ValueError):
        MarketDataBus([Provider(ticker)]).fetch_ticker("BTC/USDT")


@pytest.fixture
def live_risk(monkeypatch):
    import app.tools.trading as trading

    mode = copy.copy(trading.settings)
    mode.PAPER_MODE = False
    mode.LIVE_TRADING_ENABLED = True
    monkeypatch.setattr(trading, "settings", mode)
    monkeypatch.setattr(trading, "CexExecutor", lambda **kwargs: SimpleNamespace(fetch_balance=lambda: {"total": {"USDT": 100_000.0, "BTC": 1.0}}))
    now = int(time.time() * 1000)
    result = MarketDataResult(
        "test",
        {"last": 50_000.0},
        {
            "timestamp_ms": now,
            "max_age_ms": 30_000,
            "age_ms": 0,
            "stale": False,
            "outlier": False,
        },
    )
    monkeypatch.setattr(trading.global_container.marketdata_bus, "fetch_ticker", lambda symbol: result)
    return trading, result


@pytest.mark.parametrize(
    "meta",
    [
        {},
        {"stale": True},
        {"outlier": True},
        {"timestamp_ms": None},
        {"timestamp_ms": 1},
        {"timestamp_ms": 9_999_999_999_999_999},
        {"max_age_ms": float("inf")},
    ],
)
def test_live_exposure_requires_acceptable_metadata(live_risk, meta):
    trading, ticker = live_risk
    if meta:
        ticker.meta.update(meta)
    else:
        ticker.meta.clear()
    result = trading.pre_trade_check("BTC/USDT", "buy", 0.001)
    assert result["allowed"] is False
    assert result["market_price"] is None


def test_fresh_valid_quote_allows_safe_live_exposure(live_risk):
    trading, _ = live_risk
    result = trading.pre_trade_check("BTC/USDT", "buy", 0.001)
    assert result["allowed"] is True
    assert result["exposure_added_usd"] == 50.0


def test_stale_quote_does_not_block_valid_cash_exit(live_risk):
    trading, ticker = live_risk
    ticker.meta["stale"] = True
    result = trading.pre_trade_check("BTC/USDT", "sell", 0.5)
    assert result["allowed"] is True
    assert result["exposure_added_units"] == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0, True, "NaN", None])
def test_bad_exchange_balance_blocks_before_guardian(live_risk, monkeypatch, value):
    trading, _ = live_risk
    monkeypatch.setattr(trading, "CexExecutor", lambda **kwargs: SimpleNamespace(fetch_balance=lambda: {"total": {"USDT": value, "BTC": 1.0}}))
    calls = []
    monkeypatch.setattr(trading.global_container, "risk_guardian", SimpleNamespace(validate_trade=lambda **kwargs: calls.append(kwargs) or {"allowed": True}))
    assert trading.pre_trade_check("BTC/USDT", "buy", 0.001)["allowed"] is False
    assert calls == []


def test_overflowed_account_valuation_blocks_before_guardian(live_risk, monkeypatch):
    trading, _ = live_risk
    monkeypatch.setattr(trading, "_live_totals", lambda *args: {"BTC": 1e308})
    calls = []
    monkeypatch.setattr(trading.global_container, "risk_guardian", SimpleNamespace(validate_trade=lambda **kwargs: calls.append(kwargs) or {"allowed": True}))
    assert trading.pre_trade_check("BTC/USDT", "buy", 0.001)["allowed"] is False
    assert calls == []


def test_overflowed_order_valuation_blocks_before_guardian(live_risk, monkeypatch):
    trading, _ = live_risk
    calls = []
    monkeypatch.setattr(trading.global_container, "risk_guardian", SimpleNamespace(validate_trade=lambda **kwargs: calls.append(kwargs) or {"allowed": True}))
    assert trading.pre_trade_check("BTC/USDT", "buy", 1e308)["allowed"] is False
    assert calls == []


@pytest.mark.parametrize("field", ["amount_usd", "portfolio_value", "sentiment_score", "daily_loss_pct", "current_drawdown_pct"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_guardian_refuses_nonfinite_and_boolean_inputs(field, value):
    inputs = dict(side="buy", symbol="BTC/USDT", amount_usd=10.0, portfolio_value=100_000.0)
    inputs[field] = value
    assert RiskGuardian().validate_trade(**inputs)["allowed"] is False


@pytest.mark.parametrize("field", ["amount_usd", "portfolio_value", "current_drawdown_pct"])
def test_guardian_refuses_negative_unsigned_inputs(field):
    inputs = dict(side="buy", symbol="BTC/USDT", amount_usd=10.0, portfolio_value=100_000.0)
    inputs[field] = -1.0
    assert RiskGuardian().validate_trade(**inputs)["allowed"] is False


def test_guardian_refuses_zero_equity_for_new_exposure():
    assert RiskGuardian().validate_trade("buy", "BTC/USDT", 1.0, 0.0)["allowed"] is False


@pytest.mark.parametrize("amount, rate", [(float("nan"), 1.0), (-1.0, 1.0), (True, 1.0), (1.0, float("inf")), (1.0, -1.0)])
def test_swap_rejects_invalid_numbers_even_for_exit(live_risk, monkeypatch, amount, rate):
    trading, _ = live_risk
    monkeypatch.setattr(trading, "_dex_wallet_value_usd", lambda chain: 100_000.0)
    result = trading.swap_check("ETH", "USDT", amount, rate)
    assert result["allowed"] is False
    assert not any(isinstance(v, float) and not math.isfinite(v) for v in result.values())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_invalid_account_state_blocks_apparent_exit(live_risk, monkeypatch, value):
    trading, _ = live_risk
    monkeypatch.setattr(trading, "_live_totals", lambda *args: {"USDT": value, "BTC": 1.0})
    assert trading.pre_trade_check("BTC/USDT", "sell", 0.5)["allowed"] is False


def test_sum_of_finite_account_values_must_not_overflow(live_risk, monkeypatch):
    trading, _ = live_risk
    monkeypatch.setattr(trading, "_live_totals", lambda *args: {"USDT": 1e308, "USDC": 1e308})
    assert trading.pre_trade_check("BTC/USDT", "buy", 0.001)["allowed"] is False


@pytest.mark.parametrize("bad_balance", [True, -1, float("inf"), float("nan")])
def test_dex_wallet_validates_raw_native_balance(live_risk, monkeypatch, bad_balance):
    trading, _ = live_risk
    monkeypatch.setattr(
        trading,
        "get_web3",
        lambda chain: SimpleNamespace(
            to_checksum_address=lambda value: value,
            eth=SimpleNamespace(get_balance=lambda owner: bad_balance),
        ),
    )
    monkeypatch.setattr(trading.global_container, "signer", SimpleNamespace(get_address=lambda: "wallet"))
    monkeypatch.setattr(trading.global_container, "dex_handler", SimpleNamespace(TOKEN_MAP={"ethereum": {"ETH": trading.NATIVE_COIN_ADDRESS}}))
    assert trading._dex_wallet_value_usd("ethereum") is None


@pytest.mark.parametrize("timestamp", [None, 1, 9_999_999_999_999_999])
def test_bus_itself_refuses_unsafe_live_timestamps(monkeypatch, timestamp):
    import app.core.config as config

    live = copy.copy(config.settings)
    live.PAPER_MODE = False
    live.LIVE_TRADING_ENABLED = True
    live.MARKETDATA_FAIL_CLOSED = False  # Defense in depth even with an invalid mutable settings object.
    monkeypatch.setattr(config, "settings", live)
    monkeypatch.setenv("MARKETDATA_FAIL_CLOSED", "false")
    with pytest.raises(ValueError, match="marketdata_not_acceptable"):
        MarketDataBus([Provider({"last": 100.0, "timestamp_ms": timestamp})]).fetch_ticker("BTC/USDT")


def test_bus_itself_refuses_live_outlier(monkeypatch):
    import app.core.config as config

    live = copy.copy(config.settings)
    live.PAPER_MODE = False
    monkeypatch.setattr(config, "settings", live)
    provider = Provider({"last": 100.0, "timestamp_ms": int(time.time() * 1000)})
    bus = MarketDataBus([provider])
    bus.fetch_ticker("BTC/USDT")
    provider.ticker["last"] = 200.0
    with pytest.raises(ValueError, match="marketdata_not_acceptable"):
        bus.fetch_ticker("BTC/USDT")


def test_best_effort_bus_does_not_refetch_unvalidated_candidate():
    class ChangingProvider(Provider):
        def fetch_ticker(self, symbol):
            result = super().fetch_ticker(symbol)
            self.ticker["last"] = float("nan")
            return result

    result = MarketDataBus([ChangingProvider({"last": 100.0, "timestamp_ms": 1})]).fetch_ticker("BTC/USDT")
    assert result.data["last"] == 100.0
    assert result.meta["stale"] is True


def test_malformed_balance_surfaces_risk_blocked_without_order_send(live_risk, monkeypatch):
    import json

    import app.tools.execution as execution
    from app.core.settings import ApprovalMode, ExecutionMode

    trading, _ = live_risk
    mode = trading.settings
    mode.TRADING_HALTED = False
    mode.EXECUTION_MODE = ExecutionMode.CEX
    mode.EXECUTION_APPROVAL_MODE = ApprovalMode.AUTO
    monkeypatch.setattr(execution, "settings", mode)
    calls = []
    executor = SimpleNamespace(fetch_balance=lambda: {"total": {"USDT": float("nan")}}, place_order=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(trading, "CexExecutor", lambda **kwargs: executor)
    monkeypatch.setattr(execution, "CexExecutor", lambda **kwargs: executor)
    result = json.loads(execution.place_cex_order("BTC/USDT", "buy", 0.001))
    assert result["ok"] is False
    assert result["error"]["code"] == "risk_blocked"
    assert calls == []


def test_live_services_have_aggregate_sandbox_limits():
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.live.yml").read_text())
    for name in ("api", "mcp"):
        service = compose["services"][name]
        assert service["mem_limit"] == service["memswap_limit"] == "2g"
        assert service["cpus"] == 2.0
        assert service["pids_limit"] == 128
        assert service["read_only"] is True
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["cap_drop"] == ["ALL"]
        assert "/tmp:rw,noexec,nosuid,size=128m" in service["tmpfs"]
        assert "readytrader-live-data:/app/data" in service["volumes"]


@pytest.mark.parametrize("quantity", [float("nan"), float("inf"), -1.0, True])
def test_paper_account_checks_all_balances_before_using_equity(monkeypatch, quantity):
    import app.tools.trading as trading

    engine = SimpleNamespace(get_balances=lambda user: {"USDT": quantity}, get_portfolio_value_usd=lambda user: 100_000.0)
    monkeypatch.setattr(trading.global_container, "paper_engine", engine)
    assert trading._paper_equity_usd() is None


@pytest.mark.parametrize("field", ["last", "bid", "ask"])
@pytest.mark.parametrize("value", [True, False])
def test_ccxt_provider_rejects_boolean_prices_before_normalization(monkeypatch, field, value):
    from marketdata.providers import CcxtMarketDataProvider

    monkeypatch.setenv("MARKETDATA_FAIL_CLOSED", "true")
    raw = {"last": 1.0, "bid": 1.0, "ask": 1.0, "timestamp": int(time.time() * 1000)}
    raw[field] = value
    exchange = SimpleNamespace(fetch_ticker=lambda symbol: raw, get_exchange_name=lambda: "stub")
    bus = MarketDataBus([CcxtMarketDataProvider(exchange)])
    with pytest.raises(ValueError):
        bus.fetch_ticker("BTC/USD").acceptable_price()
