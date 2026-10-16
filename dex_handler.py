import os
from typing import Any, Dict, Optional

import requests


class DexHandler:
    """
    Handles interactions with 1inch Swap API (v6.0).
    """

    BASE_URL = "https://api.1inch.dev/swap/v6.0"

    def __init__(self):
        self.api_key = os.getenv("ONEINCH_API_KEY")
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

        # Basic Token Map for Demo (Ethereum & Base)
        self.TOKEN_MAP = {
            "ethereum": {
                "ETH": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
                "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
            },
            "base": {
                "ETH": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "WETH": "0x4200000000000000000000000000000000000006",
                "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "USBC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",  # Base USBC
                "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
            },
        }

    def resolve_token(self, chain: str, symbol: str) -> Optional[str]:
        chain_map = self.TOKEN_MAP.get(chain.lower())
        if chain_map:
            return chain_map.get(symbol.upper())
        # Allow raw EVM addresses as token identifiers (advanced usage).
        s = (symbol or "").strip()
        if s.startswith("0x") and len(s) == 42:
            try:
                int(s[2:], 16)
                return s
            except Exception:
                return None
        return None

    def _get_chain_id(self, chain: str) -> int:
        chains = {"ethereum": 1, "base": 8453, "arbitrum": 42161, "optimism": 10}
        return chains.get(chain.lower(), 1)

    def get_quote(self, chain: str, token_in: str, token_out: str, amount: str) -> Dict[str, Any]:
        """
        Get a quote for a swap.
        amount should be in atomic units (wei).
        """
        if not self.api_key:
            return {"error": "ONEINCH_API_KEY not set"}

        chain_id = self._get_chain_id(chain)
        url = f"{self.BASE_URL}/{chain_id}/quote"

        params = {"src": token_in, "dst": token_out, "amount": amount, "includeTokensInfo": "true", "includeProtocols": "true"}

        timeout = float(os.getenv("HTTP_TIMEOUT_SEC", "10"))
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": f"1inch Quote Error: {str(e)}"}

    def build_swap_tx(
        self,
        chain: str,
        token_in: str,
        token_out: str,
        amount: str,
        from_address: str,
        slippage: float = 1.0,
    ) -> Dict[str, Any]:
        """Live aggregation is contained until an audited intent verifier exists.

        A router allowlist and decoded outer selector do not constrain arbitrary
        route executors, permits, recipients, output floors, or deadlines. Never
        return signable third-party calldata under this incomplete contract.
        """
        return {
            "code": "unsupported_swap_semantics",
            "error": (
                "Live aggregated swaps are disabled: canonical approved intent and full router semantics cannot be verified. Paper swaps remain available."
            ),
        }

    def check_allowance(self, chain: str, token_address: str, wallet_address: str) -> Dict[str, Any]:
        """
        Check if the 1inch router is approved to spend the token.
        """
        if not self.api_key:
            return {"error": "ONEINCH_API_KEY not set"}

        chain_id = self._get_chain_id(chain)
        url = f"{self.BASE_URL}/{chain_id}/approve/allowance"

        params = {"tokenAddress": token_address, "walletAddress": wallet_address}

        timeout = float(os.getenv("HTTP_TIMEOUT_SEC", "10"))
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": f"1inch Allowance Error: {str(e)}"}

    def get_approve_tx(self, chain: str, token_address: str, amount: str = None) -> Dict[str, Any]:
        """
        Get call data to approve the 1inch router.
        """
        if not self.api_key:
            return {"error": "ONEINCH_API_KEY not set"}

        chain_id = self._get_chain_id(chain)
        url = f"{self.BASE_URL}/{chain_id}/approve/transaction"

        params = {"tokenAddress": token_address}
        if amount:
            params["amount"] = amount

        timeout = float(os.getenv("HTTP_TIMEOUT_SEC", "10"))
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": f"1inch Approve Error: {str(e)}"}
