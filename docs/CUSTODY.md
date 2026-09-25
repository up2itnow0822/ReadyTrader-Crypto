## Key Custody & Rotation (Phase 5)

This document describes recommended custody patterns for ReadyTrader-Crypto when operating in live mode.

______________________________________________________________________

## CEX API Keys (Least Privilege)

### Best Practices

- Create **trade-only** keys when possible
- Disable withdrawal permissions
- Restrict IPs (if your exchange supports it)
- Rotate regularly and immediately upon suspicion

### Per-Exchange Configuration

| Exchange | Recommended Permissions       | IP Restriction | Rotation Frequency |
| -------- | ----------------------------- | -------------- | ------------------- |
| Binance  | Spot trading only, no futures | Yes            | 90 days             |
| Kraken   | Create/cancel orders only     | Yes            | 90 days             |
| Coinbase | Trade permission only         | Limited        | 90 days             |

### Environment Variables

```bash
# Generic (fallback)
CEX_API_KEY=...
CEX_API_SECRET=...

# Per-exchange (preferred - allows different permissions per venue)
CEX_BINANCE_API_KEY=...
CEX_BINANCE_API_SECRET=...
CEX_KRAKEN_API_KEY=...
CEX_KRAKEN_API_SECRET=...
```

______________________________________________________________________

## EVM Signing Options

### 1) `SIGNER_TYPE=env_private_key` (Development Only)

- Uses `PRIVATE_KEY` in the environment
- Fast for local testing, **not recommended** for production
- Key is exposed in process memory

```bash
SIGNER_TYPE=env_private_key
PRIVATE_KEY=0x...
```

### 2) `SIGNER_TYPE=keystore` (Baseline Production)

- Uses `KEYSTORE_PATH` + `KEYSTORE_PASSWORD`
- Keeps key encrypted at rest
- Still protect the passphrase

```bash
SIGNER_TYPE=keystore
KEYSTORE_PATH=/secrets/keystore.json
KEYSTORE_PASSWORD=...
```

### 3) `SIGNER_TYPE=remote` (Enterprise-Friendly)

- Uses `SIGNER_REMOTE_URL` to sign via HTTP
- Recommended for HSM/KMS-backed signing proxies
- ReadyTrader-Crypto includes explicit `intent` in signing requests (Phase 5) to enable safer signer-side policy

```bash
SIGNER_TYPE=remote
SIGNER_REMOTE_URL=https://signer.internal:8443
REMOTE_SIGNER_TIMEOUT_SEC=30
REMOTE_SIGNER_RETRY_COUNT=3
REMOTE_SIGNER_REQUIRE_TLS=true
# Only if the remote signer expects it (the bundled dev/demo sentinel below does):
# REMOTE_SIGNER_AUTH_TOKEN=...
```

`RemoteSigner` enforces `REMOTE_SIGNER_REQUIRE_TLS` (default `true`): a `SIGNER_REMOTE_URL`
that is not `https://` is refused at startup, before any transaction or bearer token can be
sent in cleartext. Set it to `false` only when the signer is on a private network with the
agent (the bundled dev/demo compose stack below does exactly that). Redirects are never
followed: a signer that answers 3xx is refused, so point `SIGNER_REMOTE_URL` at the final URL.
`RemoteSigner` presents no TLS client certificate; a signer that requires mTLS is not supported.

> **Bundled dev/demo signer:** `docker-compose.sentinel.yml` / `sentinel/app.py` is a
> reference `SIGNER_TYPE=remote` implementation for local development only — not a
> production custody path. It requires `Authorization: Bearer <token>` on every request
> (`SENTINEL_AUTH_TOKEN` on the signer side, `REMOTE_SIGNER_AUTH_TOKEN` on the
> ReadyTrader-Crypto side — same value) and fails closed (503) if that token is unset or
> under 32 characters. It publishes no host port; reachable only on the compose-internal
> network.

