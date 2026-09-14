# Hermes Integration — ReadyTrader-Crypto

Connect [Hermes Agent](https://github.com/up2itnow0822/hermes-agent) to ReadyTrader-Crypto as a **stdio MCP server**. Do not add ReadyTrader tools to Hermes core; capability stays at the MCP edge plus an optional skill.

## Prerequisites

1. Clone and install ReadyTrader-Crypto (`make setup`, Python ≥ 3.12).
2. Paper-first `.env` from `env.example`:

```bash
PAPER_MODE=true
LIVE_TRADING_ENABLED=false
TRADING_HALTED=true
DEV_MODE=true
EXECUTION_MODE=cex
RISK_PROFILE=conservative
EXECUTION_APPROVAL_MODE=approve_each
ALLOW_EXCHANGES=binance,kraken,coinbase
ALLOW_CEX_SYMBOLS=btc/usdt,btc/usd
ALLOW_CEX_MARKET_TYPES=spot
```

3. Hermes installed with a writable `~/.hermes/config.yaml` (or active profile).

## `mcp_servers` config (copy-paste)

Add to `~/.hermes/config.yaml` (adjust `READYTRADER_ROOT`):

```yaml
mcp_servers:
  readytrader-crypto:
    command: python
    args:
      - app/main.py
    cwd: /Users/billwilson/Projects/ReadyTrader-Crypto   # set to your clone
    timeout: 120
    connect_timeout: 60
    env:
      PAPER_MODE: "true"
      LIVE_TRADING_ENABLED: "false"
      TRADING_HALTED: "true"
      DEV_MODE: "true"
      EXECUTION_MODE: "cex"
      RISK_PROFILE: "conservative"
      EXECUTION_APPROVAL_MODE: "approve_each"
      ALLOW_EXCHANGES: "binance,kraken,coinbase"
      ALLOW_CEX_SYMBOLS: "btc/usdt,btc/usd"
      ALLOW_CEX_MARKET_TYPES: "spot"
      # Pass CEX keys only if you need authenticated paper/read probes:
      # CEX_BINANCE_API_KEY: "..."
      # CEX_BINANCE_API_SECRET: "..."
```

Restart the Hermes session so MCP tools load. Tool names appear as `mcp_readytrader-crypto_*` (or host-specific prefix).

### Docker alternative

If the MCP process should run in Docker paper compose instead of host Python, point `command` at a wrapper that runs `docker compose exec` / `docker run` against the paper stack. Prefer host stdio for local UAT.

## Optional skill

Canonical public skill package: [readytrader-crypto-hermes](https://github.com/up2itnow0822/readytrader-crypto-hermes).

Install into Hermes as `optional-skills/finance/readytrader-crypto/`:

```bash
git clone https://github.com/up2itnow0822/readytrader-crypto-hermes.git \
  optional-skills/finance/readytrader-crypto
```

It teaches paper BTC workflow, kill-switch rules, and forbids enabling live trading without explicit operator confirmation.

## Safe tool set (pre–Phase 4 dust)

Prefer these until dust UAT is authorized:

| Tool | Use |
|------|-----|
| `get_health` | Liveness / mode flags |
| `get_metrics_snapshot` | Counters after paper activity |
| `get_crypto_price` / `fetch_ohlcv` | BTC market data |
| `deposit_paper_funds` | Seed paper wallet |
| `validate_trade_risk` | Risk Guardian checks |
| Paper order / portfolio tools | Simulated BTC/USDT path |

Defer or block until Phase 4:

- `place_cex_order` / cancel / replace with live credentials and `PAPER_MODE=false`
- Any tool that signs on-chain with a live signer
- Setting `TRADING_HALTED=false` or `LIVE_TRADING_ENABLED=true`

## FastAPI + JWT (optional)

Hermes can also call the HTTP API (`api_server.py`) with Bearer JWT when `API_AUTH_REQUIRED=true`. For production API, `DEV_MODE=false` refuses start without auth and non-wildcard CORS. MCP paper path does not require JWT.

## Smoke checklist

1. Hermes lists ReadyTrader MCP tools.
2. `get_health` reports `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, halted or paper-safe.
3. `get_crypto_price` (or ticker) for BTC works.
4. Paper deposit + ≥1 paper BTC/USDT path succeeds.
5. With `TRADING_HALTED=true` and live flags off, live CEX place is blocked.

## Production (halted) profile

For live compose still halted, use `env.live.btc.example` → `.env.live` and `docker-compose.live.yml`. Keep Hermes MCP on a **separate paper** process, or point MCP env at the live stack only with `TRADING_HALTED=true` and never confirm live proposals until Phase 4.

See `RUNBOOK.md` (BTC CEX path) and `docs/LIVE_TESTING_PROTOCOL.md`.
