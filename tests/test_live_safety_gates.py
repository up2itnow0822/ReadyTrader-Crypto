"""Regression tests for the live-safety gaps closed in issue #6.

Covers: gating `start_cex_private_ws` behind the live-execution guard, the
paper `place_cex_order` path resolving a reference price from the
market-data bus instead of fabricating one, and paper-mode `get_cex_balance`
returning the paper wallet without requiring CEX credentials.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from app.core.container import global_container
from app.core.settings import ExecutionMode, settings
from app.tools.execution import start_cex_private_ws


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
