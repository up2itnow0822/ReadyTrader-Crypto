from __future__ import annotations

import os
from functools import lru_cache

from .base import Signer
from .cb_mpc_2pc import CoinbaseMpc2pcSigner
from .encrypted_keystore import EncryptedKeystoreSigner
from .env_private_key import EnvPrivateKeySigner
from .null_signer import NullSigner
from .policy import maybe_wrap_signer
from .remote_signer import RemoteSigner


@lru_cache(maxsize=1)
def get_signer() -> Signer:
    """
    Select signer based on SIGNER_TYPE.

    Supported:
    - env_private_key (default): uses PRIVATE_KEY env var
    - keystore: uses KEYSTORE_PATH + KEYSTORE_PASSWORD
    - remote: uses SIGNER_REMOTE_URL (HTTP signer / sidecar)
    - cb_mpc_2pc: delegates signing to a Coinbase cb-mpc 2-party signer service (MPC_SIGNER_URL)
    """
    # Safe-by-default behavior:
    # - In paper mode, if SIGNER_TYPE is not explicitly configured, we use a NullSigner so
    #   imports/tools/docs generation do not require real keys.
    from app.core.config import settings

    raw_type = (os.getenv("SIGNER_TYPE") or "").strip()
    if not raw_type and getattr(settings, "PAPER_MODE", True):
        return maybe_wrap_signer(NullSigner())

    signer_type = (raw_type or "env_private_key").strip().lower()
    # Defense in depth: never allow env private keys outside paper-only, non-live runs
    if signer_type == "env_private_key":
        paper_mode = bool(getattr(settings, "PAPER_MODE", True))
        live_enabled = bool(getattr(settings, "LIVE_TRADING_ENABLED", False))
        if (not paper_mode) or live_enabled:
            raise ValueError("SIGNER_TYPE=env_private_key is forbidden when PAPER_MODE=false or LIVE_TRADING_ENABLED=true; use keystore, remote, or cb_mpc_2pc")
        return maybe_wrap_signer(EnvPrivateKeySigner())
    if signer_type == "keystore":
        return maybe_wrap_signer(EncryptedKeystoreSigner())
    if signer_type == "remote":
        return maybe_wrap_signer(RemoteSigner())
    if signer_type == "cb_mpc_2pc":
        return maybe_wrap_signer(CoinbaseMpc2pcSigner())
    if signer_type == "null":
        return maybe_wrap_signer(NullSigner())
    raise ValueError(f"Unsupported SIGNER_TYPE: {signer_type}")
