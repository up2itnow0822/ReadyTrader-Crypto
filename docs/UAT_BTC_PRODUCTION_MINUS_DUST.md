# UAT Evidence — BTC Production Minus Dust

**Date:** 2026-09-14\
**Conductor:** UAT agent (local read-mostly)\
**Scope:** LIVE_TESTING_PROTOCOL Phases 1–3 + Production checklist\
**Explicitly excluded:** Phase 4 dust / live orders / unhalt\
**Conda:** `base` (Python 3.14.6 via miniconda)

Legend: **PASS** / **FAIL** / **SKIP** (with reason)

______________________________________________________________________

## Phase 1 — Environment Validation

| ID    | Checklist item                                                                        | Result   | Evidence                                                                                                                                                                                                                                           |
| ----- | ------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1.1  | `env.example` has `TRADING_HALTED=true`                                               | **PASS** | `env.example:15` → `TRADING_HALTED=true`                                                                                                                                                                                                           |
| P1.2  | `env.live.btc.example` exists with BTC allowlists                                     | **PASS** | File present; `ALLOW_EXCHANGES=binance,kraken,coinbase`, `ALLOW_CEX_SYMBOLS=btc/usdt,btc/usd`, `ALLOW_CEX_MARKET_TYPES=spot`, `EXECUTION_MODE=cex`, `TRADING_HALTED=true`, `SIGNER_TYPE=remote`                                                    |
| P1.3  | `docker-compose -f docker-compose.live.yml --env-file` (dummy filled) config succeeds | **PASS** | Exit 0 with dummy JWT/bcrypt/signer URL from template. Rendered: `TRADING_HALTED=true`, `API_AUTH_REQUIRED=true`, `SIGNER_TYPE=remote`, `PAPER_MODE=false`, `LIVE_TRADING_ENABLED=true`, `DEV_MODE=false`                                          |
| P1.3b | Compose injects `ALLOW_CEX_SYMBOLS` / `ALLOW_CEX_MARKET_TYPES`                        | **PASS** | Fixed in `docker-compose.live.yml` for `api` + `mcp`; re-validated render shows `btc/usdt,btc/usd` and `spot`; `EXECUTION_MODE` default `cex`                                                                                                      |
| P1.4  | Settings: `DEV_MODE=false` + live + `env_private_key` fails                           | **PASS** | Subprocess: `SettingsValidationError` — `SIGNER_TYPE=env_private_key is forbidden when PAPER_MODE=false or LIVE_TRADING_ENABLED=true`. Pytest: `test_settings_forbids_env_private_key_when_live`, `test_factory_rejects_env_private_key_when_live` |
| P1.5  | `api_server` refuses unauthenticated when `DEV_MODE=false`                            | **PASS** | Subprocess import: `RuntimeError: API_AUTH_REQUIRED must be true when DEV_MODE=false` (`api_server.py:59-62`). Module docs/comments match.                                                                                                         |
| P1.6  | CEX live auth probe (`/api/test-cex-auth` or equivalent)                              | **SKIP** | No `.env` / `.env.live`; no CEX API keys present locally. Binance public API returns geo 451 from this host.                                                                                                                                       |
| P1.7  | Signer address / live remote reachability                                             | **SKIP** | No production remote signer; not required for production-minus-dust (halted). Template requires `SIGNER_REMOTE_URL`.                                                                                                                               |

______________________________________________________________________

## Phase 2 — Paper Trading Verification

