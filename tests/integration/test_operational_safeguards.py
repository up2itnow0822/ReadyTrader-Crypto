"""
Integration tests for operational safeguards.

These tests verify that critical safety mechanisms work end-to-end:
- Kill switch (max drawdown halt)
- Daily loss limits
- Position sizing limits
- Falling knife protection
- Policy engine allowlists
- Approval gates

Run with: pytest tests/integration/test_operational_safeguards.py -v
"""

from typing import Generator

import pytest

from policy_engine import PolicyEngine, PolicyError
from risk_manager import RiskGuardian


class TestKillSwitch:
    """Test max drawdown kill switch functionality."""

    def test_kill_switch_blocks_buys_at_max_drawdown(self, risk_guardian: RiskGuardian) -> None:
        """Kill switch should block all BUY orders when drawdown hits 10%."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.10,  # Exactly at 10%
        )
        assert result["allowed"] is False
        assert "Max Drawdown Limit Hit" in result["reason"]

    def test_kill_switch_allows_sells_at_max_drawdown(self, risk_guardian: RiskGuardian) -> None:
        """Kill switch should allow SELL orders to reduce risk even at max drawdown."""
        result = risk_guardian.validate_trade(
            side="sell",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.10,
        )
        assert result["allowed"] is True

    def test_kill_switch_triggers_beyond_threshold(self, risk_guardian: RiskGuardian) -> None:
        """Kill switch should trigger when drawdown exceeds 10%."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="ETH/USDT",
            amount_usd=50.0,
            portfolio_value=5000.0,
            sentiment_score=0.5,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.15,  # 15% drawdown - exceeds threshold
        )
        assert result["allowed"] is False
        assert "Max Drawdown Limit Hit" in result["reason"] and "halted" in result["reason"]


class TestDailyLossLimit:
    """Test daily loss limit enforcement."""

    def test_daily_loss_limit_blocks_at_5_percent(self, risk_guardian: RiskGuardian) -> None:
        """Should block BUY orders when daily loss hits 5%."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=-0.05,  # Exactly at -5%
            current_drawdown_pct=0.0,
        )
        assert result["allowed"] is False
        assert "Daily Loss Limit Hit" in result["reason"]

    def test_daily_loss_allows_below_threshold(self, risk_guardian: RiskGuardian) -> None:
        """Should allow trades when daily loss is below threshold."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=-0.04,  # -4%, below threshold
            current_drawdown_pct=0.0,
        )
        assert result["allowed"] is True

    def test_daily_loss_allows_sells(self, risk_guardian: RiskGuardian) -> None:
        """Should allow SELL orders even when daily loss limit hit."""
        result = risk_guardian.validate_trade(
            side="sell",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=-0.06,  # -6%, exceeds threshold
            current_drawdown_pct=0.0,
        )
        assert result["allowed"] is True


