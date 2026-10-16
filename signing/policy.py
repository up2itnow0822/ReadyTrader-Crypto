from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from .base import SignedTx, Signer


@dataclass
class SignerPolicyViolation(Exception):
    code: str
    message: str
    data: Dict[str, Any]


def _parse_csv_set(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    return {v.strip().lower() for v in value.split(",") if v.strip()}


def _parse_int_set(value: Optional[str]) -> Set[int]:
    out: Set[int] = set()
    if not value:
        return out
    for part in value.split(","):
        s = part.strip()
        if not s:
            continue
        # Support decimal and 0x-prefixed hex.
        is_hex = s.lower().startswith("0x") and all(c in "0123456789abcdef" for c in s[2:].lower())
        is_dec = s.isdigit() or (s.startswith("-") and s[1:].isdigit())
        if not (is_hex or is_dec):
            continue
        out.add(int(s, 0))
    return out


def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw, 0)
    except Exception:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class SignerPolicyConfig:
    allowed_chain_ids: Set[int]
    allowed_to_addresses: Set[str]
    max_value_wei: Optional[int]
    max_gas: Optional[int]
    max_gas_price_wei: Optional[int]
    max_data_bytes: Optional[int]
    disallow_contract_creation: bool


def policy_config_from_env() -> SignerPolicyConfig:
    """
    Policy config for signer-side enforcement (defense in depth).

    All rules are opt-in; defaults are permissive unless env vars are set.
    """
    return SignerPolicyConfig(
        allowed_chain_ids=_parse_int_set(os.getenv("SIGNER_ALLOWED_CHAIN_IDS")),
        allowed_to_addresses=_parse_csv_set(os.getenv("SIGNER_ALLOWED_TO_ADDRESSES")),
        max_value_wei=_env_int("SIGNER_MAX_VALUE_WEI", None),
        max_gas=_env_int("SIGNER_MAX_GAS", None),
        max_gas_price_wei=_env_int("SIGNER_MAX_GAS_PRICE_WEI", None),
        max_data_bytes=_env_int("SIGNER_MAX_DATA_BYTES", None),
        disallow_contract_creation=_env_bool("SIGNER_DISALLOW_CONTRACT_CREATION", False),
    )


def _hex_data_len(data_hex: Any) -> Optional[int]:
    if data_hex is None:
        return None
    s = str(data_hex).strip()
    if s.startswith("0x"):
        s = s[2:]
    # bytes length
    return len(s) // 2


def transaction_uint(value: Any, field: str) -> int:
    """Parse EVM integer quantities without truncation or permissive fallback."""
    try:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError
        number = int(value, 16 if value.startswith(("0x", "0X")) else 10) if isinstance(value, str) else value
        if number < 0 or number >= 2**256:
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise SignerPolicyViolation("invalid_transaction_quantity", f"{field} must be a nonnegative EVM integer.", {"field": field}) from None


def validate_transaction_fees(tx: Dict[str, Any], *, max_gas_price_wei: int | None = None) -> Dict[str, Any]:
    """Normalize and validate legacy/type-2 fee semantics before policy or hashing.

    Fee-less partial transactions are retained for existing signer callers, but when a
    cap is configured the fee must be explicit. Unknown typed envelopes fail closed.
    """
    out = dict(tx)
    dynamic = "maxFeePerGas" in tx or "maxPriorityFeePerGas" in tx
    kind = transaction_uint(tx["type"], "type") if "type" in tx else (2 if dynamic else 0)
    if kind not in (0, 1, 2):
        raise SignerPolicyViolation("unsupported_transaction_type", "Unsupported transaction fee semantics.", {})
    if "type" in tx:
        out["type"] = kind
    if dynamic or kind == 2:
        if kind != 2 or "gasPrice" in tx or not all(k in tx for k in ("maxFeePerGas", "maxPriorityFeePerGas")):
            raise SignerPolicyViolation("invalid_transaction_fees", "Type-2 fees require both caps and no gasPrice.", {})
        out["type"] = 2
        for field in ("maxFeePerGas", "maxPriorityFeePerGas"):
            out[field] = transaction_uint(tx[field], field)
        if out["maxPriorityFeePerGas"] > out["maxFeePerGas"]:
            raise SignerPolicyViolation("invalid_transaction_fees", "Priority fee exceeds maximum fee.", {})
        prices = (out["maxFeePerGas"], out["maxPriorityFeePerGas"])
    elif "gasPrice" in tx:
        out["gasPrice"] = transaction_uint(tx["gasPrice"], "gasPrice")
        prices = (out["gasPrice"],)
    elif max_gas_price_wei is not None:
        raise SignerPolicyViolation("invalid_transaction_fees", "Explicit transaction fees are required by the gas-price limit.", {})
    else:
        prices = ()
    if max_gas_price_wei is not None and any(p > max_gas_price_wei for p in prices):
        raise SignerPolicyViolation("gas_price_too_large", "Transaction worst-case gas price exceeds policy limit.", {"max_gas_price_wei": max_gas_price_wei})
    return out