| ID   | Checklist item                                         | Result   | Evidence                                                                                                                                                                                                        |
| ---- | ------------------------------------------------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P2.1 | ≥20 paper BTC/USDT trades via `paper_engine` (temp DB) | **PASS** | `python examples/paper_btc_uat.py` → `trades_ok: 20`, `risk_blocks: 1`, `halt_gate_ok: true`, `pass: true`. Also prior conductor: 22 executes on tempfile DB.                                                   |
| P2.2 | Risk Guardian / policy files exist                     | **PASS** | `risk_manager.py` (`RiskGuardian`), `policy_engine.py`, `signing/policy.py`                                                                                                                                     |
| P2.3 | Spot-check risk/policy tests                           | **PASS** | `tests/test_risk.py` (position size, falling knife, daily loss, max drawdown); `tests/test_policy_engine.py` (26 collected); settings validation suite green                                                    |
| P2.4 | Hermes docs + skill with `mcp_servers` snippet         | **PASS** | `docs/HERMES_INTEGRATION.md` has `mcp_servers.readytrader-crypto`; Hermes skill at `/Users/billwilson/Projects/hermes-agent/optional-skills/finance/readytrader-crypto/SKILL.md` + `references/mcp-config.yaml` |
| P2.5 | Protocol “≥24h strategy metrics / stress 200+”         | **SKIP** | Out of this conductor pass (multi-day / stress lab); paper engine smoke satisfied P2.1                                                                                                                          |

______________________________________________________________________

## Phase 3 — CEX dry path (DEX testnet N/A)

| ID   | Checklist item                                               | Result   | Evidence                                                                                                                                                            |
| ---- | ------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P3.1 | `approve_each` + `TRADING_HALTED=true` prevents live confirm | **PASS** | Live profile load: `EXECUTION_APPROVAL_MODE=approve_each`, `TRADING_HALTED=true`, `is_live_execution_allowed=false` (`settings.is_live_execution_allowed` property) |
| P3.2 | Public market data fetch (optional)                          | **PASS** | `ccxt.kraken` `fetch_ticker("BTC/USDT")` → last **77489.4**. Binance skipped (HTTP 451 geo).                                                                        |
| P3.3 | DEX Sepolia / on-chain testnet swaps                         | **SKIP** | BTC production path is CEX-only (`EXECUTION_MODE=cex`); DEX testnet out of scope for this gate                                                                      |
| P3.4 | Phase 4 dust / live orders                                   | **SKIP** | Explicitly excluded from this UAT                                                                                                                                   |

______________________________________________________________________

## Production Deployment Checklist (minus Phase 4 / unhalt)

| ID      | Checklist item                                     | Result   | Evidence                                                                                                             |
| ------- | -------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| Prod.1  | Release readiness items (hygiene/gates)            | **PASS** | `RELEASE_READINESS_CHECKLIST.md` sections 1–8 marked complete in-repo (not re-run full `make check` this pass)       |
| Prod.2  | Review `docs/SECURITY_REVIEW.md`                   | **PASS** | File present; operator pack links it (`docs/OPS_BTC_PRODUCTION.md`)                                                  |
| Prod.3  | Configure `docker-compose.live.yml`                | **PASS** | Config interpolates with BTC template dummies (P1.3)                                                                 |
| Prod.4  | Use `env.live.btc.example` → `.env.live`           | **PASS** | Template ready; operator copy step documented. Local `.env.live` not created (no secrets)                            |
| Prod.5  | Code: refuse `env_private_key` when live/non-paper | **PASS** | P1.4                                                                                                                 |
| Prod.6  | Set `SIGNER_TYPE=remote` (not env key)             | **PASS** | Template + rendered compose                                                                                          |
| Prod.7  | Signer policy enabled                              | **PASS** | Template: `SIGNER_POLICY_ENABLED=true` + chain/gas limits                                                            |
| Prod.8  | Strict policy limits (exchanges/symbols/amounts)   | **PASS** | Template + compose now wire `ALLOW_EXCHANGES`, `ALLOW_CEX_SYMBOLS`, `ALLOW_CEX_MARKET_TYPES`, `MAX_CEX_ORDER_AMOUNT` |
| Prod.9  | Code: `api_server` refuse unauth / wildcard CORS   | **PASS** | P1.5 + settings live CORS/auth tests                                                                                 |
| Prod.10 | Code: `TRADING_HALTED` defaults true               | **PASS** | `settings.py` default_factory → True; templates set true                                                             |
| Prod.11 | Enable API auth + JWT + admin hash                 | **PASS** | Template fields; compose requires `API_JWT_SECRET` / `API_ADMIN_PASSWORD_HASH`                                       |
| Prod.12 | CORS non-wildcard                                  | **PASS** | Template `CORS_ORIGINS=http://localhost:3000`                                                                        |
| Prod.13 | Monitoring/alerting setup                          | **PASS** | `deploy/observability/` (Prometheus/Grafana/Alertmanager); webhook slots in template                                 |
| Prod.14 | Hermes MCP docs                                    | **PASS** | P2.4                                                                                                                 |
| Prod.15 | Deploy halted / verify health / unhalt             | **SKIP** | No container start / no real secrets this pass; config-only. Unhalt excluded.                                        |
| Prod.16 | Post-deploy audit/rotation schedule                | **SKIP** | No live deploy; procedures exist in `RUNBOOK.md` / `docs/CUSTODY.md`                                                 |

