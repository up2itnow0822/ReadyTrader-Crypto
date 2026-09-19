# Security Review Checklist

This document provides a comprehensive security review checklist for deploying
ReadyTrader-Crypto with real funds. **Do not trade with real funds until all
applicable items are verified.**

## Pre-Production Security Checklist

### 1. Key Custody ✅

- [ ] **Signer Type Selection**

  - [x] NOT using `SIGNER_TYPE=env_private_key` in production
    - **Enforced:** settings + `signing/factory.py` refuse `env_private_key` when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`
  - [ ] Using `keystore`, `remote`, or `cb_mpc_2pc` signer type
  - [ ] Keystore file encrypted with strong passphrase (if applicable)
  - [ ] Remote signer URL uses HTTPS with valid certificate (if applicable)

- [ ] **Signer Address Pinning**

  - [ ] `ALLOW_SIGNER_ADDRESSES` is set to expected wallet address(es)
  - [ ] Verified signer address matches intended trading wallet

- [ ] **CEX API Keys**

  - [ ] Keys created with **least privilege** (trade-only, no withdrawal)
  - [ ] IP restrictions enabled (if exchange supports it)
  - [ ] API keys stored in secure secrets manager (not plaintext files)

### 2. Policy Engine Configuration ✅

- [ ] **Chain Allowlists**

  - [ ] `ALLOW_CHAINS` is set to only required chains (e.g., `ethereum,polygon`)
  - [ ] No wildcard or "all chains" configuration

- [ ] **Token Allowlists**

  - [ ] `ALLOW_TOKENS` is set to only approved tokens
  - [ ] Exotic/meme tokens excluded unless explicitly intended

- [ ] **Trade Limits**

  - [ ] `MAX_TRADE_AMOUNT` is set to reasonable limit
  - [ ] Per-token limits (`MAX_TRADE_AMOUNT_<TOKEN>`) configured if needed

- [ ] **Exchange Allowlists**

  - [ ] `ALLOW_EXCHANGES` restricts to intended exchanges only
  - [ ] `ALLOW_CEX_SYMBOLS` restricts tradeable pairs if needed

### 3. Signer Policy (Defense in Depth) ✅

- [ ] **Signing Guardrails Enabled**
  - [ ] `SIGNER_POLICY_ENABLED=true`
  - [ ] `ALLOW_SIGN_CHAIN_IDS` restricts to intended chains
  - [ ] `ALLOW_SIGN_TO_ADDRESSES` restricts approved contracts/addresses
  - [ ] `MAX_SIGN_VALUE_WEI` caps native token transfers
  - [ ] `MAX_SIGN_GAS` prevents excessive gas consumption
  - [ ] `DISALLOW_SIGN_CONTRACT_CREATION=true` (unless deploying contracts)

### 4. Risk Controls ✅

- [ ] **Position Limits**

  - [ ] Max 5% portfolio per trade (enforced by RiskGuardian)
  - [ ] Verified with test trades in paper mode

- [ ] **Loss Limits**

  - [ ] Daily loss limit (5%) configured and tested
  - [ ] Max drawdown (10%) kill switch verified

- [ ] **Falling Knife Protection**

  - [ ] Sentiment-based trade blocking enabled
  - [ ] Threshold set appropriately for strategy

### 5. Operational Controls ✅

- [ ] **Kill Switch**

  - [x] `TRADING_HALTED=true` as default startup state
    - **Enforced:** settings default `TRADING_HALTED=true`
  - [ ] Manual enable required to begin trading
  - [ ] Verified kill switch halts all trading immediately

- [ ] **Approval Gates**

  - [ ] `EXECUTION_APPROVAL_MODE=approve_each` for initial deployment
  - [ ] Manual approval UI/process tested and accessible

- [ ] **Monitoring & Alerts**

  - [ ] Prometheus metrics endpoint enabled (`/metrics`)
  - [ ] Grafana dashboards configured
  - [ ] Alertmanager rules set up for critical conditions:
    - [ ] Trading halted alerts
    - [ ] Loss limit approaching alerts
    - [ ] Connection failure alerts
    - [ ] Unusual volume/activity alerts

### 6. Infrastructure Security ✅

- [ ] **Network**

  - [x] API endpoints behind authentication (`API_AUTH_REQUIRED=true`)
    - **Enforced:** `api_server` refuses start when `DEV_MODE=false` without auth; live/non-paper settings also require auth
  - [x] WebSocket `/ws` requires JWT when `API_AUTH_REQUIRED=true` (prefer `Authorization: Bearer`; `?token=` is browser fallback only — can leak via logs/proxies)
    - **Enforced:** `api_server.websocket_endpoint` closes with 1008 if token missing/invalid
  - [x] CORS configured to specific origins (not `*`)
    - **Enforced:** `api_server` + live settings reject CORS `*` when `DEV_MODE=false`
  - [ ] TLS/HTTPS for all external connections
  - [ ] Private network for internal services

- [ ] **Secrets Management**

  - [ ] All secrets in environment variables or secrets manager
  - [ ] No secrets in source code, config files, or logs
  - [x] `.env` / `.env.live` / `.env.*.local` gitignored (templates `env*.example` stay tracked)

- [ ] **Container Security**

  - [ ] Running as non-root user
  - [ ] Read-only root filesystem (if applicable)
  - [ ] Trivy scan passed with no CRITICAL/HIGH vulnerabilities

### 7. Code & Dependencies ✅

- [ ] **Dependency Audit**

  - [ ] `pip-audit` shows no known vulnerabilities
  - [ ] `npm audit` shows 0 vulnerabilities, including `devDependencies` (frontend; PR CI / `make security`)
  - [ ] Dependencies pinned to specific versions (`requirements.lock.txt`)

- [ ] **Static Analysis**

  - [ ] Bandit security scan passed
  - [ ] No secrets detected by TruffleHog
  - [ ] CodeQL analysis completed

- [ ] **Code Review**

  - [ ] All execution path code reviewed
  - [ ] Signing logic reviewed by security-aware developer
  - [ ] Policy engine configuration reviewed

### 8. Testing & Validation ✅

- [ ] **Paper Trading Validation**

  - [ ] Complete paper trading run with realistic scenarios
  - [ ] All trade types executed successfully
  - [ ] Risk controls triggered correctly in test scenarios

- [ ] **Testnet/Sandbox Validation** (if applicable)

  - [ ] DEX swaps tested on testnet
  - [ ] CEX orders tested on exchange sandbox
  - [ ] Error conditions tested (timeouts, rate limits, rejections)

- [ ] **Integration Tests**

  - [ ] All integration tests pass
  - [ ] Operational safeguards test suite passes
  - [ ] Coverage ≥55% on critical modules

### 9. Documentation ✅

- [ ] **Runbook**

  - [ ] `RUNBOOK.md` reviewed and accurate
  - [ ] Incident response procedures documented
  - [ ] Contact information up to date

- [ ] **Configuration Documentation**

  - [ ] All environment variables documented
  - [ ] Default values clearly stated
  - [ ] Security implications noted for each setting

______________________________________________________________________

## Ongoing Security Practices

### Daily (Automated)

- [x] Security audit workflow runs automatically (pip-audit, Bandit, npm audit, Trivy, CodeQL)
- [x] SBOM generation for Python and frontend dependencies

### Weekly

- [ ] Review automated security audit results and address any findings
- [ ] Review audit logs for anomalies
- [ ] Verify monitoring/alerting is functioning

### Monthly

- [ ] Rotate API keys (CEX and any external services)
- [ ] Review and update allowlists if needed
- [ ] Dependency updates and security patches

### Quarterly

- [ ] Full security review against this checklist
- [ ] Penetration testing (if applicable)
- [ ] Review and update threat model

______________________________________________________________________

## Security Contact

For security vulnerabilities, see [SECURITY.md](../SECURITY.md).

Do **not** open public issues for security matters.