def validate_tx_against_policy(tx: Dict[str, Any], *, chain_id: int | None, cfg: SignerPolicyConfig) -> None:
    if cfg.disallow_contract_creation and not tx.get("to"):
        raise SignerPolicyViolation(
            "contract_creation_not_allowed",
            "Contract creation tx (missing 'to') is disallowed by signer policy.",
            {},
        )

    if cfg.allowed_chain_ids and chain_id is not None and int(chain_id) not in cfg.allowed_chain_ids:
        raise SignerPolicyViolation(
            "chain_id_not_allowed",
            "Transaction chain_id is not allowlisted by signer policy.",
            {"chain_id": int(chain_id), "allowed_chain_ids": sorted(cfg.allowed_chain_ids)},
        )

    to = tx.get("to")
    if cfg.allowed_to_addresses and to is not None:
        if str(to).strip().lower() not in cfg.allowed_to_addresses:
            raise SignerPolicyViolation(
                "to_not_allowed",
                "Transaction recipient/contract address is not allowlisted by signer policy.",
                {"to": str(to), "allowed_to_addresses": sorted(cfg.allowed_to_addresses)},
            )

    try:
        value = int(tx.get("value") or 0)
    except Exception:
        value = 0
    if cfg.max_value_wei is not None and value > int(cfg.max_value_wei):
        raise SignerPolicyViolation(
            "value_too_large",
            "Transaction value exceeds signer policy limit.",
            {"value_wei": value, "max_value_wei": int(cfg.max_value_wei)},
        )

    if cfg.max_gas is not None:
        try:
            gas = int(tx.get("gas") or 0)
        except Exception:
            gas = 0
        if gas and gas > int(cfg.max_gas):
            raise SignerPolicyViolation(
                "gas_too_large",
                "Transaction gas exceeds signer policy limit.",
                {"gas": gas, "max_gas": int(cfg.max_gas)},
            )

    validate_transaction_fees(tx, max_gas_price_wei=cfg.max_gas_price_wei)

    if cfg.max_data_bytes is not None:
        dl = _hex_data_len(tx.get("data"))
        if dl is not None and dl > int(cfg.max_data_bytes):
            raise SignerPolicyViolation(
                "data_too_large",
                "Transaction calldata exceeds signer policy limit.",
                {"data_bytes": dl, "max_data_bytes": int(cfg.max_data_bytes)},
            )


class PolicyEnforcedSigner(Signer):
    """
    Wrap a signer with local policy enforcement (defense in depth).
    """

    def __init__(self, inner: Signer, cfg: SignerPolicyConfig) -> None:
        self._inner = inner
        self._cfg = cfg

    def get_address(self) -> str:
        return self._inner.get_address()

    def sign_transaction(self, tx: Dict[str, Any], *, chain_id: int | None = None) -> SignedTx:
        tx = validate_transaction_fees(tx, max_gas_price_wei=self._cfg.max_gas_price_wei)
        validate_tx_against_policy(tx, chain_id=chain_id, cfg=self._cfg)
        return self._inner.sign_transaction(tx, chain_id=chain_id)


def maybe_wrap_signer(signer: Signer) -> Signer:
    """
    Wrap signer with policy if any signer policy env vars are set.
    """
    cfg = policy_config_from_env()
    enabled = _env_bool("SIGNER_POLICY_ENABLED", False)
    has_rules = bool(
        cfg.allowed_chain_ids
        or cfg.allowed_to_addresses
        or cfg.max_value_wei is not None
        or cfg.max_gas is not None
        or cfg.max_gas_price_wei is not None
        or cfg.max_data_bytes is not None
        or cfg.disallow_contract_creation
    )
    if not (enabled or has_rules):
        return signer
    return PolicyEnforcedSigner(signer, cfg)
