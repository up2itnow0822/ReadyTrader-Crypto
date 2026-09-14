# BTC Production Operator Pack (no dust trades)

Halt-first production posture for spot BTC via CEX. Secrets stay out of git.

## 1. Env and policy

```bash
cp env.live.btc.example .env.live
# Fill: API_JWT_SECRET, API_ADMIN_PASSWORD_HASH, SIGNER_REMOTE_URL,
# CEX_* trade+read keys (NO withdraw), CORS_ORIGINS, webhooks
```

Policy baked into the template:

- `EXECUTION_MODE=cex`
- `ALLOW_EXCHANGES=binance,kraken,coinbase`
- `ALLOW_CEX_SYMBOLS=btc/usdt,btc/usd`
- `ALLOW_CEX_MARKET_TYPES=spot`
- `MAX_CEX_ORDER_AMOUNT=0.01`
- `EXECUTION_APPROVAL_MODE=approve_each`
- `TRADING_HALTED=true`

## 2. CEX key hygiene

- Create API keys with **trade + read only**
- Disable withdraw / transfer
- Enable IP allowlist at the exchange
- Store secrets in `.env.live` or a vault — never commit
- Rotate per `docs/CUSTODY.md`

## 3. Validate compose (no start required for config check)

```bash
docker-compose -f docker-compose.live.yml --env-file .env.live config >/dev/null
```

Start halted (optional; needs real JWT/signer/CEX values):

```bash
docker-compose -f docker-compose.live.yml --env-file .env.live up -d
curl -s -H "Authorization: Bearer $JWT" http://localhost:8000/api/health
# Expect trading_halted true; do not set TRADING_HALTED=false
```

Remote signer: only verify URL reachability / TLS — do not sign live txs in this pack.

## 4. Monitoring

Bundled stack: `deploy/observability/`

```bash
cd deploy/observability && docker-compose up -d
# prometheus.yml scrapes ReadyTrader metrics; grafana-dashboard.json included
```

Webhooks (optional): set `DISCORD_WEBHOOK_URL` or Telegram vars in `.env.live`.
Smoke: trigger a paper tool error or health poll and confirm alert path if configured.

## 5. Incident / rotation

- Kill switch: `TRADING_HALTED=true` + restart (`RUNBOOK.md`)
- Credential rotation: `docs/CUSTODY.md`
- Security checklist: `docs/SECURITY_REVIEW.md`

## 6. Explicitly out of scope here

- Phase 4 dust live orders
- Unhalting for real capital
- Hermes confirming live `confirm_execution`
