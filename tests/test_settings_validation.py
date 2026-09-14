"""Tests for settings validation and security warnings."""

import importlib
import os
import warnings
from unittest.mock import patch

import pytest


class TestSettingsValidation:
    """Test settings validation logic."""

    def test_settings_load_defaults(self):
        """Test that settings load with safe defaults."""
        with patch.dict(os.environ, {}, clear=True):
            # Reload to get fresh settings
            import app.core.settings

            importlib.reload(app.core.settings)
            settings = app.core.settings.Settings()

            # Safe defaults
            assert settings.PAPER_MODE is True
            assert settings.LIVE_TRADING_ENABLED is False
            assert settings.TRADING_HALTED is True
            assert settings.DEV_MODE is False

    def test_settings_version_from_pyproject(self):
        """Test that version is loaded from pyproject.toml."""
        with patch.dict(os.environ, {}, clear=True):
            import app.core.settings

            importlib.reload(app.core.settings)
            settings = app.core.settings.Settings()

            assert settings.VERSION is not None
            assert len(settings.VERSION) > 0
            # Should match semver pattern
            parts = settings.VERSION.split(".")
            assert len(parts) >= 2

    def test_settings_validates_port_range(self):
        """Test that invalid port raises validation error."""
        # Import the error class before modifying environment
        from app.core.settings import SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "API_PORT": "99999",  # Invalid port
                "DEV_MODE": "true",
            },
        ):
            # Import Settings class directly (not the module global instance)
            # to test validation without triggering module-level instantiation
            import app.core.settings

            # We need to import the class without triggering module reload
            # which would create a new global instance
            Settings = app.core.settings.Settings

            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()

            assert "API_PORT" in str(exc_info.value)

    def test_settings_requires_jwt_secret_in_production(self):
        """Test that JWT secret is required in production mode with auth."""
        # Import the classes before modifying environment
        from app.core.settings import Settings, SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "",  # Missing
                "CORS_ORIGINS": "http://localhost:3000",  # Non-wildcard to avoid second error
            },
        ):
            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()

            assert "API_JWT_SECRET" in str(exc_info.value)

    def test_settings_warns_on_dev_mode(self):
        """Test that DEV_MODE=true emits a warning."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                app.core.settings.Settings()

                # Should have at least one warning about DEV_MODE
                dev_warnings = [x for x in w if "DEV_MODE" in str(x.message)]
                assert len(dev_warnings) >= 1

    def test_settings_warns_on_unauthenticated_production(self):
        """Test that unauthenticated API in production emits warning (paper path)."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "PAPER_MODE": "true",
                "LIVE_TRADING_ENABLED": "false",
                "API_AUTH_REQUIRED": "false",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                app.core.settings.Settings()

                auth_warnings = [x for x in w if "API_AUTH_REQUIRED" in str(x.message)]
                assert len(auth_warnings) >= 1

    def test_settings_rejects_unauthenticated_live_production(self):
        """Live/non-paper + DEV_MODE=false requires API auth."""
        from app.core.settings import Settings, SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "PAPER_MODE": "false",
                "LIVE_TRADING_ENABLED": "true",
                "API_AUTH_REQUIRED": "false",
                "CORS_ORIGINS": "http://localhost:3000",
                "SIGNER_TYPE": "remote",
                "SIGNER_REMOTE_URL": "https://signer.example:8080",
            },
        ):
            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()
            assert "API_AUTH_REQUIRED" in str(exc_info.value)

    def test_settings_rejects_cors_wildcard_live_production(self):
        """Live production refuses CORS wildcard."""
        from app.core.settings import Settings, SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "PAPER_MODE": "false",
                "LIVE_TRADING_ENABLED": "true",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "x" * 32,
                "CORS_ORIGINS": "*",
                "SIGNER_TYPE": "remote",
                "SIGNER_REMOTE_URL": "https://signer.example:8080",
            },
        ):
            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()
            assert "CORS" in str(exc_info.value)

    def test_settings_forbids_env_private_key_when_live(self):
        """env_private_key banned when LIVE_TRADING_ENABLED or PAPER_MODE=false."""
        from app.core.settings import Settings, SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "PAPER_MODE": "false",
                "LIVE_TRADING_ENABLED": "true",
                "SIGNER_TYPE": "env_private_key",
                "PRIVATE_KEY": "0x" + "11" * 32,
            },
        ):
            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()
            assert "env_private_key" in str(exc_info.value)

    def test_settings_warns_on_cors_wildcard_production(self):
        """Test that CORS wildcard in production emits warning."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "CORS_ORIGINS": "*",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                app.core.settings.Settings()

                cors_warnings = [x for x in w if "CORS" in str(x.message)]
                assert len(cors_warnings) >= 1

    def test_settings_live_mode_requires_remote_signer_url(self):
        """Test that live mode with remote signer requires URL."""
        from app.core.settings import Settings, SettingsValidationError

        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "PAPER_MODE": "false",
                "LIVE_TRADING_ENABLED": "true",
                "SIGNER_TYPE": "remote",
                "SIGNER_REMOTE_URL": "",
            },
        ):
            with pytest.raises(SettingsValidationError) as exc_info:
                Settings()

            assert "SIGNER_REMOTE_URL" in str(exc_info.value)

    def test_settings_to_dict_redacts_secrets(self):
        """Test that to_dict redacts sensitive values."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "API_JWT_SECRET": "super-secret-key",
                "PRIVATE_KEY": "0x1234567890",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)
            settings = app.core.settings.Settings()

            config_dict = settings.to_dict()

            # Secrets should be redacted
            assert config_dict.get("API_JWT_SECRET") == "***REDACTED***"
            assert config_dict.get("PRIVATE_KEY") == "***REDACTED***"
            # Non-secrets should be visible
            assert config_dict.get("PROJECT_NAME") == "ReadyTrader-Crypto"

    def test_settings_risk_profile_config(self):
        """Test risk profile configuration access."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "RISK_PROFILE": "conservative",
            },
        ):
            from app.core.settings import Settings

            settings = Settings()

            config = settings.risk_config
            assert config.max_position_pct > 0
            assert config.max_daily_loss_pct > 0
            assert config.max_drawdown_pct > 0

    def test_settings_is_live_execution_allowed(self):
        """Test is_live_execution_allowed property."""
        # Paper mode = not allowed (LIVE flag alone is insufficient)
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "PAPER_MODE": "true",
                "LIVE_TRADING_ENABLED": "false",
                "SIGNER_TYPE": "null",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)
            settings = app.core.settings.Settings()
            assert settings.is_live_execution_allowed is False

        # Trading halted = not allowed
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "PAPER_MODE": "false",
                "LIVE_TRADING_ENABLED": "true",
                "TRADING_HALTED": "true",
                "SIGNER_TYPE": "remote",
                "SIGNER_REMOTE_URL": "https://signer.example:8080",
            },
        ):
            import app.core.settings

            importlib.reload(app.core.settings)
            settings = app.core.settings.Settings()
            assert settings.is_live_execution_allowed is False

    def test_factory_rejects_env_private_key_when_live(self):
        """signing.factory refuses env_private_key under live flags (defense in depth)."""
        with patch.dict(
            os.environ,
            {
                "DEV_MODE": "true",
                "PAPER_MODE": "true",
                "LIVE_TRADING_ENABLED": "false",
                "SIGNER_TYPE": "env_private_key",
                "PRIVATE_KEY": "0x" + "11" * 32,
            },
            clear=False,
        ):
            import importlib
            from unittest.mock import MagicMock

            import app.core.settings

            importlib.reload(app.core.settings)
            import signing.factory as factory

            importlib.reload(factory)
            factory.get_signer.cache_clear()

            mock_settings = MagicMock()
            mock_settings.PAPER_MODE = True
            mock_settings.LIVE_TRADING_ENABLED = True
            with patch("app.core.config.settings", mock_settings):
                with pytest.raises(ValueError, match="env_private_key"):
                    factory.get_signer()
            factory.get_signer.cache_clear()


class TestExecutionStoreEdgeCases:
    """Test execution store edge cases."""

    def test_double_execution_prevention(self, tmp_path):
        """Test that proposals cannot be executed twice."""
        from execution_store import ExecutionStore

        # Use environment variable to set db path
        with patch.dict(os.environ, {"READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "test_store.db")}):
            store = ExecutionStore()

            # Create and confirm a proposal (using keyword arguments)
            prop = store.create(kind="cex_order", payload={"symbol": "BTC/USDT", "amount": 0.1})
            store.confirm(prop.request_id, prop.confirm_token)

            # Mark as executed
            result1 = store.mark_executed(prop.request_id, {"order_id": "123"})
            assert result1 is True

            # Try to execute again - should fail
            result2 = store.mark_executed(prop.request_id, {"order_id": "456"})
            assert result2 is False

            # Verify original result is preserved
            stored = store.get(prop.request_id)
            assert stored is not None
            assert stored.execution_result == {"order_id": "123"}

    def test_expired_proposal_cannot_confirm(self, tmp_path):
        """Test that expired proposals cannot be confirmed."""
        import time

        from execution_store import ExecutionStore

        with patch.dict(os.environ, {"READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "test_store.db")}):
            store = ExecutionStore()

            # Create a proposal with very short TTL
            prop = store.create(kind="cex_order", payload={"symbol": "BTC/USDT", "amount": 0.1}, ttl_seconds=0)

            # Should already be expired
            time.sleep(0.1)

            # Try to confirm - should raise ValueError for expired proposal
            with pytest.raises(ValueError, match="expired"):
                store.confirm(prop.request_id, prop.confirm_token)

    def test_wrong_token_cannot_confirm(self, tmp_path):
        """Test that wrong token cannot confirm proposal."""
        from execution_store import ExecutionStore

        with patch.dict(os.environ, {"READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "test_store.db")}):
            store = ExecutionStore()

            prop = store.create(kind="cex_order", payload={"symbol": "BTC/USDT", "amount": 0.1})

            # Try with wrong token - should raise ValueError
            with pytest.raises(ValueError, match="confirm_token"):
                store.confirm(prop.request_id, "wrong-token")

            # Original should still be pending
            stored = store.get(prop.request_id)
            assert stored is not None
            assert stored.status == "pending"

    def test_cancel_marks_proposal(self, tmp_path):
        """Test that cancelled proposals are marked as cancelled."""
        from execution_store import ExecutionStore

        with patch.dict(os.environ, {"READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "test_store.db")}):
            store = ExecutionStore()

            prop = store.create(kind="cex_order", payload={"symbol": "BTC/USDT", "amount": 0.1})

            # Cancel
            store.cancel(prop.request_id)

            # Should be marked as cancelled
            stored = store.get(prop.request_id)
            assert stored is not None
            assert stored.status == "cancelled"

    def test_proposal_status_lifecycle(self, tmp_path):
        """Test that proposal follows correct status lifecycle."""
        from execution_store import ExecutionStore

        with patch.dict(os.environ, {"READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "test_store.db")}):
            store = ExecutionStore()

            # Create - should be pending
            prop = store.create(kind="cex_order", payload={"symbol": "BTC/USDT", "amount": 0.1})
            assert prop.status == "pending"

            # Confirm - should be confirmed
            confirmed = store.confirm(prop.request_id, prop.confirm_token)
            assert confirmed is not None
            assert confirmed.status == "confirmed"

            # Execute - should be executed
            store.mark_executed(prop.request_id, {"order_id": "test123"})
            executed = store.get(prop.request_id)
            assert executed is not None
            assert executed.status == "executed"


class TestDockerConfiguration:
    """Test Docker configuration correctness."""

    def test_dockerfile_has_matching_healthcheck(self):
        """Test that Dockerfile has proper healthcheck matching CMD."""
        from pathlib import Path

        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()

        # Check that we have both MCP and API targets
        assert "FROM base AS mcp" in content
        assert "FROM base AS api" in content

        # MCP target should have Python-based healthcheck (no HTTP)
        mcp_section = content.split("FROM base AS mcp")[1].split("FROM")[0]
        assert "urllib.request" not in mcp_section
        assert "python -c" in mcp_section

        # API target should have HTTP healthcheck
        api_section = content.split("FROM base AS api")[1].split("FROM")[0]
        assert "curl" in api_section or "health" in api_section

    def test_dockerfile_uses_non_root_user(self):
        """Test that Dockerfile runs as non-root."""
        from pathlib import Path

        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()

        assert "USER readytrader" in content
        assert "useradd" in content
        assert "groupadd" in content

    def test_dockerfile_has_secure_defaults(self):
        """Test that Dockerfile has secure default environment."""
        from pathlib import Path

        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()

        assert "PAPER_MODE=true" in content
        assert "LIVE_TRADING_ENABLED=false" in content
        assert "DEV_MODE=false" in content
