# signing/

## Purpose

Custody and transaction signing backends for on-chain (DEX) paths and signer-side policy guardrails.

## Ownership

ReadyTrader-Crypto signing subsystem. Used by execution tools when not in null/paper-safe mode.

## Local Contracts

- Supported `SIGNER_TYPE`: `env_private_key`, `keystore`, `remote`, `cb_mpc_2pc`, `null`
- `env_private_key` is development-only: forbidden when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`
- Live/production prefers `remote`, `keystore`, or `cb_mpc_2pc`
- `SIGNER_POLICY_ENABLED=true` required posture for live (settings warn/enforce via ops pack)
- Factory entry: `signing/factory.py` → `get_signer()`

## Work Guidance

- Do not log private keys, keystore passwords, or raw signed payloads
- When changing signer selection rules, update `app/core/settings.py` validation and `tests/test_settings_validation.py`
- Align docs in `docs/CUSTODY.md` and `docs/SECURITY_REVIEW.md`

## Verification

- `pytest tests/test_remote_signer.py tests/test_signer_policy.py tests/test_settings_validation.py -q`

## Child DOX Index

(none)
