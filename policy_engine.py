from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from signing.policy import SignerPolicyViolation, validate_transaction_fees


@dataclass
class PolicyError(Exception):
    code: str
    message: str
    data: Dict[str, Any]


def _parse_csv_set(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    return {v.strip().lower() for v in value.split(",") if v.strip()}


def _env_float(name: str, default: Optional[float] = None) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_int_set(value: Optional[str]) -> Set[int]:
    out: Set[int] = set()
    if not value:
        return out
    for part in value.split(","):
        s = part.strip()
        if not s:
            continue
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


class PolicyEngine:
    """
    Phase 1 policy enforcement for live execution.

    Defaults are permissive (no allowlists) unless env vars are set.

    Philosophy:
    - The policy engine is a deterministic “deny layer” (it never forces trades).
    - If an allowlist/limit env var is set, it is enforced strictly.
    - If unset, the rule is not applied (so dev/demo works out of the box).
    """

    def __init__(self) -> None:
        # Intentionally stateless in Phase 1
        pass

    def validate_insight_backing(self, *, symbol: str, insight_id: str, insights: List[Any]) -> float:
        """
        [PHASE 3] Verify that a trade is backed by a high-confidence insight.
        Returns the confidence score if it matches the symbol and is not expired.
        """
        if not insight_id:
            return 0.0

        sym = symbol.strip().upper()
        for ins in insights:
            # Note: ins is a MarketInsight-like object (or dict from vars(ins))
            ins_id = getattr(ins, "insight_id", None) or ins.get("insight_id")
            ins_sym = getattr(ins, "symbol", None) or ins.get("symbol")
            if ins_id == insight_id and ins_sym == sym:
                conf = getattr(ins, "confidence", 0.0) or ins.get("confidence", 0.0)
                return float(conf)

        raise PolicyError(
            code="insight_not_found", message=f"No valid insight found for {symbol} with ID {insight_id}", data={"symbol": symbol, "insight_id": insight_id}
        )

    def validate_swap(
        self,
        *,
        chain: str,
        from_token: str,
        to_token: str,
        amount: float,
        overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        chain_l = chain.strip().lower()
        from_l = from_token.strip().lower()
        to_l = to_token.strip().lower()

        allow_chains = _parse_csv_set(os.getenv("ALLOW_CHAINS"))
        if allow_chains and chain_l not in allow_chains:
            raise PolicyError(
                code="chain_not_allowed",
                message=f"Chain '{chain}' is not allowlisted.",
                data={"chain": chain, "allow_chains": sorted(allow_chains)},
            )

        allow_tokens = _parse_csv_set(os.getenv("ALLOW_TOKENS"))
        if allow_tokens:
            if from_l not in allow_tokens or to_l not in allow_tokens:
                raise PolicyError(
                    code="token_not_allowed",
                    message="Token not allowlisted.",
                    data={
                        "from_token": from_token,
                        "to_token": to_token,
                        "allow_tokens": sorted(allow_tokens),
                    },
                )

        max_amount_global = (overrides or {}).get("MAX_TRADE_AMOUNT", _env_float("MAX_TRADE_AMOUNT", None))
        if max_amount_global is not None and amount > max_amount_global:
            raise PolicyError(
                code="trade_amount_too_large",
                message=f"Trade amount {amount} exceeds MAX_TRADE_AMOUNT={max_amount_global}.",
                data={"amount": amount, "max_trade_amount": max_amount_global},
            )

        max_amount_from = _env_float(f"MAX_TRADE_AMOUNT_{from_token.strip().upper()}", None)
        if max_amount_from is not None and amount > max_amount_from:
            raise PolicyError(
                code="trade_amount_too_large",
                message=(f"Trade amount {amount} {from_token} exceeds MAX_TRADE_AMOUNT_{from_token.strip().upper()}={max_amount_from}."),
                data={"amount": amount, "token": from_token, "max_trade_amount_token": max_amount_from},
            )

    def validate_transfer_native(
        self,
        *,
        chain: str,
        to_address: str,
        amount: float,
        overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        chain_l = chain.strip().lower()

        allow_chains = _parse_csv_set(os.getenv("ALLOW_CHAINS"))
        if allow_chains and chain_l not in allow_chains:
            raise PolicyError(
                code="chain_not_allowed",
                message=f"Chain '{chain}' is not allowlisted.",
                data={"chain": chain, "allow_chains": sorted(allow_chains)},
            )

        max_transfer = (overrides or {}).get("MAX_TRANSFER_NATIVE", _env_float("MAX_TRANSFER_NATIVE", None))
        if max_transfer is not None and amount > max_transfer:
            raise PolicyError(
                code="transfer_amount_too_large",
                message=f"Transfer amount {amount} exceeds MAX_TRANSFER_NATIVE={max_transfer}.",
                data={"amount": amount, "max_transfer_native": max_transfer},
            )

        allow_to = _parse_csv_set(os.getenv("ALLOW_TO_ADDRESSES"))
        if allow_to and to_address.strip().lower() not in allow_to:
            raise PolicyError(
                code="recipient_not_allowed",
                message="Recipient address is not allowlisted.",
                data={"to_address": to_address, "allow_to_addresses": sorted(allow_to)},
            )

    def validate_router_address(self, *, chain: str, router_address: str, context: Dict[str, Any]) -> None:
        """
        Validate that the DEX router / spender is allowlisted, if allowlists are configured.
        """
        addr = router_address.strip().lower()
        chain_l = chain.strip().lower()

        allow_global = _parse_csv_set(os.getenv("ALLOW_ROUTERS"))
        allow_chain = _parse_csv_set(os.getenv(f"ALLOW_ROUTERS_{chain_l.upper()}"))
        allow = allow_chain or allow_global

        if allow and addr not in allow:
            raise PolicyError(
                code="router_not_allowed",
                message="Router/spender address is not allowlisted.",
                data={"router": router_address, "chain": chain, "allow_routers": sorted(allow), "context": context},
            )

    def validate_signer_address(self, *, address: str) -> None:
        """
        Optional safeguard: restrict signing to a known allowlist of addresses.

        This helps prevent an operator accidentally pointing ReadyTrader-Crypto at the wrong signer/key.
        """
        addr = (address or "").strip().lower()
        allow = _parse_csv_set(os.getenv("ALLOW_SIGNER_ADDRESSES"))
        if allow and addr not in allow:
            raise PolicyError(
                code="signer_address_not_allowed",
                message="Signer address is not allowlisted.",
                data={"address": address, "allow_signer_addresses": sorted(allow)},
            )

    def validate_sign_tx(
        self,
        *,
        chain_id: int | None,
        to_address: str | None,
        value_wei: int | None,
        gas: int | None,
        gas_price_wei: int | None,
        data_hex: str | None,
        max_fee_per_gas_wei: int | None = None,
        max_priority_fee_per_gas_wei: int | None = None,
        tx_type: int | None = None,
    ) -> None:
        """
        Phase 5: signer-side intent guardrails (defense in depth).

        Defaults are permissive unless env vars are set.

        Env:
        - ALLOW_SIGN_CHAIN_IDS (csv ints)
        - ALLOW_SIGN_TO_ADDRESSES (csv addresses)
        - MAX_SIGN_VALUE_WEI (int)
        - MAX_SIGN_GAS (int)
        - MAX_SIGN_GAS_PRICE_WEI (int)
        - MAX_SIGN_DATA_BYTES (int)
        - DISALLOW_SIGN_CONTRACT_CREATION (true/false)
        """
        allow_chain_ids = _parse_int_set(os.getenv("ALLOW_SIGN_CHAIN_IDS"))
        if allow_chain_ids and chain_id is not None and int(chain_id) not in allow_chain_ids:
            raise PolicyError(
                code="sign_chain_id_not_allowed",
                message="chain_id is not allowlisted for signing.",
                data={"chain_id": int(chain_id), "allow_sign_chain_ids": sorted(allow_chain_ids)},
            )

        allow_to = _parse_csv_set(os.getenv("ALLOW_SIGN_TO_ADDRESSES"))
        if allow_to and to_address and to_address.strip().lower() not in allow_to:
            raise PolicyError(
                code="sign_to_not_allowed",
                message="Recipient/contract address is not allowlisted for signing.",
                data={"to_address": to_address, "allow_sign_to_addresses": sorted(allow_to)},
            )

        max_value = _env_int("MAX_SIGN_VALUE_WEI", None)
        if max_value is not None and (value_wei or 0) > int(max_value):
            raise PolicyError(
                code="sign_value_too_large",
                message="Transaction value exceeds MAX_SIGN_VALUE_WEI.",
                data={"value_wei": int(value_wei or 0), "max_sign_value_wei": int(max_value)},
            )

        max_gas = _env_int("MAX_SIGN_GAS", None)
        if max_gas is not None and (gas or 0) > int(max_gas):
            raise PolicyError(
                code="sign_gas_too_large",
                message="Transaction gas exceeds MAX_SIGN_GAS.",
                data={"gas": int(gas or 0), "max_sign_gas": int(max_gas)},
            )

        fee_fields = {}
        for field, value in (
            ("gasPrice", gas_price_wei),
            ("maxFeePerGas", max_fee_per_gas_wei),
            ("maxPriorityFeePerGas", max_priority_fee_per_gas_wei),
            ("type", tx_type),
        ):
            if value is not None:
                fee_fields[field] = value
        try:
            validate_transaction_fees(fee_fields, max_gas_price_wei=_env_int("MAX_SIGN_GAS_PRICE_WEI", None))
        except SignerPolicyViolation as exc:
            raise PolicyError("sign_" + exc.code, exc.message, exc.data) from exc

        max_data = _env_int("MAX_SIGN_DATA_BYTES", None)
        if max_data is not None and data_hex is not None:
            s = str(data_hex).strip()
            if s.startswith("0x"):
                s = s[2:]
            data_bytes = len(s) // 2
            if data_bytes > int(max_data):
                raise PolicyError(
                    code="sign_data_too_large",
                    message="Transaction calldata exceeds MAX_SIGN_DATA_BYTES.",
                    data={"data_bytes": data_bytes, "max_sign_data_bytes": int(max_data)},
                )

        disallow_create = (os.getenv("DISALLOW_SIGN_CONTRACT_CREATION") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        if disallow_create and not to_address:
            raise PolicyError(
                code="sign_contract_creation_not_allowed",
                message="Contract creation tx is disallowed by policy.",
                data={},
            )

    def validate_cex_order(
        self,
        *,
        exchange_id: str,
        symbol: str,
        market_type: str = "spot",
        side: str,
        amount: float,
        order_type: str,
        price: Optional[float] = None,
        overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        ex = exchange_id.strip().lower()
        sym = symbol.strip().upper()
        mt = (market_type or "").strip().lower() or "spot"
        sd = side.strip().lower()
        ot = order_type.strip().lower()

        allow_exchanges = _parse_csv_set(os.getenv("ALLOW_EXCHANGES"))
        if allow_exchanges and ex not in allow_exchanges:
            raise PolicyError(
                code="exchange_not_allowed",
                message=f"Exchange '{exchange_id}' is not allowlisted.",
                data={"exchange": exchange_id, "allow_exchanges": sorted(allow_exchanges)},
            )

        allow_symbols = _parse_csv_set(os.getenv("ALLOW_CEX_SYMBOLS"))
        if allow_symbols and sym.lower() not in allow_symbols:
            raise PolicyError(
                code="symbol_not_allowed",
                message=f"Symbol '{symbol}' is not allowlisted for CEX.",
                data={"symbol": symbol, "allow_cex_symbols": sorted(allow_symbols)},
            )

        allow_market_types = _parse_csv_set(os.getenv("ALLOW_CEX_MARKET_TYPES"))
        if allow_market_types and mt not in allow_market_types:
            raise PolicyError(
                code="market_type_not_allowed",
                message=f"Market type '{market_type}' is not allowlisted for CEX.",
                data={"market_type": market_type, "allow_cex_market_types": sorted(allow_market_types)},
            )

        if sd not in {"buy", "sell"}:
            raise PolicyError("invalid_side", "side must be 'buy' or 'sell'", {"side": side})
        if ot not in {"market", "limit"}:
            raise PolicyError(
                "invalid_order_type",
                "order_type must be 'market' or 'limit'",
                {"order_type": order_type},
            )
        if amount <= 0:
            raise PolicyError("invalid_amount", "amount must be > 0", {"amount": amount})
        if ot == "limit" and (price is None or price <= 0):
            raise PolicyError("invalid_price", "price must be provided for limit orders and be > 0", {"price": price})

        max_amt = (overrides or {}).get("MAX_CEX_ORDER_AMOUNT", _env_float("MAX_CEX_ORDER_AMOUNT", None))
        if max_amt is not None and amount > max_amt:
            raise PolicyError(
                code="order_amount_too_large",
                message=f"Order amount {amount} exceeds MAX_CEX_ORDER_AMOUNT={max_amt}.",
                data={"amount": amount, "max_cex_order_amount": max_amt},
            )

    def validate_cex_access(self, *, exchange_id: str) -> None:
        ex = exchange_id.strip().lower()
        allow_exchanges = _parse_csv_set(os.getenv("ALLOW_EXCHANGES"))
        if allow_exchanges and ex not in allow_exchanges:
            raise PolicyError(
                code="exchange_not_allowed",
                message=f"Exchange '{exchange_id}' is not allowlisted.",
                data={"exchange": exchange_id, "allow_exchanges": sorted(allow_exchanges)},
            )