### 4) `SIGNER_TYPE=cb_mpc_2pc` (Coinbase cb-mpc, Self-Hosted MPC)

- Uses a 2-party MPC signer service (see `mpc_signer/`) configured via `MPC_SIGNER_URL`
- No private key exists in a single process; signing is distributed across two parties
- Recommended for "degen" multi-venue users who want a single wallet with strong compromise resistance

```bash
SIGNER_TYPE=cb_mpc_2pc
MPC_SIGNER_URL=http://mpc-party-0:8787
```

______________________________________________________________________

## Defense in Depth

Use both layers when possible:

### PolicyEngine Allowlists

```bash
# Address allowlist
ALLOW_SIGNER_ADDRESSES=0xabc...,0xdef...

# Signer-intent guardrails
ALLOW_SIGN_CHAIN_IDS=1,8453,42161,10
ALLOW_SIGN_TO_ADDRESSES=0xrouter1,0xrouter2
MAX_SIGN_VALUE_WEI=0
MAX_SIGN_GAS=500000
MAX_SIGN_GAS_PRICE_WEI=200000000000
MAX_SIGN_DATA_BYTES=2000
```

### Signer Policy Wrapper (Local, Defense-in-Depth)

```bash
SIGNER_POLICY_ENABLED=true
SIGNER_ALLOWED_CHAIN_IDS=1,8453,42161,10
SIGNER_ALLOWED_TO_ADDRESSES=0xrouter1,0xrouter2
SIGNER_MAX_VALUE_WEI=0
SIGNER_MAX_GAS=500000
SIGNER_DISALLOW_CONTRACT_CREATION=true
```

______________________________________________________________________

## Credential Rotation Policy

### Rotation Schedule

| Credential Type         | Standard Rotation | Emergency Rotation Trigger              |
| ------------------------ | ------------------ | ---------------------------------------- |
| CEX API Keys            | 90 days            | Suspicious activity, employee departure |
| Keystore Password       | 180 days           | Suspected compromise                    |
| Remote Signer TLS Certs | 365 days           | Certificate compromise                  |
| MPC Keyshares           | 180 days           | Party compromise, infrastructure change |
| JWT Secrets             | 90 days            | Token leak, admin departure             |
| Webhook Secrets         | 180 days           | Endpoint compromise                     |

### Standard Rotation Procedure

#### Step 1: Prepare

Restart the MCP server and the API server with `TRADING_HALTED=true` (settings are read at
start-up; exporting the variable in another shell does not change a running server), then:

```bash
# Verify halt is active
curl -s http://localhost:8000/api/health | jq '.trading_halted'
# Should return: true
```

#### Step 2: Rotate Credentials

**For CEX API Keys:**

1. Generate new API key in exchange dashboard
1. Configure with same permissions as old key
1. Test new key with read-only operation
1. Update environment/secrets manager
1. Restart service with new credentials
1. Verify connectivity: `GET /api/health` (HTTP, `api_server.py`; there is no health MCP tool)
1. Revoke old API key in exchange dashboard

**For Keystore:**

1. Generate new keystore with new password
1. Transfer funds from old address (if applicable)
1. Update `KEYSTORE_PATH` and `KEYSTORE_PASSWORD`
1. Restart service
1. Verify signing works in paper mode
1. Securely destroy old keystore file

**For Remote Signer:**

1. Generate new TLS certificates
1. Deploy to signer service
1. Update `SIGNER_REMOTE_URL` if endpoint changed
1. Restart ReadyTrader-Crypto
1. Verify signing: test transaction in paper mode

**For MPC Keyshares:**

1. Initiate key refresh protocol in MPC service
1. Both parties must participate in refresh
1. Verify new keyshares produce same address
1. Archive old keyshare backups securely
1. Test signing with refreshed shares

#### Step 3: Validate

```bash
# Check health
curl -s http://localhost:8000/api/health

# Check metrics
curl -s http://localhost:8000/api/metrics

# Run paper trade test
PAPER_MODE=true python -c "
from server import mcp
# Test a paper trade
"
```

