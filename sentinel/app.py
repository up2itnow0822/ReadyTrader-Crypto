import hmac
import os
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from signing import get_signer
from signing.intents import build_evm_tx_intent
from signing.policy import SignerPolicyViolation

app = FastAPI(title="Sentinel Signer", version="1.0.0")

# Sentinel is a dev/demo reference remote signer (SIGNER_TYPE=env_private_key) meant to run
# on a private compose network -- see docker-compose.sentinel.yml and docs/CUSTODY.md for
# production signer options. Every route below is gated by _require_auth.
MIN_AUTH_TOKEN_LENGTH = 32


def _require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Fail-closed Bearer-token auth shared by every route.

    SENTINEL_AUTH_TOKEN is read fresh on every call (never cached at import time) so it can
    be rotated without restarting the process. There is no flag to bypass this check: an
    unset or short token always fails closed (503), never falls through to "no auth".
    """
    expected = os.getenv("SENTINEL_AUTH_TOKEN", "")
    if len(expected) < MIN_AUTH_TOKEN_LENGTH:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sentinel signer is not configured: SENTINEL_AUTH_TOKEN is unset or shorter "
                f"than {MIN_AUTH_TOKEN_LENGTH} characters. Set a long, random SENTINEL_AUTH_TOKEN "
                "in the environment before sending requests -- there is no bypass."
            ),
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = authorization[len("Bearer ") :]
    # hmac.compare_digest is constant-time in the length of `expected`, so this does not leak
    # the token through response-timing differences. The token itself is never echoed back.
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid authentication token")


class SignRequest(BaseModel):
    tx: Dict[str, Any]
    chain_id: Optional[int] = None
    intent: Optional[Dict[str, Any]] = None


@app.get("/address")
def get_address(_auth: None = Depends(_require_auth)) -> Dict[str, str]:
    signer = get_signer()
    return {"address": signer.get_address()}


@app.post("/sign_transaction")
def sign_transaction(req: SignRequest, _auth: None = Depends(_require_auth)):
    try:
        signer = get_signer()
        # "Firewall" Logic: verify intent matches tx
        if req.intent:
            calculated_intent = build_evm_tx_intent(req.tx, chain_id=req.chain_id)
            if calculated_intent.to_dict() != req.intent:
                raise HTTPException(status_code=400, detail="Intent mismatch: payload does not match declared intent.")

        signed = signer.sign_transaction(req.tx, chain_id=req.chain_id)
        return {"rawTransactionHex": "0x" + signed.rawTransaction.hex()}
    except SignerPolicyViolation as e:
        raise HTTPException(status_code=403, detail=f"Policy violation: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
