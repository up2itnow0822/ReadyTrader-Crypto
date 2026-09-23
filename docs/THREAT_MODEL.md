## ReadyTrader-Crypto Threat Model (Live Trading)

This document is an operator-focused threat model for ReadyTrader-Crypto when configured for **live trading** (`PAPER_MODE=false`). It is intentionally concise and actionable.

### Scope

- **In scope**:
  - CEX credentials (`CEX_*`)
  - EVM signing materials (`PRIVATE_KEY`, keystore files, `SIGNER_REMOTE_URL`)
  - Live execution path (CEX orders, EVM transfers/swaps)
  - Market data correctness (stale/outlier data leading to bad execution)
- **Out of scope**:
  - Exchange-side compromise (assumed handled by exchange security)
  - OS/hypervisor compromise (assumed handled by your infra)

______________________________________________________________________

## Primary assets

- **Funds**: on-chain wallets + exchange balances
- **Keys**:
  - CEX API keys
  - EVM signer secrets (raw key, keystore passphrase, remote signer credentials)
- **Execution authority**: ability to place orders / sign transactions
- **Operational evidence**: audit logs and operator telemetry

______________________________________________________________________

## Threats and mitigations

### 1) Secret leakage (keys logged or committed)

- **Threat**: accidental logging of secrets; committing `.env`; exposing keystore/password.
- **Mitigations**:
  - Never commit `.env` (use `env.example`).
  - Phase 4 logging redaction reduces risk, but do not rely on it—avoid logging secrets entirely.
  - Prefer **keystore** or **remote signer** for production over `PRIVATE_KEY`.

### 2) Wrong-key / wrong-signer usage

- **Threat**: ReadyTrader-Crypto points at an unintended key and signs from the wrong wallet.
- **Mitigations**:
  - Use `ALLOW_SIGNER_ADDRESSES` (PolicyEngine) to pin the expected signer address.
  - Use **signer policy wrapper** (`SIGNER_POLICY_*`) to restrict what the signer can sign.

### 3) Overbroad signing authority (remote signer/HSM proxy)

- **Threat**: remote signer signs any tx presented by client; compromised ReadyTrader-Crypto can drain funds.
- **Mitigations**:
  - Phase 5 introduces **explicit signing intent** in RemoteSigner requests (`intent` payload).
  - Enforce on signer side:
    - `SIGNER_ALLOWED_CHAIN_IDS`
    - `SIGNER_ALLOWED_TO_ADDRESSES`
    - `SIGNER_MAX_VALUE_WEI`
    - `SIGNER_MAX_DATA_BYTES`
    - `SIGNER_DISALLOW_CONTRACT_CREATION=true`

### 4) Malicious or stale market data drives bad trades

- **Threat**: stale/outlier tick causes market order at wrong time/venue.
- **Mitigations**:
  - Phase 3 guardrails:
    - `MARKETDATA_FAIL_CLOSED=true`
    - tune `MARKETDATA_MAX_AGE_MS*` and outlier thresholds
  - Prefer websocket-first + ingest-first for trusted feeds.

### 5) Execution replay / double-submit from agent retries

- **Threat**: an agent retries and duplicates an order or tx.
- **Mitigations**:
  - Use `idempotency_key` wherever supported (CEX order placement, swaps).
  - Use approve-each mode for early deployments (`EXECUTION_APPROVAL_MODE=approve_each`).

### 6) Operator mistakes / unsafe configuration

- **Threat**: loosening limits too far, disabling policy allowlists, enabling live trading without supervision.
- **Mitigations**:
  - Live-trading consent gate + kill switch (`TRADING_HALTED=true`).
  - Advanced Risk Mode requires additional consent.
  - Keep policy allowlists/limits enabled in production.

### 7) Sentinel dev/demo remote-signer service

- **Threat**: `docker-compose.sentinel.yml` runs `sentinel/app.py`, a convenience remote
  signer for local development. Unauthenticated HTTP would let anyone who can reach the
  container sign transactions or read the wallet address.
- **Mitigations**:
  - Every route requires `Authorization: Bearer <token>`, checked with `hmac.compare_digest`
    against `SENTINEL_AUTH_TOKEN`; the service fails closed (503) if that token is unset or
    shorter than 32 characters — no bypass flag exists.
  - The compose file does not publish port 8888 on the host (`expose` only).
  - It is a **dev/demo reference implementation**, not a production custody path — see
    `docs/CUSTODY.md` for production signer options.

______________________________________________________________________

## Recommended production baseline

- **Execution**:
  - start with `EXECUTION_APPROVAL_MODE=approve_each`
  - use `TRADING_HALTED=true` by default; enable only during controlled windows
- **Keys**:
  - prefer `SIGNER_TYPE=keystore` or `SIGNER_TYPE=remote`
  - set `ALLOW_SIGNER_ADDRESSES=<expected>`
  - enable signer-side policy (`SIGNER_POLICY_ENABLED=true` + limits/allowlists)
- **Market data**:
  - enable `MARKETDATA_FAIL_CLOSED=true`
  - use WS + trusted ingest feeds; REST as fallback