#### Step 4: Resume Trading

Only after validation passes, restart both servers with `TRADING_HALTED=false`, then:

```bash
# Verify trading is enabled
curl -s http://localhost:8000/api/health | jq '.trading_halted'
# Should return: false
```

### Emergency Rotation Procedure

For suspected compromise, follow these additional steps:

1. **Immediately halt trading**: `TRADING_HALTED=true`
1. **Revoke compromised credential** before generating replacement
1. **Audit logs**: Review `/app/data/audit.db` for unauthorized activity
1. **Check balances**: Verify no unauthorized transfers
1. **Notify stakeholders**: Follow incident response procedures
1. **Generate new credentials** with different entropy source if possible
1. **Review access**: Who had access to old credentials?
1. **Document incident**: Time, scope, remediation steps

______________________________________________________________________

## MPC Keyshare Management

### Initial Setup

1. Generate keyshares using `mpc_signer/scripts/gen_certs.sh`
1. Distribute Party 0 keyshare to primary signer service
1. Distribute Party 1 keyshare to backup/approval signer service
1. **Never store both keyshares in the same location**
1. Test signing with both parties online

### Backup Strategy

| Component        | Backup Location        | Encryption | Access Control   |
| ----------------- | ----------------------- | ----------- | ----------------- |
| Party 0 Keyshare | HSM/secure enclave     | AES-256    | 2-person rule    |
| Party 1 Keyshare | Separate HSM/enclave   | AES-256    | 2-person rule    |
| Recovery Seed    | Cold storage (offline) | Shamir 3/5 | Geographic split |
| TLS Certificates | Secrets manager        | At-rest    | Service accounts |

### Key Refresh Protocol

MPC keyshares should be refreshed without changing the underlying key:

1. Schedule maintenance window
1. Ensure both parties are online and responsive
1. Initiate refresh via MPC protocol
1. Both parties generate new shares of same key
1. Verify: signing produces same signatures
1. Archive old shares (encrypted, dated)
1. Update backup copies

### Disaster Recovery

If one party's keyshare is lost:

1. **Do NOT panic** - remaining party cannot sign alone
1. Retrieve backup keyshare from secure storage
1. Restore to replacement infrastructure
1. Verify both parties can communicate
1. Test signing before resuming operations
1. Schedule immediate key refresh

If both keyshares are lost:

1. Use recovery seed to regenerate keyshares
1. This requires the Shamir threshold (e.g., 3 of 5 shares)
1. Follow initial setup procedure
1. **Address will change** - plan fund migration

______________________________________________________________________

## Audit Trail Requirements

### What to Log

| Event                   | Log Level | Retention |
| ------------------------ | --------- | --------- |
| Credential rotation     | INFO      | 2 years   |
| Failed authentication   | WARN      | 1 year    |
| Signing requests        | INFO      | 1 year    |
| Policy violations       | WARN      | 2 years   |
| Emergency halt triggers | ERROR     | 2 years   |

### Audit Database Location

```bash
AUDIT_DB_PATH=/app/data/audit.db
```

### Querying Audit Logs

```bash
# Recent signing events
sqlite3 /app/data/audit.db "SELECT * FROM events WHERE event_type='sign' ORDER BY timestamp DESC LIMIT 10;"

# Failed operations
sqlite3 /app/data/audit.db "SELECT * FROM events WHERE status='failed' ORDER BY timestamp DESC;"
```

______________________________________________________________________

## Compliance Checklist

Before going live, verify:

- [ ] No `SIGNER_TYPE=env_private_key` in production
- [ ] All CEX API keys have withdrawal disabled
- [ ] IP restrictions configured where supported
- [ ] Rotation schedule documented and calendar reminders set
- [ ] Emergency rotation procedure tested
- [ ] Backup keyshares verified and accessible
- [ ] Audit logging enabled and retention configured
- [ ] Incident response contacts documented
