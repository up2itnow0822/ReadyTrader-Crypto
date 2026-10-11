from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

from web3 import Web3
from web3.providers.rpc import HTTPProvider

CHAIN_ID_BY_NAME: Dict[str, int] = {
    "ethereum": 1,
    "base": 8453,
    "arbitrum": 42161,
    "optimism": 10,
}


def chain_id_for(chain: str) -> int:
    c = (chain or "").strip().lower()
    if c in CHAIN_ID_BY_NAME:
        return CHAIN_ID_BY_NAME[c]
    raise ValueError(f"Unsupported chain: {chain}")


def _env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def rpc_url_for(chain: str) -> str:
    """
    Resolve RPC URL for a chain.

    Env precedence (chain=ethereum -> ETHEREUM):
    - EVM_RPC_URL_<CHAIN>
    - RPC_URL_<CHAIN>
    """
    c = (chain or "").strip().lower()
    key = c.upper()
    url = _env(f"EVM_RPC_URL_{key}") or _env(f"RPC_URL_{key}")
    if not url:
        raise ValueError(f"Missing RPC URL for chain '{chain}'. Set EVM_RPC_URL_{key} (or RPC_URL_{key}).")
    return url


@lru_cache(maxsize=16)
def get_web3(chain: str) -> Web3:
    url = rpc_url_for(chain)
    w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": float(_env("HTTP_TIMEOUT_SEC") or "10")}))
    if not w3.is_connected():
        raise ValueError(f"RPC not reachable for chain '{chain}' ({url})")
    return w3


ERC20_MIN_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
]


@lru_cache(maxsize=2048)
def erc20_decimals(chain: str, token_address: str) -> int:
    w3 = get_web3(chain)
    addr = w3.to_checksum_address(token_address)
    c = w3.eth.contract(address=addr, abi=ERC20_MIN_ABI)
    d = int(c.functions.decimals().call())
    if d < 0 or d > 255:
        raise ValueError("Invalid ERC20 decimals()")
    return d


def to_atomic(amount: float, decimals: int) -> int:
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if decimals < 0 or decimals > 255:
        raise ValueError("decimals out of range")
    # avoid float drift by using string conversion
    s = f"{amount:.18f}".rstrip("0").rstrip(".")
    if not s:
        s = "0"
    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    frac = (frac + ("0" * decimals))[:decimals]
    return int(whole or "0") * (10**decimals) + int(frac or "0")


def is_hex_address(s: str) -> bool:
    v = (s or "").strip()
    if not (v.startswith("0x") and len(v) == 42):
        return False
    try:
        int(v[2:], 16)
        return True
    except Exception:
        return False


def send_raw_transaction(chain: str, raw_tx: bytes) -> str:
    w3 = get_web3(chain)
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    # tx_hash is HexBytes
    return w3.to_hex(tx_hash)
