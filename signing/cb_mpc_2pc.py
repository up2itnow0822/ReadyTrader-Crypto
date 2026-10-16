from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import requests
import rlp
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from eth_keys import keys
from eth_utils import keccak

from .base import SignedTx, Signer
from .policy import SignerPolicyViolation, transaction_uint, validate_transaction_fees

SECP256K1_N = int(
    "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141",
    16,
)
SECP256K1_HALF_N = SECP256K1_N // 2


def _env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise ValueError(f"{name} environment variable not set")
    return v


def _http_timeout() -> float:
    value = float((os.getenv("HTTP_TIMEOUT_SEC") or "65").strip())
    if not math.isfinite(value) or not 0 < value <= 90:
        raise ValueError("HTTP_TIMEOUT_SEC must be finite and between 0 and 90")
    return value


def _to_int(v: Any, *, name: str) -> int:
    try:
        return transaction_uint(v, name)
    except SignerPolicyViolation as exc:
        raise ValueError(exc.message) from exc


def _to_bytes32(b: bytes) -> bytes:
    if len(b) != 32:
        raise ValueError("expected 32 bytes")
    return b


def _to_bytes(v: Any, *, name: str) -> bytes:
    if v is None:
        return b""
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("0x"):
            s = s[2:]
        if s == "":
            return b""
        return bytes.fromhex(s)
    raise ValueError(f"Invalid bytes field {name}: {type(v).__name__}")


def _to_address_bytes(v: Any) -> bytes:
    if v is None or v == "":
        return b""
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return b""
        if s.startswith("0x"):
            s = s[2:]
        b = bytes.fromhex(s)
        if len(b) != 20:
            raise ValueError("to must be 20 bytes")
        return b
    raise ValueError("to must be hex string")


def _normalize_sig(r: int, s: int) -> Tuple[int, int]:
    if r <= 0 or r >= SECP256K1_N:
        raise ValueError("invalid r")
    if s <= 0 or s >= SECP256K1_N:
        raise ValueError("invalid s")
    if s > SECP256K1_HALF_N:
        s = SECP256K1_N - s
    return r, s


def _find_recovery_id(msg_hash_32: bytes, r: int, s: int, expected_address: str) -> int:
    exp = expected_address.strip().lower()
    if not exp.startswith("0x"):
        exp = "0x" + exp
    for recid in (0, 1):
        sig = keys.Signature(vrs=(recid, r, s))
        pub = sig.recover_public_key_from_msg_hash(msg_hash_32)
        if pub.to_checksum_address().lower() == exp:
            return recid
    raise ValueError("could not determine recovery id (address mismatch)")


