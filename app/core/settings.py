"""
ReadyTrader-Crypto Unified Settings System

This module provides a validated, typed settings layer that serves as the single
source of truth for all configuration. All environment variables are validated
at startup to catch misconfigurations early.

Usage:
    from app.core.settings import settings

    if settings.PAPER_MODE:
        # paper trading logic
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any, FrozenSet, Set

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ExecutionMode(str, Enum):
    """Execution routing mode."""

    DEX = "dex"
    CEX = "cex"
    HYBRID = "hybrid"
    AUTO = "auto"


class ApprovalMode(str, Enum):
    """Execution approval mode."""

    AUTO = "auto"
    APPROVE_EACH = "approve_each"


class RiskProfile(str, Enum):
    """Risk profile presets."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class SignerType(Enum):
    """Signer backend types."""

    ENV_PRIVATE_KEY = "env_private_key"
    KEYSTORE = "keystore"
    REMOTE = "remote"
    CB_MPC_2PC = "cb_mpc_2pc"
    NULL = "null"


class SettingsValidationError(Exception):
    """Raised when settings validation fails."""

    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        super().__init__(f"Invalid configuration for {field}={value!r}: {message}")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean from environment variable."""
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


def _parse_int(value: str | None, default: int | None = None) -> int | None:
    """Parse an integer from environment variable."""
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip(), 0)  # Support hex with 0x prefix
    except ValueError:
        return default


def _parse_float(value: str | None, default: float | None = None) -> float | None:
    """Parse a float from environment variable."""
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _parse_csv_set(value: str | None) -> FrozenSet[str]:
    """Parse a comma-separated list into a frozen set of lowercase strings."""
    if not value:
        return frozenset()
    return frozenset(v.strip().lower() for v in value.split(",") if v.strip())


def _parse_csv_int_set(value: str | None) -> FrozenSet[int]:
    """Parse a comma-separated list of integers."""
    if not value:
        return frozenset()
    result: Set[int] = set()
    for part in value.split(","):
        s = part.strip()
        if not s:
            continue
        try:
            result.add(int(s, 0))
        except ValueError:
            continue
    return frozenset(result)


def _get_version_from_pyproject() -> str:
    """Extract version from pyproject.toml."""
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        version: str = str(data.get("project", {}).get("version", "0.0.0"))
        return version
    except Exception:
        return "0.0.0"


@dataclass(frozen=True)
class RiskProfileConfig:
    """Risk profile configuration values."""

    max_position_pct: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    falling_knife_threshold: float


# Risk profile presets
RISK_PROFILES: dict[RiskProfile, RiskProfileConfig] = {
    RiskProfile.CONSERVATIVE: RiskProfileConfig(
        max_position_pct=0.05,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.10,
        falling_knife_threshold=-0.5,
    ),
    RiskProfile.MODERATE: RiskProfileConfig(
        max_position_pct=0.10,
        max_daily_loss_pct=0.10,
        max_drawdown_pct=0.20,
        falling_knife_threshold=-0.7,
    ),
    RiskProfile.AGGRESSIVE: RiskProfileConfig(
        max_position_pct=0.25,
        max_daily_loss_pct=0.20,
        max_drawdown_pct=0.40,
        falling_knife_threshold=-0.9,
    ),
}


@dataclass
class Settings:
    """
    Unified settings class with validation.

    All configuration is loaded and validated at instantiation time.
    This ensures misconfigurations are caught at startup, not runtime.
    """

    # Project metadata (read from pyproject.toml)
    PROJECT_NAME: str = "ReadyTrader-Crypto"
    VERSION: str = field(default_factory=_get_version_from_pyproject)

    # Core mode settings
    PAPER_MODE: bool = field(default_factory=lambda: _parse_bool(os.getenv("PAPER_MODE"), True))
    LIVE_TRADING_ENABLED: bool = field(default_factory=lambda: _parse_bool(os.getenv("LIVE_TRADING_ENABLED"), False))
    # Default halted: operator must explicitly set TRADING_HALTED=false to trade.
    TRADING_HALTED: bool = field(default_factory=lambda: _parse_bool(os.getenv("TRADING_HALTED"), True))
    DEV_MODE: bool = field(default_factory=lambda: _parse_bool(os.getenv("DEV_MODE"), False))

    # Execution settings
    EXECUTION_MODE: ExecutionMode = field(
        default_factory=lambda: ExecutionMode(os.getenv("EXECUTION_MODE", "auto").strip().lower())
        if os.getenv("EXECUTION_MODE", "auto").strip().lower() in [e.value for e in ExecutionMode]
        else ExecutionMode.AUTO
    )

    EXECUTION_APPROVAL_MODE: ApprovalMode = field(
        default_factory=lambda: ApprovalMode(os.getenv("EXECUTION_APPROVAL_MODE", "auto").strip().lower())
        if os.getenv("EXECUTION_APPROVAL_MODE", "auto").strip().lower() in [e.value for e in ApprovalMode]
        else ApprovalMode.AUTO
    )

    # Risk settings
    RISK_PROFILE: RiskProfile = field(
        default_factory=lambda: RiskProfile(os.getenv("RISK_PROFILE", "conservative").strip().lower())
        if os.getenv("RISK_PROFILE", "conservative").strip().lower() in [e.value for e in RiskProfile]
        else RiskProfile.CONSERVATIVE
    )

    # API server settings
    API_PORT: int = field(default_factory=lambda: _parse_int(os.getenv("API_PORT"), 8000) or 8000)
    API_HOST: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0").strip())  # nosec B104 - intentional for container binding
    API_AUTH_REQUIRED: bool = field(default_factory=lambda: _parse_bool(os.getenv("API_AUTH_REQUIRED"), False))
    API_JWT_SECRET: str | None = field(default_factory=lambda: os.getenv("API_JWT_SECRET"))
    API_JWT_EXPIRATION_HOURS: int = field(default_factory=lambda: _parse_int(os.getenv("API_JWT_EXPIRATION_HOURS"), 24) or 24)
    API_ADMIN_USERNAME: str = field(default_factory=lambda: os.getenv("API_ADMIN_USERNAME", "admin").strip())
    API_ADMIN_PASSWORD_HASH: str | None = field(default_factory=lambda: os.getenv("API_ADMIN_PASSWORD_HASH"))

    # CORS settings
    CORS_ORIGINS: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("CORS_ORIGINS", "*")))
    CORS_ALLOW_ALL: bool = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*").strip() == "*")

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = field(default_factory=lambda: _parse_bool(os.getenv("RATE_LIMIT_ENABLED"), True))
    RATE_LIMIT_DEFAULT_PER_MIN: int = field(default_factory=lambda: _parse_int(os.getenv("RATE_LIMIT_DEFAULT_PER_MIN"), 120) or 120)
    RATE_LIMIT_EXECUTION_PER_MIN: int = field(default_factory=lambda: _parse_int(os.getenv("RATE_LIMIT_EXECUTION_PER_MIN"), 20) or 20)

    # Signer settings
    SIGNER_TYPE: SignerType = field(
        default_factory=lambda: SignerType(os.getenv("SIGNER_TYPE", "env_private_key").strip().lower())
        if os.getenv("SIGNER_TYPE", "env_private_key").strip().lower() in [e.value for e in SignerType]
        else SignerType.ENV_PRIVATE_KEY
    )
    PRIVATE_KEY: str | None = field(default_factory=lambda: os.getenv("PRIVATE_KEY"))
    KEYSTORE_PATH: str | None = field(default_factory=lambda: os.getenv("KEYSTORE_PATH"))
    KEYSTORE_PASSWORD: str | None = field(default_factory=lambda: os.getenv("KEYSTORE_PASSWORD"))
    SIGNER_REMOTE_URL: str | None = field(default_factory=lambda: os.getenv("SIGNER_REMOTE_URL"))
    MPC_SIGNER_URL: str | None = field(default_factory=lambda: os.getenv("MPC_SIGNER_URL"))

    # Signer policy
    SIGNER_POLICY_ENABLED: bool = field(default_factory=lambda: _parse_bool(os.getenv("SIGNER_POLICY_ENABLED"), False))
    SIGNER_ALLOWED_CHAIN_IDS: FrozenSet[int] = field(default_factory=lambda: _parse_csv_int_set(os.getenv("SIGNER_ALLOWED_CHAIN_IDS")))
    SIGNER_ALLOWED_TO_ADDRESSES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("SIGNER_ALLOWED_TO_ADDRESSES")))
    SIGNER_MAX_VALUE_WEI: int | None = field(default_factory=lambda: _parse_int(os.getenv("SIGNER_MAX_VALUE_WEI")))
    SIGNER_MAX_GAS: int | None = field(default_factory=lambda: _parse_int(os.getenv("SIGNER_MAX_GAS")))
    SIGNER_MAX_GAS_PRICE_WEI: int | None = field(default_factory=lambda: _parse_int(os.getenv("SIGNER_MAX_GAS_PRICE_WEI")))
    SIGNER_MAX_DATA_BYTES: int | None = field(default_factory=lambda: _parse_int(os.getenv("SIGNER_MAX_DATA_BYTES")))
    SIGNER_DISALLOW_CONTRACT_CREATION: bool = field(default_factory=lambda: _parse_bool(os.getenv("SIGNER_DISALLOW_CONTRACT_CREATION"), False))

    # Policy allowlists
    ALLOW_CHAINS: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_CHAINS")))
    ALLOW_TOKENS: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_TOKENS")))
    ALLOW_ROUTERS: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_ROUTERS")))
    ALLOW_EXCHANGES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_EXCHANGES")))
    ALLOW_SIGNER_ADDRESSES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_SIGNER_ADDRESSES")))
    ALLOW_TO_ADDRESSES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_TO_ADDRESSES")))
    ALLOW_CEX_SYMBOLS: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_CEX_SYMBOLS")))
    ALLOW_CEX_MARKET_TYPES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("ALLOW_CEX_MARKET_TYPES")))

    # Policy limits
    MAX_TRADE_AMOUNT: float | None = field(default_factory=lambda: _parse_float(os.getenv("MAX_TRADE_AMOUNT")))
    MAX_TRANSFER_NATIVE: float | None = field(default_factory=lambda: _parse_float(os.getenv("MAX_TRANSFER_NATIVE")))
    MAX_CEX_ORDER_AMOUNT: float | None = field(default_factory=lambda: _parse_float(os.getenv("MAX_CEX_ORDER_AMOUNT")))
    DEX_SLIPPAGE_PCT: float = field(default_factory=lambda: _parse_float(os.getenv("DEX_SLIPPAGE_PCT"), 1.0) or 1.0)

    # Market data settings
    MARKETDATA_EXCHANGES: FrozenSet[str] = field(default_factory=lambda: _parse_csv_set(os.getenv("MARKETDATA_EXCHANGES", "binance,kraken,coinbase")))
    CCXT_DEFAULT_TYPE: str = field(default_factory=lambda: os.getenv("CCXT_DEFAULT_TYPE", "spot").strip())
    CCXT_PROXY: str | None = field(default_factory=lambda: os.getenv("CCXT_PROXY"))
    TICKER_CACHE_TTL_SEC: int = field(default_factory=lambda: _parse_int(os.getenv("TICKER_CACHE_TTL_SEC"), 5) or 5)
    OHLCV_CACHE_TTL_SEC: int = field(default_factory=lambda: _parse_int(os.getenv("OHLCV_CACHE_TTL_SEC"), 60) or 60)
    MARKETS_CACHE_TTL_SEC: int = field(default_factory=lambda: _parse_int(os.getenv("MARKETS_CACHE_TTL_SEC"), 300) or 300)
    HTTP_TIMEOUT_SEC: int = field(default_factory=lambda: _parse_int(os.getenv("HTTP_TIMEOUT_SEC"), 10) or 10)

    # Market data guardrails
    MARKETDATA_MAX_AGE_MS: int = field(default_factory=lambda: _parse_int(os.getenv("MARKETDATA_MAX_AGE_MS"), 30000) or 30000)
    MARKETDATA_MAX_AGE_MS_EXCHANGE_WS: int = field(default_factory=lambda: _parse_int(os.getenv("MARKETDATA_MAX_AGE_MS_EXCHANGE_WS"), 15000) or 15000)
    MARKETDATA_OUTLIER_MAX_PCT: float = field(default_factory=lambda: _parse_float(os.getenv("MARKETDATA_OUTLIER_MAX_PCT"), 20.0) or 20.0)
    MARKETDATA_OUTLIER_WINDOW_MS: int = field(default_factory=lambda: _parse_int(os.getenv("MARKETDATA_OUTLIER_WINDOW_MS"), 10000) or 10000)
    MARKETDATA_FAIL_CLOSED: bool = field(default_factory=lambda: _parse_bool(os.getenv("MARKETDATA_FAIL_CLOSED"), False))

    # Persistence paths
    AUDIT_DB_PATH: str | None = field(default_factory=lambda: os.getenv("AUDIT_DB_PATH"))
    IDEMPOTENCY_DB_PATH: str | None = field(default_factory=lambda: os.getenv("IDEMPOTENCY_DB_PATH"))
    EXECUTION_DB_PATH: str | None = field(default_factory=lambda: os.getenv("EXECUTION_DB_PATH"))
    INSIGHT_DB_PATH: str | None = field(default_factory=lambda: os.getenv("INSIGHT_DB_PATH"))
    STRATEGY_DB_PATH: str | None = field(default_factory=lambda: os.getenv("STRATEGY_DB_PATH"))
    PAPER_DB_PATH: str | None = field(default_factory=lambda: os.getenv("PAPER_DB_PATH"))

    # Private updates
    CEX_PRIVATE_POLL_INTERVAL_SEC: float = field(default_factory=lambda: _parse_float(os.getenv("CEX_PRIVATE_POLL_INTERVAL_SEC"), 2.0) or 2.0)

    # Observability
    READYTRADER_LOG_LEVEL: str = field(default_factory=lambda: os.getenv("READYTRADER_LOG_LEVEL", "info").strip().lower())
    READYTRADER_SERVICE_NAME: str = field(default_factory=lambda: os.getenv("READYTRADER_SERVICE_NAME", "readytrader").strip())
    READYTRADER_METRICS_NS: str = field(default_factory=lambda: os.getenv("READYTRADER_METRICS_NS", "readytrader").strip())

    # Webhooks
    DISCORD_WEBHOOK_URL: str | None = field(default_factory=lambda: os.getenv("DISCORD_WEBHOOK_URL"))
    TELEGRAM_BOT_TOKEN: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN"))
    TELEGRAM_CHAT_ID: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID"))

    # Intelligence APIs
    CRYPTOPANIC_API_KEY: str | None = field(default_factory=lambda: os.getenv("CRYPTOPANIC_API_KEY"))
    NEWSAPI_KEY: str | None = field(default_factory=lambda: os.getenv("NEWSAPI_KEY"))
    REDDIT_CLIENT_ID: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID"))
    REDDIT_CLIENT_SECRET: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET"))
    TWITTER_BEARER_TOKEN: str | None = field(default_factory=lambda: os.getenv("TWITTER_BEARER_TOKEN"))

    # Remote signer timeouts
    REMOTE_SIGNER_TIMEOUT_SEC: int = field(default_factory=lambda: _parse_int(os.getenv("REMOTE_SIGNER_TIMEOUT_SEC"), 30) or 30)
    REMOTE_SIGNER_RETRY_COUNT: int = field(default_factory=lambda: _parse_int(os.getenv("REMOTE_SIGNER_RETRY_COUNT"), 3) or 3)
    REMOTE_SIGNER_REQUIRE_TLS: bool = field(default_factory=lambda: _parse_bool(os.getenv("REMOTE_SIGNER_REQUIRE_TLS"), True))

    def __post_init__(self) -> None:
        """Validate settings after initialization."""
        self._validate()

    def _validate(self) -> None:
        """Validate all settings and emit security warnings."""
        import warnings

        errors: list[str] = []

        # Production / live fail-closed (paper MCP may still boot without JWT)
        production_live = (not self.DEV_MODE) and (self.LIVE_TRADING_ENABLED or not self.PAPER_MODE)
        if production_live:
            if not self.API_AUTH_REQUIRED:
                errors.append(
                    "API_AUTH_REQUIRED must be true when DEV_MODE=false and "
                    "(LIVE_TRADING_ENABLED=true or PAPER_MODE=false)"
                )
            if self.CORS_ALLOW_ALL:
                errors.append(
                    "CORS_ORIGINS must not be '*' when DEV_MODE=false for live/non-paper; "
                    "set explicit origins"
                )

        if not self.DEV_MODE and self.API_AUTH_REQUIRED and not self.API_JWT_SECRET:
            errors.append("API_JWT_SECRET must be set when API_AUTH_REQUIRED=true in production mode")

        if not self.DEV_MODE and self.API_AUTH_REQUIRED and self.CORS_ALLOW_ALL:
            errors.append(
                "CORS_ORIGINS should not be '*' when API_AUTH_REQUIRED=true in production mode"
            )

        # Security warnings (non-fatal but important)
        if self.DEV_MODE:
            warnings.warn(
                "DEV_MODE=true: Security restrictions relaxed. Do NOT use in production!",
                UserWarning,
                stacklevel=3,
            )

        if not self.API_AUTH_REQUIRED and not self.DEV_MODE:
            warnings.warn(
                "API_AUTH_REQUIRED=false: API endpoints are unauthenticated. "
                "api_server refuses to start without auth when DEV_MODE=false.",
                UserWarning,
                stacklevel=3,
            )

        if self.CORS_ALLOW_ALL and not self.DEV_MODE:
            warnings.warn(
                "CORS_ORIGINS='*': Accepting requests from any origin. "
                "api_server refuses wildcard CORS when DEV_MODE=false.",
                UserWarning,
                stacklevel=3,
            )

        # env_private_key is development-only — refuse for any non-paper or live-enabled path
        live_or_non_paper = (not self.PAPER_MODE) or self.LIVE_TRADING_ENABLED
        if live_or_non_paper and self.SIGNER_TYPE == SignerType.ENV_PRIVATE_KEY:
            errors.append(
                "SIGNER_TYPE=env_private_key is forbidden when PAPER_MODE=false or "
                "LIVE_TRADING_ENABLED=true; use keystore, remote, or cb_mpc_2pc"
            )

        # Live trading validations (after env_private_key ban)
        if not self.PAPER_MODE and self.LIVE_TRADING_ENABLED:
            if self.SIGNER_TYPE == SignerType.KEYSTORE and (not self.KEYSTORE_PATH or not self.KEYSTORE_PASSWORD):
                errors.append("KEYSTORE_PATH and KEYSTORE_PASSWORD required when SIGNER_TYPE=keystore")
            elif self.SIGNER_TYPE == SignerType.REMOTE and not self.SIGNER_REMOTE_URL:
                errors.append("SIGNER_REMOTE_URL required when SIGNER_TYPE=remote")
            elif self.SIGNER_TYPE == SignerType.CB_MPC_2PC and not self.MPC_SIGNER_URL:
                errors.append("MPC_SIGNER_URL required when SIGNER_TYPE=cb_mpc_2pc")

            if not self.SIGNER_POLICY_ENABLED:
                warnings.warn(
                    "SIGNER_POLICY_ENABLED=false: No signer-side guardrails. Enable for defense-in-depth in live trading.",
                    UserWarning,
                    stacklevel=3,
                )

            if not self.ALLOW_EXCHANGES and not self.ALLOW_CHAINS:
                warnings.warn(
                    "ALLOW_EXCHANGES/ALLOW_CHAINS not set: configure allowlists for production live trading.",
                    UserWarning,
                    stacklevel=3,
                )

        # Port validation
        if not (1 <= self.API_PORT <= 65535):
            errors.append(f"API_PORT must be between 1 and 65535, got {self.API_PORT}")

        if errors:
            raise SettingsValidationError("MULTIPLE", None, "; ".join(errors))

    @cached_property
    def risk_config(self) -> RiskProfileConfig:
        """Get the current risk profile configuration."""
        return RISK_PROFILES[self.RISK_PROFILE]

    @property
    def is_live_execution_allowed(self) -> bool:
        """Check if live execution is currently allowed."""
        return not self.PAPER_MODE and self.LIVE_TRADING_ENABLED and not self.TRADING_HALTED

    def to_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary (redacting secrets)."""
        result: dict[str, Any] = {}
        for key in dir(self):
            if key.startswith("_") or key.isupper() is False:
                continue
            value = getattr(self, key)
            # Redact sensitive values
            if any(s in key.upper() for s in ["SECRET", "PASSWORD", "KEY", "TOKEN"]):
                result[key] = "***REDACTED***" if value else None
            elif isinstance(value, frozenset):
                result[key] = list(value)
            elif isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result


# Global settings instance
settings = Settings()


# Backwards compatibility - expose string values for legacy code
# These should be migrated to use the Settings class directly
def get_execution_approval_mode() -> str:
    """Get execution approval mode as string (legacy compatibility)."""
    return settings.EXECUTION_APPROVAL_MODE.value


def set_execution_approval_mode(mode: str) -> None:
    """Set execution approval mode (for approval lock pattern - legacy)."""
    # This is a mutable escape hatch for the approval lock pattern
    # We update the underlying object but this is not thread-safe
    object.__setattr__(settings, "EXECUTION_APPROVAL_MODE", ApprovalMode(mode))
