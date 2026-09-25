# Hermes Integration — ReadyTrader-Crypto

Connect [Hermes Agent](https://github.com/up2itnow0822/hermes-agent) to
[ReadyTrader-Crypto](https://github.com/up2itnow0822/ReadyTrader-Crypto) as a **stdio MCP
server**. Do not add ReadyTrader tools to Hermes core; capability stays at the MCP edge plus
the optional skill package
([readytrader-crypto-hermes](https://github.com/up2itnow0822/readytrader-crypto-hermes)).

Everything below was verified on 2026-09-25 against ReadyTrader-Crypto with PR #20 (the Risk
Guardian in every order path) and the hermes-agent source (`tools/mcp_tool.py`,
`tools/skills_hub.py`), by running the Hermes CLI and Hermes's own MCP tool layer against the
server.

## Prerequisites

1. Clone ReadyTrader-Crypto and install it into its own virtualenv (Python ≥ 3.12):

```bash
git clone https://github.com/up2itnow0822/ReadyTrader-Crypto.git
cd ReadyTrader-Crypto
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`make setup` installs into whatever `pip` is on your PATH; it does not create a venv.
Hermes spawns the MCP process itself, so point the config at an interpreter that has the
dependencies (`.venv/bin/python`, or `.venv\Scripts\python.exe` on Windows).

2. Paper-first flags. The Hermes `env:` block below supplies all of them; no `.env` and no
   exchange keys are required for the paper profile.

```bash
PAPER_MODE=true
LIVE_TRADING_ENABLED=false
TRADING_HALTED=true
DEV_MODE=false
EXECUTION_MODE=cex
EXECUTION_APPROVAL_MODE=approve_each
ALLOW_EXCHANGES=binance,kraken,coinbase
ALLOW_CEX_SYMBOLS=btc/usdt,btc/usd
ALLOW_CEX_MARKET_TYPES=spot
```

`DEV_MODE=false` is safe for the stdio MCP paper path with these defaults
(`API_AUTH_REQUIRED` is false). `Settings._validate()` only raises when `DEV_MODE=false`
is combined with `API_AUTH_REQUIRED=true` and no `API_JWT_SECRET`, or with a live/non-paper
profile; `api_server.py` additionally refuses to start without auth. Set `DEV_MODE=true`
only for a local HTTP API without JWT.

3. Hermes installed with a writable `~/.hermes/config.yaml` (or active profile).

## `mcp_servers` config (copy-paste)

Add to `~/.hermes/config.yaml` (set `command` and `cwd` to your clone):

```yaml
mcp_servers:
  readytrader-crypto:
    command: /path/to/ReadyTrader-Crypto/.venv/bin/python
    args:
      - server.py
    cwd: /path/to/ReadyTrader-Crypto
    timeout: 120
    connect_timeout: 60
    env:
      PAPER_MODE: "true"
      LIVE_TRADING_ENABLED: "false"
      TRADING_HALTED: "true"
      DEV_MODE: "false"
      EXECUTION_MODE: "cex"
      EXECUTION_APPROVAL_MODE: "approve_each"
      ALLOW_EXCHANGES: "binance,kraken,coinbase"
      ALLOW_CEX_SYMBOLS: "btc/usdt,btc/usd"
      ALLOW_CEX_MARKET_TYPES: "spot"
      # Only if you need authenticated exchange probes (never withdraw-capable keys):
      # CEX_BINANCE_API_KEY: "..."
      # CEX_BINANCE_API_SECRET: "..."
```

Notes:

- The entrypoint is `server.py` (canonical, works on every revision). `python app/main.py`
  failed with `ModuleNotFoundError: No module named 'server'` on revisions before the
  September 2026 paper-path fix because Python puts `app/` on `sys.path`, not the repo root;
  `python -m app.main` also works.
- `timeout` is the per-tool-call limit in seconds (Hermes default 300). `connect_timeout`
  is the startup handshake limit (default 60).
- Hermes merges `env:` over a minimal default environment (`PATH`, `HOME`, …); it does not
  inherit your shell's full environment.

Start a **new** Hermes session so MCP tools load. Tools register as
`mcp__readytrader_crypto__<tool>` — server-name hyphens become underscores and the delimiter
is a double underscore (`mcp__readytrader_crypto__get_crypto_price`).

### Docker alternative

From ReadyTrader-Crypto PR #20 the image's default command serves MCP over stdio. Build it
once in the clone (`docker build -t readytrader-crypto .`) and let Hermes start one container
per session. Hermes hands its `env:` block to the `docker` command, so name each variable with
`-e` to pass it into the container, and mount a named volume so the paper account survives
between sessions:

```yaml
mcp_servers:
  readytrader-crypto:
    command: docker
    args: [run, -i, --rm,
           -e, PAPER_MODE, -e, LIVE_TRADING_ENABLED, -e, TRADING_HALTED, -e, DEV_MODE,
           -e, EXECUTION_MODE, -e, EXECUTION_APPROVAL_MODE,
           -e, ALLOW_EXCHANGES, -e, ALLOW_CEX_SYMBOLS, -e, ALLOW_CEX_MARKET_TYPES,
           -v, "readytrader-crypto-data:/app/data", readytrader-crypto]
    timeout: 120
    connect_timeout: 60
    env:
      PAPER_MODE: "true"
      LIVE_TRADING_ENABLED: "false"
      TRADING_HALTED: "true"
      DEV_MODE: "false"
      EXECUTION_MODE: "cex"
      EXECUTION_APPROVAL_MODE: "approve_each"
      ALLOW_EXCHANGES: "binance,kraken,coinbase"
      ALLOW_CEX_SYMBOLS: "btc/usdt,btc/usd"
      ALLOW_CEX_MARKET_TYPES: "spot"
```

Do not wrap `docker compose exec` instead: an exec'd process takes the container's
environment, not the one Hermes passes, so the paper-profile flags would silently not apply.
Host stdio (above) is simpler for local use.

## Optional skill

Install the skill into `~/.hermes/skills/` (the runtime skill directory):

```bash
hermes skills install up2itnow0822/readytrader-crypto-hermes/skills/finance/readytrader-crypto --category finance
```

Or copy `skills/finance/readytrader-crypto/` from a clone of readytrader-crypto-hermes into
`~/.hermes/skills/finance/`. The skill teaches the paper BTC procedure, the tool safety
classes, and refuses live trading without explicit operator authorization.

## MCP tools (verified list)

ReadyTrader registers 29 tools. Paper-safe without credentials:

| Tool                                                                                         | Use                                                            |
| -------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `get_crypto_price`, `fetch_ohlcv`                                                            | BTC market data                                                |
| `get_sentiment`, `get_news`, `get_social_sentiment`, `get_financial_news`, `get_free_news`   | Read-only context (the keyed sources need provider keys)       |
| `get_market_regime`, `run_backtest_simulation`, `post_market_insight`, `get_latest_insights` | Analysis and shared insights                                   |
| `deposit_paper_funds`                                                                        | Seed the paper wallet (response includes balance)              |
| `validate_trade_risk`                                                                        | Risk Guardian check                                            |
| `place_cex_order`                                                                            | Paper order at the market price (a limit only when marketable) |
| `get_cex_capabilities`                                                                       | Public exchange metadata, no auth                              |

Without provider keys `get_news`, `get_social_sentiment` and `get_financial_news` answer
`not_configured` (`ok: false`): no data, not an outage.

`get_cex_balance` shows the paper wallet in paper mode. The live-account tools answer
`paper_mode_not_supported` when `PAPER_MODE=true` (paper orders fill at once and never rest on an
exchange): `get_cex_order`, `list_cex_open_orders`, `list_cex_orders`, `get_cex_my_trades`,
`wait_for_cex_order`, `cancel_cex_order`, `cancel_all_cex_orders`, `replace_cex_order`,
`start_cex_private_ws`, `stop_cex_private_ws`, `list_cex_private_updates`, `transfer_eth`. Out of scope for a
BTC/CEX profile: `swap_tokens` (DEX; its paper branch does route to the paper engine).

Older revisions (before ReadyTrader-Crypto PR #20) differ: the keyed news tools answer `ok: true`
with an "Unavailable … not configured" sentence, a paper market order fills at any `price` it is
given and a paper limit fills at its own price, the order reads and writes above fail with
`cex_error` instead of `paper_mode_not_supported`, and `docker build .` builds the HTTP API
rather than the stdio MCP server.

Note that `ALLOW_EXCHANGES`, `ALLOW_CEX_SYMBOLS`, and `ALLOW_CEX_MARKET_TYPES` are enforced by
the policy engine on the **live** order path only; paper orders are not filtered by them.
Setting them keeps the profile correct if an operator ever flips to live, but the agent
must self-enforce BTC-only in paper mode.

There are **no** `get_health`, `get_metrics_snapshot`, `list_pending_executions`, or
`confirm_execution` MCP tools. Health, metrics, portfolio, and approval live only on the
HTTP API (`api_server.py`): `GET /api/health`, `GET /api/metrics`, `GET /api/portfolio`,
`GET /api/pending-approvals`, `POST /api/approve-trade`.

Defer or block until Phase 4:

- Any order tool against a process with `PAPER_MODE=false`
- Any tool that signs on-chain with a live signer
- Setting `TRADING_HALTED=false` or `LIVE_TRADING_ENABLED=true`

## FastAPI + JWT (optional)

Hermes can also call the HTTP API (`api_server.py`) with a Bearer JWT when
`API_AUTH_REQUIRED=true`. With `DEV_MODE=false`, `api_server.py` refuses to start without
auth and non-wildcard CORS. The MCP paper path does not use the HTTP API and needs no JWT.

## Smoke checklist

1. A fresh Hermes session lists `mcp__readytrader_crypto__*` tools: the server's 29, plus the four
   resource and prompt helpers Hermes adds because the server advertises those capabilities.
1. `get_crypto_price(symbol="BTC/USDT")` returns `ok: true` with the numeric price in `data.price`
   (and the sentence `The current price of BTC/USDT is <price> (Source: …)` in `data.result`).
1. `deposit_paper_funds(asset="USDT", amount=10000)` returns the updated balance.
1. `validate_trade_risk(side="buy", symbol="BTC/USDT", amount_usd=100, portfolio_value=10000)` returns a verdict.
1. `place_cex_order(symbol="BTC/USDT", side="buy", amount=0.001, order_type="market")` (no `price`)
   returns `"mode": "paper"` and a fill at the market price.
1. `~/.hermes/config.yaml` still shows `PAPER_MODE: "true"`, `LIVE_TRADING_ENABLED: "false"`,
   `TRADING_HALTED: "true"`.

The kill switch cannot be exercised from the paper profile (paper orders bypass the live
guard by design). Its behavior is asserted in ReadyTrader-Crypto's own test suite and the
Phase 4 protocol, not in this checklist.

## Production (halted) profile

For the live compose stack still halted, use `env.live.btc.example` → `.env.live` and
`docker-compose.live.yml`. Keep Hermes MCP on a **separate paper** process. Never point
the MCP entry at the live stack from this skill, and never approve live proposals until
Phase 4.

See ReadyTrader-Crypto
[`RUNBOOK.md`](https://github.com/up2itnow0822/ReadyTrader-Crypto/blob/main/RUNBOOK.md),
[`docs/LIVE_TESTING_PROTOCOL.md`](https://github.com/up2itnow0822/ReadyTrader-Crypto/blob/main/docs/LIVE_TESTING_PROTOCOL.md),
[`docs/OPS_BTC_PRODUCTION.md`](https://github.com/up2itnow0822/ReadyTrader-Crypto/blob/main/docs/OPS_BTC_PRODUCTION.md),
[`docs/UAT_BTC_PRODUCTION_MINUS_DUST.md`](https://github.com/up2itnow0822/ReadyTrader-Crypto/blob/main/docs/UAT_BTC_PRODUCTION_MINUS_DUST.md),
and [`docs/TOOLS.md`](https://github.com/up2itnow0822/ReadyTrader-Crypto/blob/main/docs/TOOLS.md).
