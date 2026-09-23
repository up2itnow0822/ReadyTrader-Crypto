# sentinel/

## Purpose

A standalone FastAPI remote-signer reference service (`docker-compose.sentinel.yml`) that
exposes `POST /sign_transaction` and `GET /address` over HTTP for `signing/remote_signer.py`
to call. It is a **dev/demo reference implementation** (`SIGNER_TYPE=env_private_key`), not a
production custody path -- see `docs/CUSTODY.md` for production signer options.

## Ownership

ReadyTrader-Crypto signing subsystem, paired with `signing/remote_signer.py`.

## Local Contracts

- Every route requires `Authorization: Bearer <token>`, checked with `hmac.compare_digest`
  against env `SENTINEL_AUTH_TOKEN`.
- Fail closed: if `SENTINEL_AUTH_TOKEN` is unset or shorter than 32 characters, every request
  returns 503 -- there is no bypass flag.
- Missing/malformed header or wrong token returns 401; the token is never echoed back.
- `docker-compose.sentinel.yml` does not publish port 8888 on the host (`expose` only); it
  passes `SENTINEL_AUTH_TOKEN` to `sentinel` and the matching `REMOTE_SIGNER_AUTH_TOKEN` to
  `readytrader` from the host environment (same value).

## Work Guidance

- Never log or echo `SENTINEL_AUTH_TOKEN` or `PRIVATE_KEY`.
- Keep the intent-check (`build_evm_tx_intent`) and `SignerPolicyViolation` handling in
  `sign_transaction` -- auth is a layer in front of them, not a replacement.
- Changing the auth mechanism here must stay in step with `signing/remote_signer.py`'s
  `REMOTE_SIGNER_AUTH_TOKEN` header logic and `docs/THREAT_MODEL.md` / `docs/CUSTODY.md`.

## Verification

- `pytest tests/test_sentinel_auth.py -q`

## Child DOX Index

(none)
