"""
ReadyTrader-Crypto Error Taxonomy

This module provides a standardized error handling framework across all modules.
All errors inherit from ReadyTraderError and follow a consistent structure.

Error Categories:
- Configuration Errors (1xx): Invalid settings, missing credentials
- Policy Errors (2xx): Allowlist violations, limit breaches
- Execution Errors (3xx): Trade execution failures
- Market Data Errors (4xx): Data fetch failures, stale data
- Network Errors (5xx): Connectivity issues, timeouts
- Authentication Errors (6xx): API key issues, permission denied
- Validation Errors (7xx): Input validation failures
- System Errors (8xx): Internal errors, resource exhaustion
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import ccxt


class ErrorCategory(Enum):
    """Error category enumeration for classification."""

    CONFIGURATION = "configuration"
    POLICY = "policy"
    EXECUTION = "execution"
    MARKET_DATA = "market_data"
    NETWORK = "network"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    SYSTEM = "system"


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"  # Informational, operation may continue
    MEDIUM = "medium"  # Warning, operation degraded
    HIGH = "high"  # Error, operation failed
    CRITICAL = "critical"  # Critical, system may be compromised


@dataclass
class ReadyTraderError(Exception):
    """
    Base exception class for all ReadyTrader-Crypto errors.

    Provides a consistent structure for error handling across all modules.

    Attributes:
        code: Unique error code (e.g., "POLICY_001")
        message: Human-readable error message
        category: Error category for classification
        severity: Error severity level
        data: Additional context data
        suggestion: Optional remediation suggestion
        doc_ref: Optional documentation reference
    """

    code: str
    message: str
    category: ErrorCategory = ErrorCategory.SYSTEM
    severity: ErrorSeverity = ErrorSeverity.HIGH
    data: Dict[str, Any] = field(default_factory=dict)
    suggestion: Optional[str] = None
    doc_ref: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:
        return f"ReadyTraderError(code={self.code!r}, message={self.message!r})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for JSON serialization."""
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "data": self.data,
            "suggestion": self.suggestion,
            "doc_ref": self.doc_ref,
        }

    def to_json(self) -> str:
        """Convert error to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


# =============================================================================
# Configuration Errors (1xx)
# =============================================================================


@dataclass
class ConfigurationError(ReadyTraderError):
    """Configuration-related errors."""

    category: ErrorCategory = ErrorCategory.CONFIGURATION


class MissingCredentialsError(ConfigurationError):
    """Missing API credentials."""

    def __init__(self, credential_name: str, env_vars: list[str]):
        super().__init__(
            code="CONFIG_101",
            message=f"Missing required credential: {credential_name}",
            severity=ErrorSeverity.HIGH,
            data={"credential": credential_name, "env_vars": env_vars},
            suggestion=f"Set one of these environment variables: {', '.join(env_vars)}",
            doc_ref="docs/CUSTODY.md#credentials",
        )


class InvalidConfigurationError(ConfigurationError):
    """Invalid configuration value."""

    def __init__(self, config_name: str, value: Any, valid_values: Optional[list] = None):
        super().__init__(
            code="CONFIG_102",
            message=f"Invalid configuration value for {config_name}: {value}",
            severity=ErrorSeverity.HIGH,
            data={"config": config_name, "value": value, "valid_values": valid_values},
            suggestion=f"Valid values are: {valid_values}" if valid_values else "Check documentation for valid values",
            doc_ref="env.example",
        )


class SignerConfigurationError(ConfigurationError):
    """Signer configuration error."""

    def __init__(self, signer_type: str, reason: str):
        super().__init__(
            code="CONFIG_103",
            message=f"Signer configuration error for {signer_type}: {reason}",
            severity=ErrorSeverity.CRITICAL,
            data={"signer_type": signer_type, "reason": reason},
            suggestion="Check SIGNER_TYPE and related environment variables",
            doc_ref="docs/CUSTODY.md#signers",
        )


# =============================================================================
# Policy Errors (2xx)
# =============================================================================


@dataclass
class PolicyError(ReadyTraderError):
    """Policy enforcement errors."""

    category: ErrorCategory = ErrorCategory.POLICY


class ChainNotAllowedError(PolicyError):
    """Chain not in allowlist."""

    def __init__(self, chain: str, allowed_chains: list[str]):
        super().__init__(
            code="POLICY_201",
            message=f"Chain '{chain}' is not allowlisted",
            severity=ErrorSeverity.HIGH,
            data={"chain": chain, "allowed_chains": allowed_chains},
            suggestion=f"Add '{chain}' to ALLOW_CHAINS or use an allowed chain: {allowed_chains}",
            doc_ref="docs/THREAT_MODEL.md#policy-engine",
        )


class TokenNotAllowedError(PolicyError):
    """Token not in allowlist."""

    def __init__(self, token: str, allowed_tokens: list[str]):
        super().__init__(
            code="POLICY_202",
            message=f"Token '{token}' is not allowlisted",
            severity=ErrorSeverity.HIGH,
            data={"token": token, "allowed_tokens": allowed_tokens},
            suggestion=f"Add '{token}' to ALLOW_TOKENS or use an allowed token",
            doc_ref="docs/THREAT_MODEL.md#policy-engine",
        )


class ExchangeNotAllowedError(PolicyError):
    """Exchange not in allowlist."""

    def __init__(self, exchange: str, allowed_exchanges: list[str]):
        super().__init__(
            code="POLICY_203",
            message=f"Exchange '{exchange}' is not allowlisted",
            severity=ErrorSeverity.HIGH,
            data={"exchange": exchange, "allowed_exchanges": allowed_exchanges},
            suggestion=f"Add '{exchange}' to ALLOW_EXCHANGES",
            doc_ref="docs/EXCHANGES.md",
        )


class AmountExceedsLimitError(PolicyError):
    """Trade amount exceeds configured limit."""

    def __init__(self, amount: float, limit: float, limit_name: str):
        super().__init__(
            code="POLICY_204",
            message=f"Amount {amount} exceeds {limit_name} limit of {limit}",
            severity=ErrorSeverity.HIGH,
            data={"amount": amount, "limit": limit, "limit_name": limit_name},
            suggestion=f"Reduce trade amount or increase {limit_name}",
            doc_ref="docs/THREAT_MODEL.md#risk-limits",
        )


class SignerAddressNotAllowedError(PolicyError):
    """Signer address not in allowlist."""

    def __init__(self, address: str, allowed_addresses: list[str]):
        super().__init__(
            code="POLICY_205",
            message=f"Signer address '{address}' is not allowlisted",
            severity=ErrorSeverity.CRITICAL,
            data={"address": address, "allowed_addresses": allowed_addresses},
            suggestion="Verify ALLOW_SIGNER_ADDRESSES matches your configured signer",
            doc_ref="docs/THREAT_MODEL.md#wrong-signer",
        )


class RouterNotAllowedError(PolicyError):
    """Router/spender address not in allowlist."""

    def __init__(self, router: str, chain: str, allowed_routers: list[str]):
        super().__init__(
            code="POLICY_206",
            message=f"Router '{router}' on '{chain}' is not allowlisted",
            severity=ErrorSeverity.CRITICAL,
            data={"router": router, "chain": chain, "allowed_routers": allowed_routers},
            suggestion="Add the router to ALLOW_ROUTERS or ALLOW_ROUTERS_{CHAIN}",
            doc_ref="docs/THREAT_MODEL.md#router-allowlist",
        )


# =============================================================================
# Execution Errors (3xx)
# =============================================================================


@dataclass
class ExecutionError(ReadyTraderError):
    """Trade execution errors."""

    category: ErrorCategory = ErrorCategory.EXECUTION


class ExecutionModeBlockedError(ExecutionError):
    """Execution blocked by mode setting."""

    def __init__(self, venue: str, execution_mode: str):
        super().__init__(
            code="EXEC_301",
            message=f"Execution on '{venue}' blocked by EXECUTION_MODE={execution_mode}",
            severity=ErrorSeverity.MEDIUM,
            data={"venue": venue, "execution_mode": execution_mode},
            suggestion=f"Change EXECUTION_MODE to 'hybrid' or '{venue}' to enable",
            doc_ref="docs/ARCHITECTURE.md#execution-layer",
        )


class LiveTradingDisabledError(ExecutionError):
    """Live trading is disabled."""

    def __init__(self) -> None:
        super().__init__(
            code="EXEC_302",
            message="Live trading is disabled (LIVE_TRADING_ENABLED=false)",
            severity=ErrorSeverity.HIGH,
            data={},
            suggestion="Set LIVE_TRADING_ENABLED=true to enable live trading",
            doc_ref="docs/THREAT_MODEL.md#live-trading",
        )


class TradingHaltedError(ExecutionError):
    """Trading is halted by kill switch."""

    def __init__(self) -> None:
        super().__init__(
            code="EXEC_303",
            message="Trading is halted (TRADING_HALTED=true)",
            severity=ErrorSeverity.CRITICAL,
            data={},
            suggestion="Set TRADING_HALTED=false to resume trading",
            doc_ref="docs/THREAT_MODEL.md#kill-switch",
        )


class OrderPlacementError(ExecutionError):
    """Order placement failed."""

    def __init__(self, exchange: str, symbol: str, reason: str):
        super().__init__(
            code="EXEC_304",
            message=f"Order placement failed on {exchange} for {symbol}: {reason}",
            severity=ErrorSeverity.HIGH,
            data={"exchange": exchange, "symbol": symbol, "reason": reason},
            suggestion="Check order parameters, balance, and exchange status",
            doc_ref="docs/ERRORS.md#order-errors",
        )


class InsufficientBalanceError(ExecutionError):
    """Insufficient balance for trade."""

    def __init__(self, asset: str, required: float, available: float):
        super().__init__(
            code="EXEC_305",
            message=f"Insufficient {asset} balance: required {required}, available {available}",
            severity=ErrorSeverity.HIGH,
            data={"asset": asset, "required": required, "available": available},
            suggestion="Deposit more funds or reduce order size",
            doc_ref="docs/ERRORS.md#balance-errors",
        )


class ApprovalRequiredError(ExecutionError):
    """Trade requires manual approval."""

    def __init__(self, request_id: str, expires_at: int):
        super().__init__(
            code="EXEC_306",
            message=f"Trade requires approval (request_id: {request_id})",
            severity=ErrorSeverity.LOW,
            data={"request_id": request_id, "expires_at": expires_at},
            suggestion="Approve the trade in the Web UI or via API",
            doc_ref="docs/ARCHITECTURE.md#approval-gate",
        )


class IdempotencyConflictError(ExecutionError):
    """Idempotency key already used."""

    def __init__(self, idempotency_key: str, previous_result: Dict[str, Any]):
        super().__init__(
            code="EXEC_307",
            message=f"Idempotency key '{idempotency_key}' already used",
            severity=ErrorSeverity.LOW,
            data={"idempotency_key": idempotency_key, "previous_result": previous_result},
            suggestion="Use a unique idempotency key for new trades",
            doc_ref="docs/THREAT_MODEL.md#replay-protection",
        )


class ProposalStateError(ExecutionError):
    """An approval proposal cannot be confirmed in its current state."""

    # reason -> (code, HTTP status, suggestion). Reasons come from execution_store.ProposalError.
    REASONS = {
        "executed": ("EXEC_308", 409, "This proposal was already executed; nothing further will happen."),
        "unknown": ("EXEC_309", 404, "The proposal does not exist in this server process; ask the agent to propose again."),
        "expired": ("EXEC_310", 410, "Proposals expire quickly by design; ask the agent to propose again."),
        "cancelled": ("EXEC_311", 409, "This proposal was rejected earlier and cannot be revived."),
        "already_confirmed": ("EXEC_311", 409, "This proposal was already approved; approvals are single-use."),
        "malformed": ("EXEC_312", 422, "The proposal payload is incomplete; ask the agent to propose again."),
    }

    def __init__(self, reason: str, request_id: str, message: str | None = None):
        code, status, suggestion = self.REASONS.get(reason, ("EXEC_311", 409, None))
        super().__init__(
            code=code,
            message=message or f"Proposal {request_id} cannot be approved ({reason})",
            severity=ErrorSeverity.LOW,
            data={"request_id": request_id, "reason": reason},
            suggestion=suggestion,
            doc_ref="docs/ARCHITECTURE.md#approval-gate",
        )
        self.http_status = status


# =============================================================================
# Market Data Errors (4xx)
# =============================================================================


@dataclass
class MarketDataError(ReadyTraderError):
    """Market data errors."""

    category: ErrorCategory = ErrorCategory.MARKET_DATA


class StaleDataError(MarketDataError):
    """Market data is stale."""

    def __init__(self, symbol: str, age_ms: int, max_age_ms: int):
        super().__init__(
            code="DATA_401",
            message=f"Market data for {symbol} is stale ({age_ms}ms > {max_age_ms}ms max)",
            severity=ErrorSeverity.HIGH,
            data={"symbol": symbol, "age_ms": age_ms, "max_age_ms": max_age_ms},
            suggestion="Check data source connectivity or adjust MARKETDATA_MAX_AGE_MS",
            doc_ref="docs/MARKETDATA.md#freshness",
        )


class DataFetchError(MarketDataError):
    """Failed to fetch market data."""

    def __init__(self, symbol: str, source: str, reason: str):
        super().__init__(
            code="DATA_402",
            message=f"Failed to fetch data for {symbol} from {source}: {reason}",
            severity=ErrorSeverity.HIGH,
            data={"symbol": symbol, "source": source, "reason": reason},
            suggestion="Check network connectivity and exchange status",
            doc_ref="docs/MARKETDATA.md#providers",
        )


class OutlierDataError(MarketDataError):
    """Outlier data detected."""

    def __init__(self, symbol: str, value: float, expected_range: tuple):
        super().__init__(
            code="DATA_403",
            message=f"Outlier price detected for {symbol}: {value} outside {expected_range}",
            severity=ErrorSeverity.HIGH,
            data={"symbol": symbol, "value": value, "expected_range": expected_range},
            suggestion="Data may be corrupted; verify with alternative source",
            doc_ref="docs/MARKETDATA.md#outlier-detection",
        )


class NoDataSourceError(MarketDataError):
    """No data source available."""

    def __init__(self, symbol: str):
        super().__init__(
            code="DATA_404",
            message=f"No data source available for {symbol}",
            severity=ErrorSeverity.HIGH,
            data={"symbol": symbol},
            suggestion="Configure market data providers in MARKETDATA_EXCHANGES",
            doc_ref="docs/MARKETDATA.md#configuration",
        )


# =============================================================================
# Network Errors (5xx)
# =============================================================================


@dataclass
class NetworkError(ReadyTraderError):
    """Network connectivity errors."""

    category: ErrorCategory = ErrorCategory.NETWORK


class ConnectionTimeoutError(NetworkError):
    """Connection timed out."""

    def __init__(self, endpoint: str, timeout_sec: float):
        super().__init__(
            code="NET_501",
            message=f"Connection to {endpoint} timed out after {timeout_sec}s",
            severity=ErrorSeverity.HIGH,
            data={"endpoint": endpoint, "timeout_sec": timeout_sec},
            suggestion="Check network connectivity and retry",
            doc_ref="docs/ERRORS.md#network-errors",
        )


class WebSocketDisconnectedError(NetworkError):
    """WebSocket connection lost."""

    def __init__(self, exchange: str, reason: str):
        super().__init__(
            code="NET_502",
            message=f"WebSocket disconnected from {exchange}: {reason}",
            severity=ErrorSeverity.MEDIUM,
            data={"exchange": exchange, "reason": reason},
            suggestion="Connection will auto-reconnect; check exchange status if persistent",
            doc_ref="docs/MARKETDATA.md#websocket",
        )


class RPCError(NetworkError):
    """JSON-RPC error."""

    def __init__(self, chain: str, method: str, error_code: int, error_message: str):
        super().__init__(
            code="NET_503",
            message=f"RPC error on {chain} for {method}: [{error_code}] {error_message}",
            severity=ErrorSeverity.HIGH,
            data={"chain": chain, "method": method, "error_code": error_code, "error_message": error_message},
            suggestion="Check RPC endpoint status and gas settings",
            doc_ref="docs/ERRORS.md#rpc-errors",
        )


# =============================================================================
# Authentication Errors (6xx)
# =============================================================================


@dataclass
class AuthenticationError(ReadyTraderError):
    """Authentication and authorization errors."""

    category: ErrorCategory = ErrorCategory.AUTHENTICATION


class InvalidAPIKeyError(AuthenticationError):
    """Invalid API key."""

    def __init__(self, exchange: str):
        super().__init__(
            code="AUTH_601",
            message=f"Invalid API key for {exchange}",
            severity=ErrorSeverity.CRITICAL,
            data={"exchange": exchange},
            suggestion="Verify API key and secret are correctly configured",
            doc_ref="docs/CUSTODY.md#api-keys",
        )


class PermissionDeniedError(AuthenticationError):
    """Permission denied for operation."""

    def __init__(self, exchange: str, operation: str):
        super().__init__(
            code="AUTH_602",
            message=f"Permission denied for {operation} on {exchange}",
            severity=ErrorSeverity.HIGH,
            data={"exchange": exchange, "operation": operation},
            suggestion="Check API key permissions and IP whitelist",
            doc_ref="docs/CUSTODY.md#api-keys",
        )


class ApprovalDeniedError(AuthenticationError):
    """The caller may not approve this trade proposal."""

    def __init__(self, request_id: str, reason: str):
        super().__init__(
            code="AUTH_604",
            message=f"Not allowed to approve proposal {request_id}: {reason}",
            severity=ErrorSeverity.HIGH,
            data={"request_id": request_id, "reason": reason},
            suggestion="Sign in to the dashboard as an admin, or supply the proposal's confirm_token",
            doc_ref="docs/ARCHITECTURE.md#approval-gate",
        )


class SignatureVerificationError(AuthenticationError):
    """Signature verification failed."""

    def __init__(self, reason: str):
        super().__init__(
            code="AUTH_603",
            message=f"Signature verification failed: {reason}",
            severity=ErrorSeverity.CRITICAL,
            data={"reason": reason},
            suggestion="Check signer configuration and private key",
            doc_ref="docs/CUSTODY.md#signers",
        )


# =============================================================================
# Validation Errors (7xx)
# =============================================================================


@dataclass
class ValidationError(ReadyTraderError):
    """Input validation errors."""

    category: ErrorCategory = ErrorCategory.VALIDATION


class InvalidSymbolError(ValidationError):
    """Invalid trading symbol."""

    def __init__(self, symbol: str, exchange: str):
        super().__init__(
            code="VAL_701",
            message=f"Invalid symbol '{symbol}' for {exchange}",
            severity=ErrorSeverity.MEDIUM,
            data={"symbol": symbol, "exchange": exchange},
            suggestion="Check symbol format (e.g., 'BTC/USDT') and exchange listings",
            doc_ref="docs/EXCHANGES.md",
        )


class InvalidAmountError(ValidationError):
    """Invalid order amount."""

    def __init__(self, amount: float, reason: str):
        super().__init__(
            code="VAL_702",
            message=f"Invalid amount {amount}: {reason}",
            severity=ErrorSeverity.MEDIUM,
            data={"amount": amount, "reason": reason},
            suggestion="Amount must be positive and within exchange limits",
            doc_ref="docs/ERRORS.md#validation",
        )


class InvalidPriceError(ValidationError):
    """Invalid order price."""

    def __init__(self, price: float, reason: str):
        super().__init__(
            code="VAL_703",
            message=f"Invalid price {price}: {reason}",
            severity=ErrorSeverity.MEDIUM,
            data={"price": price, "reason": reason},
            suggestion="Price must be positive for limit orders",
            doc_ref="docs/ERRORS.md#validation",
        )


class InvalidAddressError(ValidationError):
    """Invalid blockchain address."""

    def __init__(self, address: str, expected_format: str):
        super().__init__(
            code="VAL_704",
            message=f"Invalid address '{address}': expected {expected_format}",
            severity=ErrorSeverity.MEDIUM,
            data={"address": address, "expected_format": expected_format},
            suggestion="Verify address format and checksum",
            doc_ref="docs/ERRORS.md#validation",
        )


# =============================================================================
# System Errors (8xx)
# =============================================================================


@dataclass
class SystemError(ReadyTraderError):
    """Internal system errors."""

    category: ErrorCategory = ErrorCategory.SYSTEM


class RateLimitError(SystemError):
    """Rate limit exceeded."""

    def __init__(self, key: str, limit: int, window_seconds: int, current_count: int):
        super().__init__(
            code="SYS_801",
            message=f"Rate limit exceeded for {key}: {current_count}/{limit} per {window_seconds}s",
            severity=ErrorSeverity.MEDIUM,
            data={"key": key, "limit": limit, "window_seconds": window_seconds, "count": current_count},
            suggestion="Wait before retrying or reduce request frequency",
            doc_ref="docs/ERRORS.md#rate-limiting",
        )


class ResourceExhaustedError(SystemError):
    """Resource exhausted."""

    def __init__(self, resource: str, limit: str):
        super().__init__(
            code="SYS_802",
            message=f"Resource exhausted: {resource} (limit: {limit})",
            severity=ErrorSeverity.CRITICAL,
            data={"resource": resource, "limit": limit},
            suggestion="Scale resources or reduce load",
            doc_ref="docs/RUNBOOK.md",
        )


class InternalError(SystemError):
    """Internal system error."""

    def __init__(self, component: str, reason: str):
        super().__init__(
            code="SYS_803",
            message=f"Internal error in {component}: {reason}",
            severity=ErrorSeverity.CRITICAL,
            data={"component": component, "reason": reason},
            suggestion="Check logs and report if persistent",
            doc_ref="docs/RUNBOOK.md",
        )


# =============================================================================
# Risk Management Errors
# =============================================================================


@dataclass
class RiskError(ReadyTraderError):
    """Risk management errors."""

    category: ErrorCategory = ErrorCategory.POLICY


class PositionSizeTooLargeError(RiskError):
    """Position size exceeds limit."""

    def __init__(self, position_pct: float, max_pct: float):
        super().__init__(
            code="RISK_901",
            message=f"Position size too large ({position_pct:.1%} > {max_pct:.0%} max)",
            severity=ErrorSeverity.HIGH,
            data={"position_pct": position_pct, "max_pct": max_pct},
            suggestion="Reduce position size to comply with risk limits",
            doc_ref="docs/ARCHITECTURE.md#risk-guardian",
        )


class DailyLossLimitError(RiskError):
    """Daily loss limit exceeded."""

    def __init__(self, daily_loss_pct: float, limit_pct: float):
        super().__init__(
            code="RISK_902",
            message=f"Daily loss limit hit ({daily_loss_pct:.1%}). Trading halted for buys.",
            severity=ErrorSeverity.HIGH,
            data={"daily_loss_pct": daily_loss_pct, "limit_pct": limit_pct},
            suggestion="Wait for next trading day or review strategy",
            doc_ref="docs/ARCHITECTURE.md#risk-guardian",
        )


class MaxDrawdownError(RiskError):
    """Maximum drawdown exceeded."""

    def __init__(self, drawdown_pct: float, limit_pct: float):
        super().__init__(
            code="RISK_903",
            message=f"Max drawdown limit hit ({drawdown_pct:.1%}). Trading halted for buys.",
            severity=ErrorSeverity.CRITICAL,
            data={"drawdown_pct": drawdown_pct, "limit_pct": limit_pct},
            suggestion="Review portfolio and risk management settings",
            doc_ref="docs/ARCHITECTURE.md#risk-guardian",
        )


class FallingKnifeProtectionError(RiskError):
    """Falling knife protection triggered."""

    def __init__(self, sentiment_score: float, threshold: float):
        super().__init__(
            code="RISK_904",
            message=f"Falling knife protection: BUY blocked (sentiment {sentiment_score:.2f} < {threshold})",
            severity=ErrorSeverity.MEDIUM,
            data={"sentiment_score": sentiment_score, "threshold": threshold},
            suggestion="Wait for sentiment to improve before buying",
            doc_ref="docs/ARCHITECTURE.md#risk-guardian",
        )


# =============================================================================
# Legacy Support: AppError compatibility
# =============================================================================


@dataclass
class AppError(ReadyTraderError):
    """
    Legacy error class for backward compatibility.

    Deprecated: Use specific error classes instead.
    """

    def __init__(self, code: str, message: str, data: Dict[str, Any] | None = None):
        super().__init__(code=code, message=message, data=data or {})


# =============================================================================
# Exception Classification Utility
# =============================================================================


def classify_exception(e: Exception) -> ReadyTraderError:
    """
    Map common CCXT / network issues into standardized error classes.

    This function converts third-party exceptions into ReadyTraderError
    instances for consistent error handling.

    Args:
        e: The exception to classify

    Returns:
        A ReadyTraderError instance with appropriate error code
    """
    # Already a ReadyTraderError
    if isinstance(e, ReadyTraderError):
        return e

    # CCXT Authentication Errors
    if isinstance(e, ccxt.AuthenticationError):
        return AuthenticationError(code="AUTH_601", message=str(e), data={"original_type": type(e).__name__})

    if isinstance(e, ccxt.PermissionDenied):
        return PermissionDeniedError(exchange="unknown", operation="unknown")

    # CCXT Network Errors
    if isinstance(e, ccxt.NetworkError):
        return NetworkError(code="NET_501", message=str(e), data={"original_type": type(e).__name__})

    if isinstance(e, ccxt.ExchangeNotAvailable):
        return NetworkError(code="NET_502", message=f"Exchange not available: {e}", data={"original_type": type(e).__name__})

    # CCXT Rate Limiting
    if isinstance(e, ccxt.RateLimitExceeded):
        return RateLimitError(key="exchange", limit=0, window_seconds=60, current_count=0)

    # CCXT Validation Errors
    if isinstance(e, ccxt.BadSymbol):
        return InvalidSymbolError(symbol="unknown", exchange="unknown")

    # CCXT Exchange Errors
    if isinstance(e, ccxt.ExchangeError):
        return ExecutionError(code="EXEC_304", message=str(e), data={"original_type": type(e).__name__})

    # Generic fallback
    return InternalError(component="unknown", reason=str(e))


def json_error_response(error: ReadyTraderError) -> Dict[str, Any]:
    """
    Convert a ReadyTraderError to a JSON-compatible error response.

    Args:
        error: The error to convert

    Returns:
        A dictionary suitable for JSON serialization
    """
    return {"ok": False, "error": error.to_dict()}


def json_ok_response(data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Create a success response.

    Args:
        data: Optional response data

    Returns:
        A dictionary suitable for JSON serialization
    """
    return {"ok": True, "data": data or {}}
