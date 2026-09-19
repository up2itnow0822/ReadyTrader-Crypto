## ReadyTrader-Crypto — Release Readiness Checklist

This checklist is meant to be used before any public release or major announcement. It focuses on trust, safety, and reproducibility.

### 1) Scope & versioning

- [x] **Define release scope** (features included, features explicitly excluded)
- [x] **Version bump** in `pyproject.toml` (and/or tag strategy documented)
- [x] **Changelog entry** created (what changed, what broke, what to watch)

### 2) Repo hygiene & governance

- [x] **License present** (`LICENSE`)
- [x] **Prominent disclaimer** present (`README.md` + `DISCLAIMER.md`)
- [x] **Security policy** present (`SECURITY.md`)
- [x] **Contributing guide** present (`CONTRIBUTING.md`)
- [x] **CI is required** for PRs (branch protection recommended)
- [x] **No secrets in repo** (scan git history if needed)

### 3) Build & install reproducibility

- [x] `requirements.txt` is **runtime-only** and pinned
- [x] `requirements-dev.txt` exists for **tests + lint + security tooling**
- [x] `Dockerfile` builds cleanly from scratch (no missing files)
- [x] `.dockerignore` excludes secrets/tests/CI-only artifacts
- [x] `python-version` matches `pyproject.toml` (`>=3.12`)

### 4) Documentation completeness (minimum viable trust)

- [x] **README is accurate** (features, limitations, supported venues, safety model)
- [x] **Full tool catalog** exists and is up-to-date (`docs/TOOLS.md`)
- [x] **Configuration template** exists (`env.example`) and matches code
- [x] **Runbook** exists and is practical (`RUNBOOK.md`)
- [x] "How to run checks locally" documented (`CONTRIBUTING.md`)

### 5) Safety & live-trading governance

- [x] **Safe default**: `PAPER_MODE=true` (no live execution by default)
- [x] **Live gating works**:
  - [x] `LIVE_TRADING_ENABLED=true` required
  - [x] `TRADING_HALTED=true` halts execution
  - [x] Risk disclosure consent required (per process)
- [x] **Approval mode works**:
  - [x] `EXECUTION_APPROVAL_MODE=approve_each` returns proposals
  - [x] replay protection (single-use token) and TTL enforced
- [x] **Policy engine rules** documented and verified (allowlists/limits)
- [x] **Signer abstraction** documented (env key / keystore / remote signer)

### 6) Quality gates (must be green)

- [x] Lint: `ruff check .`
- [x] Tests: `pytest -q`
- [x] Security static scan: `bandit -q -r . -c bandit.yaml`
- [x] Dependency audit: `pip-audit -r requirements.txt`
- [x] GitHub Actions CI run is green on `main`

### 7) Operator readiness (minimum)

- [x] `GET /api/health` (HTTP, `api_server.py`) returns healthy state in paper mode
- [x] `GET /api/metrics` (HTTP, `api_server.py`, JWT-protected) returns sane counters/timers after tool usage
- [x] Websocket streams can be started/stopped without crashing the process
- [x] Clear troubleshooting steps exist in `RUNBOOK.md`

### 8) Release packaging & distribution

- [x] Tag release (or document why tags aren't used yet)
- [x] GitHub Release notes include:
  - [x] upgrade steps
  - [x] breaking changes
  - [x] safety reminders (paper first)
- [x] Announcement copy uses "safe claims" (see `docs/POSITIONING.md`)

______________________________________________________________________

## Production Deployment Checklist

Use this additional checklist when deploying to production with live trading enabled.

### Pre-Deployment

- [ ] Complete all items above
- [ ] Review `docs/SECURITY_REVIEW.md` checklist
- [ ] Configure `docker-compose.live.yml` (not the default compose file)
- [ ] Use BTC profile template `env.live.btc.example` → `.env.live` (CEX spot BTC)
- [x] **Code-enforced:** `SIGNER_TYPE=env_private_key` refused when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`
- [ ] Set `SIGNER_TYPE=remote` (or keystore / cb_mpc_2pc) — never `env_private_key`
- [ ] Configure signer policy (`SIGNER_POLICY_ENABLED=true`)
- [ ] Set strict policy limits:
  - [ ] `ALLOW_CHAINS` (DEX only; e.g., `ethereum`)
  - [ ] `ALLOW_TOKENS` (DEX only)
  - [ ] `ALLOW_EXCHANGES` (e.g., `binance,kraken,coinbase`)
  - [ ] `ALLOW_CEX_SYMBOLS` (e.g., `btc/usdt,btc/usd`)
  - [ ] `MAX_TRADE_AMOUNT` / `MAX_CEX_ORDER_AMOUNT`
- [x] **Code-enforced:** `api_server` refuses start when `DEV_MODE=false` and (`API_AUTH_REQUIRED=false` or CORS `*`)
- [x] **Code-enforced:** live/non-paper + `DEV_MODE=false` requires auth + non-wildcard CORS in settings
- [x] **Code-enforced:** `TRADING_HALTED` defaults to `true`
- [ ] Enable API authentication (`API_AUTH_REQUIRED=true`) + JWT secret + admin hash
- [ ] Configure CORS origins (no wildcards)
- [ ] Set up monitoring/alerting (Discord/Telegram webhooks or Prometheus scrape)
- [ ] Hermes MCP: see `docs/HERMES_INTEGRATION.md` (paper-first; live tools gated)

### Deployment

- [ ] Deploy with `TRADING_HALTED=true` initially
- [ ] Verify `GET /api/health` returns healthy
- [ ] Verify policy limits with small test trades (paper mode)
- [ ] Enable trading (`TRADING_HALTED=false`) only after validation

### Post-Deployment

- [ ] Monitor audit logs for anomalies
- [ ] Set up automated security scan schedule (daily)
- [ ] Document incident response procedures
- [ ] Schedule credential rotation (see `docs/CUSTODY.md`)

______________________________________________________________________

## Verification Commands

```bash
# Run all quality gates
make check

# Run security scans
make security

# Test Docker build
make docker-build && make docker-test

# Verify documentation
python tools/verify_docs.py
```