def _rlp_int(i: int) -> bytes:
    if i == 0:
        return b""
    return int(i).to_bytes((int(i).bit_length() + 7) // 8, "big")


@dataclass(frozen=True)
class _SignedTx(SignedTx):
    rawTransaction: bytes


class MPCApprovalRequired(ValueError):
    """Unsigned transaction details for an independent operator to inspect."""

    def __init__(self, transaction: dict, digest32: bytes) -> None:
        self.transaction = transaction
        self.digest_hex = "0x" + digest32.hex()
        super().__init__("MPC approval required: " + json.dumps({"transaction": transaction, "digest_hex": self.digest_hex}, sort_keys=True))


class CoinbaseMpc2pcSigner(Signer):
    """MPC EVM signer with mTLS and separately issued, exact-digest approvals.

    MPC_APPROVAL_DIR contains <digest-without-0x>.json operator approvals. This
    client never creates approval authority; both parties independently verify it.
    """

    def __init__(self, url_env: str = "MPC_SIGNER_URL") -> None:
        self._base_url = _env(url_env).rstrip("/")
        parsed = urlsplit(self._base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("MPC_SIGNER_URL must be an https origin without credentials")
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.cert = (_env("MPC_CLIENT_CERT"), _env("MPC_CLIENT_KEY"))
        self._session.verify = _env("MPC_CA_CERT")
        self._cached_address: Optional[str] = None

    def _approval(self, tx: Dict[str, Any], digest32: bytes) -> dict:
        proof = tx.get("mpc_approval")
        if proof is None:
            directory = os.getenv("MPC_APPROVAL_DIR")
            if not directory:
                raise ValueError("MPC approval required; configure MPC_APPROVAL_DIR")
            try:
                path = Path(directory) / (digest32.hex() + ".json")
                with path.open("rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError("MPC approval exceeds size limit")
                proof = json.loads(raw)
            except (OSError, ValueError) as exc:
                raise ValueError("MPC approval unavailable or invalid") from exc
        if (
            not isinstance(proof, dict)
            or set(proof) != {"id", "expires_at", "wallet", "digest_hex", "signature_hex"}
            or proof.get("digest_hex") != "0x" + digest32.hex()
        ):
            raise ValueError("MPC approval does not match transaction digest")
        return proof

    def _get_address(self) -> str:
        timeout = _http_timeout()
        r = self._session.get(f"{self._base_url}/address", timeout=timeout, allow_redirects=False)
        if r.is_redirect:
            raise ValueError("MPC redirects are forbidden")
        r.raise_for_status()
        data = r.json()
        addr = str(data.get("address") or "").strip()
        if not addr:
            raise ValueError("MPC signer returned empty address")
        return addr

    def get_address(self) -> str:
        if self._cached_address:
            return self._cached_address
        self._cached_address = self._get_address()
        return self._cached_address

    def _mpc_sign_transaction(self, transaction: dict, approval: dict) -> bytes:
        timeout = _http_timeout()
        payload = {"transaction": transaction, "approval": approval}
        r = self._session.post(f"{self._base_url}/sign_transaction", json=payload, timeout=timeout, allow_redirects=False)
        if r.is_redirect:
            raise ValueError("MPC redirects are forbidden")
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise ValueError(f"MPC signing failed: {data}")
        sig_hex = str(data.get("signature_der_hex") or "").strip()
        if sig_hex.startswith("0x"):
            sig_hex = sig_hex[2:]
        sig = bytes.fromhex(sig_hex)
        if not sig:
            raise ValueError("MPC signer returned empty signature")
        return sig

    def sign_transaction(self, tx: Dict[str, Any], *, chain_id: int | None = None) -> SignedTx:
        allowed = {
            "type",
            "chainId",
            "nonce",
            "gas",
            "gasPrice",
            "maxFeePerGas",
            "maxPriorityFeePerGas",
            "to",
            "from",
            "value",
            "data",
            "accessList",
            "idempotency_key",
            "idempotencyKey",
            "mpc_approval",
        }
        if set(tx) - allowed:
            raise ValueError("Unsupported transaction fields")
        try:
            tx = validate_transaction_fees(tx)
        except SignerPolicyViolation as exc:
            raise ValueError(exc.message) from exc
        tx_type = tx.get("type", 2 if "maxFeePerGas" in tx else 0)
        if tx_type not in (0, 2):
            raise ValueError("MPC supports only legacy and type-2 transactions")
        cid = _to_int(chain_id if chain_id is not None else tx.get("chainId"), name="chainId")
        if "chainId" in tx and _to_int(tx["chainId"], name="chainId") != cid:
            raise ValueError("Conflicting chainId")
        if cid <= 0 or _to_int(tx.get("gas"), name="gas") <= 0:
            raise ValueError("chainId and gas must be positive")
        if tx.get("accessList", []) != []:
            raise ValueError("MPC does not support nonempty accessList")
        if len(_to_address_bytes(tx.get("to"))) != 20:
            raise ValueError("MPC disallows contract creation")
        if _to_int(tx.get("nonce"), name="nonce") >= 2**64 or _to_int(tx.get("gas"), name="gas") >= 2**64:
            raise ValueError("nonce and gas must fit uint64")

        # Build signing payload + hash
        if int(tx_type) == 0:
            nonce = _to_int(tx.get("nonce"), name="nonce")
            gas_price = _to_int(tx.get("gasPrice"), name="gasPrice")
            gas = _to_int(tx.get("gas"), name="gas")
            to_b = _to_address_bytes(tx.get("to"))
            value = _to_int(tx.get("value", 0), name="value")
            data_b = _to_bytes(tx.get("data", b""), name="data")

            unsigned = [
                _rlp_int(nonce),
                _rlp_int(gas_price),
                _rlp_int(gas),
                to_b,
                _rlp_int(value),
                data_b,
                _rlp_int(int(cid)),
                b"",
                b"",
            ]
            signing_payload = rlp.encode(unsigned)
            digest32 = _to_bytes32(keccak(signing_payload))
        elif int(tx_type) == 2:
            nonce = _to_int(tx.get("nonce"), name="nonce")
            max_priority = _to_int(tx.get("maxPriorityFeePerGas"), name="maxPriorityFeePerGas")
            max_fee = _to_int(tx.get("maxFeePerGas"), name="maxFeePerGas")
            gas = _to_int(tx.get("gas"), name="gas")
            to_b = _to_address_bytes(tx.get("to"))
            value = _to_int(tx.get("value", 0), name="value")
            data_b = _to_bytes(tx.get("data", b""), name="data")
            access_list = tx.get("accessList") or []
            if not isinstance(access_list, list):
                raise ValueError("accessList must be a list")

            inner = [
                _rlp_int(int(cid)),
                _rlp_int(nonce),
                _rlp_int(max_priority),
                _rlp_int(max_fee),
                _rlp_int(gas),
                to_b,
                _rlp_int(value),
                data_b,
                access_list,
            ]
            signing_payload = b"\x02" + rlp.encode(inner)
            digest32 = _to_bytes32(keccak(signing_payload))
        else:
            raise ValueError(f"Unsupported tx type: {tx_type} (supported: 0, 2)")

        transaction = {
            "type": tx_type,
            "chain_id": str(cid),
            "nonce": str(nonce),
            "gas": str(gas),
            "to": "0x" + to_b.hex(),
            "value": str(value),
            "data": "0x" + data_b.hex(),
            "gas_price": str(tx.get("gasPrice", 0)),
            "max_fee_per_gas": str(tx.get("maxFeePerGas", 0)),
            "max_priority_fee_per_gas": str(tx.get("maxPriorityFeePerGas", 0)),
        }
        try:
            approval = self._approval(tx, digest32)
        except ValueError as exc:
            raise MPCApprovalRequired(transaction, digest32) from exc
        expected_addr = self.get_address()
        if str(approval["wallet"]).lower() != expected_addr.lower() or (tx.get("from") and str(tx["from"]).lower() != expected_addr.lower()):
            raise ValueError("MPC approval wallet or transaction sender mismatch")
        sig_der = self._mpc_sign_transaction(transaction, approval)
        r, s = decode_dss_signature(sig_der)
        r, s = _normalize_sig(int(r), int(s))

        # Determine recovery id by checking recovered address
        recid = _find_recovery_id(digest32, r, s, expected_addr)

        # Assemble raw tx
        if int(tx_type) == 0:
            v = int(recid) + 35 + (2 * int(cid))
            signed = [
                _rlp_int(_to_int(tx.get("nonce"), name="nonce")),
                _rlp_int(_to_int(tx.get("gasPrice"), name="gasPrice")),
                _rlp_int(_to_int(tx.get("gas"), name="gas")),
                _to_address_bytes(tx.get("to")),
                _rlp_int(_to_int(tx.get("value", 0), name="value")),
                _to_bytes(tx.get("data", b""), name="data"),
                _rlp_int(v),
                _rlp_int(r),
                _rlp_int(s),
            ]
            raw = rlp.encode(signed)
            return _SignedTx(rawTransaction=raw)

        # type 2
        y_parity = int(recid)
        access_list = tx.get("accessList") or []
        inner_signed = [
            _rlp_int(int(cid)),
            _rlp_int(_to_int(tx.get("nonce"), name="nonce")),
            _rlp_int(_to_int(tx.get("maxPriorityFeePerGas"), name="maxPriorityFeePerGas")),
            _rlp_int(_to_int(tx.get("maxFeePerGas"), name="maxFeePerGas")),
            _rlp_int(_to_int(tx.get("gas"), name="gas")),
            _to_address_bytes(tx.get("to")),
            _rlp_int(_to_int(tx.get("value", 0), name="value")),
            _to_bytes(tx.get("data", b""), name="data"),
            access_list,
            _rlp_int(y_parity),
            _rlp_int(r),
            _rlp_int(s),
        ]
        raw = b"\x02" + rlp.encode(inner_signed)
        return _SignedTx(rawTransaction=raw)