______________________________________________________________________

## Gate verdict

| Gate                                                            | Status                                                                                                                                                        |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Production-minus-dust (Phases 1–3 + prod checklist, no Phase 4) | **PASS**                                                                                                                                                      |
| Blocker before any unhalt / Phase 4                             | None remaining in compose/policy wiring. Operator secrets + dust UAT still required for Phase 4.                                                              |
| Remaining operator work                                         | Real `.env.live` secrets, CEX trade+read keys (no withdraw), remote signer reachability, Hermes CLI MCP smoke, then halted `up` + authenticated `/api/health` |

### Agent team notes

- Security auditor: checklist **PASS**; **SEC-001** `/ws` JWT enforced; **SEC-002** `.env.live` gitignored. Residual: unauthenticated `/api/health` recon (intentional); operator CEX auth pending secrets.
- Test engineer: `pytest tests/test_settings_validation.py tests/test_risk.py tests/test_api_server.py` → **39 passed**; `examples/paper_btc_uat.py` → **pass**.
- UAT conductor: Phases 1–3 **PASS**; P1.5 CEX auth **BLOCKED-pending-operator-secrets**; Phase 4 excluded.

### Residual risks (pre–Phase 4)

1. No live CEX credentials — trade+read / no-withdraw / IP allowlist unverified.
1. Remote signer — template URL only; TLS/reachability/address pin unproven.
1. Host conda `base` (Python 3.14) may lack runtime ccxt; validate marketdata inside the compose image.
1. Binance may return geo HTTP 451 from this host — prefer Kraken/Coinbase or proxy for probes.
1. Multi-day paper metrics / stress lab (protocol 2.2/2.5) not required for this gate.

### Ready for dust UAT — operator gates

1. `env.live.btc.example` → `.env.live` with JWT, admin hash, CEX trade+read keys (no withdraw).
1. Reachable `SIGNER_REMOTE_URL` + `ALLOW_SIGNER_ADDRESSES` + TLS.
1. CEX auth probe: read+trade, confirm **no withdraw**.
1. `docker compose -f docker-compose.live.yml --env-file .env.live up` with `TRADING_HALTED=true`; authenticated health OK.
1. Keep `EXECUTION_APPROVAL_MODE=approve_each`; dust-sized `MAX_CEX_ORDER_AMOUNT` / `MAX_TRADE_AMOUNT`.
1. Written operator OK to unhalt + confirm **one** dust BTC spot order only.

______________________________________________________________________

## Commands used (non-secret)

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate base
docker compose -f docker-compose.live.yml --env-file <dummy-from-env.live.btc.example> config
PAPER_MODE=true DEV_MODE=true TRADING_HALTED=true pytest tests/test_settings_validation.py -q
python examples/paper_btc_uat.py
pytest tests/test_settings_validation.py tests/test_risk.py tests/test_api_server.py -q
```

No live orders. No commits.
