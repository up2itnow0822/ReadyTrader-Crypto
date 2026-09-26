"""Regression tests for the live-safety gaps closed in issue #6.

Covers: gating `start_cex_private_ws` behind the live-execution guard, the
paper `place_cex_order` path resolving a reference price from the
market-data bus instead of fabricating one, and paper-mode `get_cex_balance`
returning the paper wallet without requiring CEX credentials.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.container import global_container
from app.core.settings import ExecutionMode, settings
from app.tools.execution import (
    _paper_reference_price,
    get_cex_balance,
    place_cex_order,
    start_cex_private_ws,
)
from paper_engine import PaperTradingEngine


@pytest.fixture
def real_paper_engine(tmp_path):
    engine = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    with patch.object(global_container, "paper_engine", engine):
        yield engine


def test_start_cex_private_ws_blocked_when_halted():
    with (
        patch.multiple(
            settings,
            PAPER_MODE=False,
            LIVE_TRADING_ENABLED=True,
            TRADING_HALTED=True,
            EXECUTION_MODE=ExecutionMode.CEX,
        ),
        patch.object(global_container.binance_user_streams, "start") as start,
    ):
        res = json.loads(start_cex_private_ws(exchange="binance"))
    assert res["ok"] is False
    start.assert_not_called()


def test_start_cex_private_ws_blocked_without_consent():
    with (
        patch.multiple(settings, PAPER_MODE=False, LIVE_TRADING_ENABLED=False, TRADING_HALTED=False),
        patch.object(global_container.binance_user_streams, "start") as start,
    ):
        res = json.loads(start_cex_private_ws(exchange="binance"))
    assert res["ok"] is False
    start.assert_not_called()


def test_start_cex_private_ws_allowed_when_live_and_not_halted():
    with (
        patch.multiple(
            settings,
            PAPER_MODE=False,
            LIVE_TRADING_ENABLED=True,
            TRADING_HALTED=False,
            EXECUTION_MODE=ExecutionMode.CEX,
        ),
        patch.object(global_container.policy_engine, "validate_cex_access"),
        patch.object(global_container.binance_user_streams, "start") as start,
    ):
        res = json.loads(start_cex_private_ws(exchange="binance"))
    assert res["ok"] is True, res
    start.assert_called_once()


def test_paper_order_without_price_uses_bus_price(real_paper_engine):
    real_paper_engine.deposit("agent_zero", "USDT", 10_000.0)
    with (
        patch.multiple(settings, PAPER_MODE=True, EXECUTION_MODE=ExecutionMode.CEX),
        patch("app.tools.execution._paper_reference_price", return_value=60_000.0),
    ):
        res = json.loads(place_cex_order("BTC/USDT", "buy", 0.005, order_type="market"))
    assert res["ok"] is True, res
    assert res["data"]["mode"] == "paper"
    assert real_paper_engine.get_balance("agent_zero", "BTC") == pytest.approx(0.005)
    assert real_paper_engine.get_balance("agent_zero", "USDT") == pytest.approx(10_000.0 - 300.0)


def test_paper_order_without_price_and_without_bus_price_fails(real_paper_engine):
    real_paper_engine.deposit("agent_zero", "USDT", 10_000.0)
    with (
        patch.multiple(settings, PAPER_MODE=True, EXECUTION_MODE=ExecutionMode.CEX),
        patch("app.tools.execution._paper_reference_price", return_value=None),
    ):
        res = json.loads(place_cex_order("BTC/USDT", "buy", 0.01, order_type="market"))
    assert res["ok"] is False
    assert res["error"]["code"] == "paper_price_required"
    assert real_paper_engine.get_balances("agent_zero") == {"USDT": 10_000.0}


def test_get_cex_balance_paper_mode(real_paper_engine):
    real_paper_engine.deposit("agent_zero", "USDT", 10_000.0)
    with patch.object(settings, "PAPER_MODE", True):
        res = json.loads(get_cex_balance())
    assert res["ok"] is True, res
    assert res["data"]["mode"] == "paper"
    assert res["data"]["balance"] == {"USDT": 10_000.0}


def test_get_cex_balance_paper_mode_without_engine():
    with (
        patch.object(settings, "PAPER_MODE", True),
        patch.object(global_container, "paper_engine", None),
    ):
        res = json.loads(get_cex_balance())
    assert res["ok"] is False
    # Pin the paper branch itself: pre-fix code also returned ok=False here, but
    # via an unrelated "Missing CEX credentials" cex_error from a real executor.
    assert res["error"]["code"] == "paper_engine_missing"


def test_paper_reference_price_reads_bus_ticker():
    with patch.object(global_container, "marketdata_bus") as bus:
        bus.fetch_ticker.return_value = SimpleNamespace(data={"last": 60_000.0})
        assert _paper_reference_price("BTC/USDT") == pytest.approx(60_000.0)
        bus.fetch_ticker.assert_called_once_with("BTC/USDT")


def test_paper_reference_price_falls_back_to_close():
    with patch.object(global_container, "marketdata_bus") as bus:
        bus.fetch_ticker.return_value = SimpleNamespace(data={"close": 59_500.0})
        assert _paper_reference_price("BTC/USDT") == pytest.approx(59_500.0)


def test_paper_reference_price_returns_none_when_bus_unusable():
    with patch.object(global_container, "marketdata_bus") as bus:
        for data in (None, {}, {"last": 0.0}, {"last": -1.0}, {"last": "n/a"}):
            bus.fetch_ticker.return_value = SimpleNamespace(data=data)
            assert _paper_reference_price("BTC/USDT") is None, data
        bus.fetch_ticker.side_effect = RuntimeError("no providers")
        assert _paper_reference_price("BTC/USDT") is None
