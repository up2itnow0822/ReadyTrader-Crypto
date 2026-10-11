"""
Integration tests for full CEX execution flows.

These tests verify the complete flow from tool invocation through
policy validation, execution, and audit logging.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.container import global_container
from app.core.settings import ApprovalMode, ExecutionMode, settings
from app.tools.execution import place_cex_order


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary directories for test data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Set environment variables to use temp directories
    env_patches = {
        "PAPER_DB_PATH": str(data_dir / "paper.db"),
        "AUDIT_DB_PATH": str(data_dir / "audit.db"),
        "IDEMPOTENCY_DB_PATH": str(data_dir / "idempotency.db"),
        "EXECUTION_DB_PATH": str(data_dir / "execution.db"),
        "INSIGHT_DB_PATH": str(data_dir / "insights.db"),
        "STRATEGY_DB_PATH": str(data_dir / "strategies.db"),
        "PAPER_MODE": "true",
        "SIGNER_TYPE": "null",
        "EXECUTION_MODE": "auto",
    }

    with patch.dict(os.environ, env_patches):
        yield data_dir


@pytest.fixture
def fresh_container(temp_data_dir):
    """Create a fresh container instance for integration testing."""
    # Need to reimport to pick up new env vars
    import importlib

    import app.core.config
    import app.core.container

    # Reload modules to pick up env changes
    importlib.reload(app.core.config)
    importlib.reload(app.core.container)

    return app.core.container.global_container


class TestCexPaperModeFlow:
    """Test CEX execution in paper mode."""

    def test_full_paper_trading_cycle(self, fresh_container):
        """Test complete paper trading cycle: deposit -> trade -> check balance."""
        # Step 1: Deposit funds using container's paper engine
        result = fresh_container.paper_engine.deposit("agent_zero", "USDT", 10000.0)
        assert result is not None

        # Step 2: Validate trade risk
        risk_result = fresh_container.risk_guardian.validate_trade(side="buy", symbol="BTC/USDT", amount_usd=400.0, portfolio_value=10000.0)
        assert risk_result["allowed"] is True

        # Step 3: Execute trade via paper engine directly
        trade_result = fresh_container.paper_engine.execute_trade(
            user_id="agent_zero", side="buy", symbol="BTC/USDT", amount=0.01, price=100000.0, rationale="integration test"
        )
        assert trade_result is not None

    def test_paper_mode_risk_rejection(self, fresh_container):
        """Test that RiskGuardian blocks oversized trades."""
        # Deposit funds
        fresh_container.paper_engine.deposit("agent_zero", "USDT", 10000.0)

        # Try to validate an oversized trade (>5% of portfolio)
        risk_result = fresh_container.risk_guardian.validate_trade(side="buy", symbol="BTC/USDT", amount_usd=600.0, portfolio_value=10000.0)
        assert risk_result["allowed"] is False
        assert "Position size too large" in risk_result["reason"]

    def test_paper_mode_falling_knife_protection(self, fresh_container):
        """Test falling knife protection blocks buy during bearish sentiment."""
        # Test with extreme bearish sentiment directly
        risk_result = fresh_container.risk_guardian.validate_trade(
            side="buy", symbol="BTC/USDT", amount_usd=100.0, portfolio_value=10000.0, sentiment_score=-0.7
        )
        assert risk_result["allowed"] is False
        assert "Falling Knife" in risk_result["reason"]


class TestCexLiveModeFlow:
    """Test CEX execution in live mode (mocked).

    These drive the real `place_cex_order` tool (not the paper/testing helpers)
    so the live-safety gates are proven through the same code path agents use.
    Each test also patches `CexExecutor` so no real exchange client can be built.
    """

    def test_live_mode_requires_consent(self):
        """place_cex_order refuses to execute when LIVE_TRADING_ENABLED=false."""
        with (
            patch.multiple(
                settings,
                PAPER_MODE=False,
                LIVE_TRADING_ENABLED=False,
                TRADING_HALTED=False,
                EXECUTION_MODE=ExecutionMode.CEX,
            ),
            patch("app.tools.execution.CexExecutor") as mock_executor,
        ):
            res = json.loads(place_cex_order("BTC/USDT", "buy", 0.01, order_type="market", price=50_000.0))
        assert res["ok"] is False
        mock_executor.assert_not_called()
        # An operator switch saying no is reported as itself, not as an exchange failure.
        assert res["error"]["code"] == "live_trading_disabled"

    def test_live_mode_halted_blocks_execution(self):
        """Test that TRADING_HALTED blocks live execution."""
        with (
            patch.multiple(
                settings,
                PAPER_MODE=False,
                LIVE_TRADING_ENABLED=True,
                TRADING_HALTED=True,
                EXECUTION_MODE=ExecutionMode.CEX,
            ),
            patch("app.tools.execution.CexExecutor") as mock_executor,
        ):
            res = json.loads(place_cex_order("BTC/USDT", "buy", 0.01, order_type="market", price=50_000.0))
        assert res["ok"] is False
        mock_executor.assert_not_called()

    def test_approval_mode_returns_proposal(self):
        """Test approve_each mode returns proposal instead of executing."""
        proposal = SimpleNamespace(request_id="req-1", confirm_token="tok-1", expires_at=1.0, kind="place_cex_order")
        with (
            patch.multiple(
                settings,
                PAPER_MODE=False,
                LIVE_TRADING_ENABLED=True,
                TRADING_HALTED=False,
                EXECUTION_MODE=ExecutionMode.CEX,
                EXECUTION_APPROVAL_MODE=ApprovalMode.APPROVE_EACH,
            ),
            patch.object(global_container.execution_store, "create", return_value=proposal) as create,
            patch("app.tools.execution.CexExecutor") as mock_executor,
            # The Risk Guardian reads the exchange account before proposing: 100,000 USDT.
            patch("app.tools.trading.CexExecutor") as account,
        ):
            account.return_value.fetch_balance.return_value = {"total": {"USDT": 100_000.0}}
            res = json.loads(place_cex_order("BTC/USDT", "buy", 0.01, order_type="market", price=50_000.0))
        assert res["ok"] is True, res
        assert res["data"]["approval_required"] is True
        assert res["data"]["request_id"] == "req-1"
        mock_executor.assert_not_called()
        assert create.call_args.kwargs["payload"]["paper_mode"] is False, "a proposal records the mode it was made in"


class TestIdempotencyFlow:
    """Test idempotency key handling in execution."""

    def test_idempotency_store_basic_operations(self, fresh_container):
        """Test idempotency store basic set/get operations."""
        store = fresh_container.idempotency_store

        # Set a value
        store.set("test-key", {"order_id": "123", "status": "filled"})

        # Get it back
        result = store.get("test-key")
        assert result is not None
        assert result["order_id"] == "123"

        # Get non-existent key
        missing = store.get("nonexistent")
        assert missing is None


class TestAuditLogging:
    """Test audit log integration."""

    def test_audit_log_enabled_and_append(self, fresh_container):
        """Test that audit log is enabled and can append entries."""
        from observability.audit import now_ms

        # Verify audit log is enabled
        assert fresh_container.audit_log.enabled() is True

        # Append a test entry
        fresh_container.audit_log.append(
            ts_ms=now_ms(), request_id="test-audit-123", tool="test_tool", ok=True, mode="paper", venue="cex", summary={"test": "data"}
        )


class TestMarketDataIntegration:
    """Test market data integration with execution."""

    def test_marketdata_bus_ticker_fetch(self, fresh_container):
        """Test market data bus can fetch ticker data."""
        # Store mock data in the ingest store
        fresh_container.marketdata_store.put_ticker(
            symbol="BTC/USDT", last=50000.0, bid=49999.0, ask=50001.0, timestamp_ms=1704067200000, source="test_ingest", ttl_sec=60.0
        )

        # Fetch should return our ingested data
        result = fresh_container.marketdata_bus.fetch_ticker("BTC/USDT")

        assert result.data["last"] == 50000.0
        assert result.source == "ingest"
