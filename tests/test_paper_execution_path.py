"""Regression tests for the paper execution path and enum-typed settings.

These deliberately use a REAL PaperTradingEngine (temp SQLite) instead of a Mock so
signature mismatches between the MCP tools and the engine are caught. The existing
tests mocked the engine, which hid a TypeError on the paper `place_cex_order` path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.container import global_container
from app.core.settings import ApprovalMode, ExecutionMode, RiskProfile, settings
from app.tools.execution import _maybe_propose, _require_live_allowed, place_cex_order, swap_tokens
from execution.router import venue_allowed
from paper_engine import PaperTradingEngine

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def real_paper_engine(tmp_path):
    engine = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    with patch.object(global_container, "paper_engine", engine):
        yield engine


def test_place_cex_order_paper_path_uses_real_engine(real_paper_engine):
    real_paper_engine.deposit("agent_zero", "USDT", 10_000.0)
    with patch.object(settings, "PAPER_MODE", True), patch.object(settings, "EXECUTION_MODE", ExecutionMode.CEX):
        res = json.loads(place_cex_order("BTC/USDT", "buy", 0.01, order_type="market", price=50_000.0))
    assert res["ok"] is True, res
    assert res["data"]["mode"] == "paper"
    assert real_paper_engine.get_balance("agent_zero", "BTC") == pytest.approx(0.01)
    assert real_paper_engine.get_balance("agent_zero", "USDT") == pytest.approx(10_000.0 - 500.0)


def test_swap_tokens_paper_path_uses_real_engine(real_paper_engine):
    real_paper_engine.deposit("agent_zero", "ETH", 2.0)
    with patch.object(settings, "PAPER_MODE", True):
        res = json.loads(swap_tokens("ETH", "USDC", 1.0))
    assert res["ok"] is True, res
    assert res["data"]["mode"] == "paper"
    assert real_paper_engine.get_balance("agent_zero", "ETH") == pytest.approx(1.0)


def test_enum_settings_compare_equal_to_their_string_values():
    assert ExecutionMode.CEX == "cex"
    assert ApprovalMode.APPROVE_EACH == "approve_each"
    assert RiskProfile.CONSERVATIVE == "conservative"
    assert venue_allowed(ExecutionMode.CEX, "cex") is True
    assert venue_allowed(ExecutionMode.DEX, "cex") is False


def test_maybe_propose_returns_proposal_in_live_approve_each_mode():
    proposal = SimpleNamespace(request_id="req-1", confirm_token="tok-1", expires_at=1.0, kind="place_cex_order")
    with (
        patch.object(settings, "PAPER_MODE", False),
        patch.object(settings, "EXECUTION_APPROVAL_MODE", ApprovalMode.APPROVE_EACH),
        patch.object(global_container.execution_store, "create", return_value=proposal) as create,
    ):
        out = _maybe_propose("place_cex_order", {"symbol": "BTC/USDT"})
    create.assert_called_once()
    assert out is not None
    data = json.loads(out)["data"]
    assert data["approval_required"] is True
    assert data["request_id"] == "req-1"


def test_maybe_propose_is_none_in_paper_mode_and_auto_mode():
    with patch.object(settings, "PAPER_MODE", True), patch.object(settings, "EXECUTION_APPROVAL_MODE", ApprovalMode.APPROVE_EACH):
        assert _maybe_propose("place_cex_order", {}) is None
    with patch.object(settings, "PAPER_MODE", False), patch.object(settings, "EXECUTION_APPROVAL_MODE", ApprovalMode.AUTO):
        assert _maybe_propose("place_cex_order", {}) is None


def test_require_live_allowed_kill_switch_and_venue_routing():
    live = {"PAPER_MODE": False, "LIVE_TRADING_ENABLED": True, "EXECUTION_MODE": ExecutionMode.CEX}
    with patch.multiple(settings, **live, TRADING_HALTED=True):
        with pytest.raises(ValueError, match="TRADING_HALTED"):
            _require_live_allowed(venue="cex")
    with patch.multiple(settings, **live, TRADING_HALTED=False):
        _require_live_allowed(venue="cex")  # enum-typed EXECUTION_MODE must route without raising
        with pytest.raises(ValueError, match="EXECUTION_MODE=cex"):
            _require_live_allowed(venue="dex")
    with patch.multiple(settings, PAPER_MODE=False, LIVE_TRADING_ENABLED=False, TRADING_HALTED=False, EXECUTION_MODE=ExecutionMode.CEX):
        with pytest.raises(ValueError, match="LIVE_TRADING_ENABLED"):
            _require_live_allowed(venue="cex")


def test_app_main_runs_as_a_script_from_repo_root(tmp_path):
    """`python app/main.py` is the documented entrypoint (README, Dockerfile, smithery.yaml)."""
    env = {
        **os.environ,
        "PAPER_MODE": "true",
        "DEV_MODE": "false",
        "SIGNER_TYPE": "null",
        "PAPER_DB_PATH": str(tmp_path / "paper.db"),
        "AUDIT_DB_PATH": str(tmp_path / "audit.db"),
        "IDEMPOTENCY_DB_PATH": str(tmp_path / "idempotency.db"),
        "EXECUTION_DB_PATH": str(tmp_path / "execution.db"),
        "INSIGHT_DB_PATH": str(tmp_path / "insights.db"),
        "STRATEGY_DB_PATH": str(tmp_path / "strategies.db"),
    }
    proc = subprocess.run(
        [sys.executable, "app/main.py"],
        cwd=REPO_ROOT,
        env=env,
        input=b"",  # closed stdin -> stdio MCP server exits cleanly
        capture_output=True,
        timeout=60,
    )
    assert b"ModuleNotFoundError" not in proc.stderr, proc.stderr.decode(errors="replace")
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