class TestPositionSizeLimits:
    """Test position sizing enforcement (max 5% per trade)."""

    def test_position_size_blocks_over_5_percent(self, risk_guardian: RiskGuardian) -> None:
        """Should block trades exceeding 5% of portfolio."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=600.0,  # 6% of 10,000
            portfolio_value=10000.0,
        )
        assert result["allowed"] is False
        assert "Position size too large" in result["reason"]

    def test_position_size_allows_at_5_percent(self, risk_guardian: RiskGuardian) -> None:
        """Should allow trades at exactly 5% of portfolio."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=500.0,  # Exactly 5% of 10,000
            portfolio_value=10000.0,
        )
        assert result["allowed"] is True

    def test_position_size_allows_below_5_percent(self, risk_guardian: RiskGuardian) -> None:
        """Should allow trades below 5% of portfolio."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=400.0,  # 4% of 10,000
            portfolio_value=10000.0,
        )
        assert result["allowed"] is True


class TestFallingKnifeProtection:
    """Test falling knife protection (blocks buys during extreme bearish sentiment)."""

    def test_falling_knife_blocks_buy_on_extreme_bearish(self, risk_guardian: RiskGuardian) -> None:
        """Should block BUY orders when sentiment is extremely bearish (<-0.5)."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=-0.6,  # Very bearish
        )
        assert result["allowed"] is False
        assert "Falling Knife" in result["reason"]

    def test_falling_knife_allows_sell_on_extreme_bearish(self, risk_guardian: RiskGuardian) -> None:
        """Should allow SELL orders to cut losses even in bearish conditions."""
        result = risk_guardian.validate_trade(
            side="sell",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=-0.8,  # Extremely bearish
        )
        assert result["allowed"] is True

    def test_falling_knife_allows_buy_on_mild_bearish(self, risk_guardian: RiskGuardian) -> None:
        """Should allow BUY orders when sentiment is only mildly bearish."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=100.0,
            portfolio_value=10000.0,
            sentiment_score=-0.4,  # Mildly bearish, above threshold
        )
        assert result["allowed"] is True


class TestPolicyEngineAllowlists:
    """Test policy engine allowlist enforcement."""

    @pytest.fixture(autouse=True)
    def setup_allowlists(self, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
        """Set up test allowlists."""
        monkeypatch.setenv("ALLOW_CHAINS", "ethereum,polygon,arbitrum")
        monkeypatch.setenv("ALLOW_TOKENS", "eth,usdc,usdt,weth")
        monkeypatch.setenv("MAX_TRADE_AMOUNT", "5000")
        monkeypatch.setenv("ALLOW_EXCHANGES", "binance,coinbase,kraken")
        yield
        # Cleanup happens automatically with monkeypatch

    def test_chain_allowlist_blocks_non_allowed(self) -> None:
        """Should block swaps on non-allowlisted chains."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_swap(
                chain="solana",
                from_token="sol",
                to_token="usdc",
                amount=100.0,
            )
        assert exc_info.value.code == "chain_not_allowed"

    def test_chain_allowlist_allows_listed(self) -> None:
        """Should allow swaps on allowlisted chains."""
        pe = PolicyEngine()
        # Should not raise
        pe.validate_swap(
            chain="ethereum",
            from_token="eth",
            to_token="usdc",
            amount=100.0,
        )

    def test_token_allowlist_blocks_non_allowed(self) -> None:
        """Should block swaps with non-allowlisted tokens."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_swap(
                chain="ethereum",
                from_token="shib",  # Not in allowlist
                to_token="usdc",
                amount=100.0,
            )
        assert exc_info.value.code == "token_not_allowed"

    def test_trade_amount_limit_blocks_excessive(self) -> None:
        """Should block trades exceeding MAX_TRADE_AMOUNT."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_swap(
                chain="ethereum",
                from_token="eth",
                to_token="usdc",
                amount=6000.0,  # Exceeds 5000 limit
            )
        assert exc_info.value.code == "trade_amount_too_large"

    def test_exchange_allowlist_blocks_non_allowed(self) -> None:
        """Should block orders on non-allowlisted exchanges."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_cex_order(
                exchange_id="unknown_exchange",
                symbol="BTC/USDT",
                side="buy",
                amount=0.01,
                order_type="market",
            )
        assert exc_info.value.code == "exchange_not_allowed"

    def test_exchange_allowlist_allows_listed(self) -> None:
        """Should allow orders on allowlisted exchanges."""
        pe = PolicyEngine()
        # Should not raise
        pe.validate_cex_order(
            exchange_id="binance",
            symbol="BTC/USDT",
            side="buy",
            amount=0.01,
            order_type="market",
        )


class TestCombinedSafeguards:
    """Test multiple safeguards working together."""

    def test_multiple_conditions_fail_first_check(self, risk_guardian: RiskGuardian) -> None:
        """When multiple conditions would fail, the first check should trigger."""
        # This has both max drawdown AND oversized position
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=600.0,  # 6%, would fail position check
            portfolio_value=10000.0,
            sentiment_score=0.0,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.12,  # Would fail drawdown check
        )
        assert result["allowed"] is False
        # Drawdown check comes first
        assert "Max Drawdown" in result["reason"]

    def test_all_checks_pass_allows_trade(self, risk_guardian: RiskGuardian) -> None:
        """Trade should be allowed when all safeguards pass."""
        result = risk_guardian.validate_trade(
            side="buy",
            symbol="BTC/USDT",
            amount_usd=300.0,  # 3%, within limits
            portfolio_value=10000.0,
            sentiment_score=0.2,  # Slightly bullish
            daily_loss_pct=-0.01,  # Small loss
            current_drawdown_pct=0.02,  # Small drawdown
        )
        assert result["allowed"] is True
        assert "looks safe" in result["reason"].lower()


class TestSigningPolicyGuardrails:
    """Test signer-side policy guardrails (defense in depth)."""

    @pytest.fixture(autouse=True)
    def setup_signing_limits(self, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
        """Set up signing policy limits."""
        monkeypatch.setenv("ALLOW_SIGN_CHAIN_IDS", "1,137,42161")  # Mainnet, Polygon, Arbitrum
        monkeypatch.setenv("MAX_SIGN_VALUE_WEI", str(10 * 10**18))  # 10 ETH max
        monkeypatch.setenv("MAX_SIGN_GAS", "500000")
        monkeypatch.setenv("DISALLOW_SIGN_CONTRACT_CREATION", "true")
        yield

    def test_signing_blocks_non_allowed_chain_id(self) -> None:
        """Should block signing for non-allowlisted chain IDs."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_sign_tx(
                chain_id=56,  # BSC, not in allowlist
                to_address="0x1234567890123456789012345678901234567890",
                value_wei=1000000000000000000,  # 1 ETH
                gas=100000,
                gas_price_wei=20000000000,
                data_hex="0x",
            )
        assert exc_info.value.code == "sign_chain_id_not_allowed"

    def test_signing_blocks_excessive_value(self) -> None:
        """Should block signing transactions with excessive value."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_sign_tx(
                chain_id=1,
                to_address="0x1234567890123456789012345678901234567890",
                value_wei=20 * 10**18,  # 20 ETH, exceeds 10 ETH limit
                gas=100000,
                gas_price_wei=20000000000,
                data_hex="0x",
            )
        assert exc_info.value.code == "sign_value_too_large"

    def test_signing_blocks_contract_creation(self) -> None:
        """Should block contract creation when disallowed."""
        pe = PolicyEngine()
        with pytest.raises(PolicyError) as exc_info:
            pe.validate_sign_tx(
                chain_id=1,
                to_address=None,  # Contract creation (no to address)
                value_wei=0,
                gas=200000,
                gas_price_wei=20000000000,
                data_hex="0x608060405234801561001057600080fd5b50",  # Contract bytecode
            )
        assert exc_info.value.code == "sign_contract_creation_not_allowed"

    def test_signing_allows_valid_transaction(self) -> None:
        """Should allow valid transactions within limits."""
        pe = PolicyEngine()
        # Should not raise
        pe.validate_sign_tx(
            chain_id=1,
            to_address="0x1234567890123456789012345678901234567890",
            value_wei=1 * 10**18,  # 1 ETH
            gas=100000,
            gas_price_wei=20000000000,
            data_hex="0x",
        )
