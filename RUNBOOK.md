## ReadyTrader-Crypto Runbook (Docker-first)

### Common operations

#### Verify health

- HTTP API: `GET /api/health` (`api_server.py`) returns `mode`, `trading_halted`, `live_enabled`, `version`. There is no health MCP tool; from an MCP client, a successful `get_crypto_price` call is the liveness check.
- If health fails:
  - confirm required environment variables are set
  - confirm exchange endpoints are reachable (REST + websocket if enabled)
  - confirm rate limits and policy allowlists are not blocking requests

#### View metrics

- HTTP API: `GET /api/metrics` (`api_server.py`, JWT-protected) returns the metrics snapshot. There is no metrics MCP tool.

#### Kill switch (live trading)

- Default is `TRADING_HALTED=true` (safe). Set `TRADING_HALTED=false` only after UAT.
- To halt immediately: set `TRADING_HALTED=true` and restart the container/process. The kill switch
  refuses new orders, swaps and transfers; reading the account and cancelling orders still work, so
  run `cancel_all_cex_orders(...)` and `list_cex_open_orders(...)` next (`docs/LIVE_TESTING_PROTOCOL.md` 4.5).

#### BTC CEX production path (spot)

1. Copy `env.live.btc.example` → `.env.live`; fill JWT, CEX trade-only keys (no withdraw), remote signer URL.
1. Validate compose (do not unhalt):\
   `docker-compose -f docker-compose.live.yml --env-file .env.live config`
1. Start halted: `docker-compose -f docker-compose.live.yml --env-file .env.live up -d`
1. Verify `GET /api/health` with JWT; confirm `trading_halted: true`.
1. Paper/MCP first via Hermes — see `docs/HERMES_INTEGRATION.md`.
1. Full ops pack (monitoring, keys, compose): `docs/OPS_BTC_PRODUCTION.md`.
1. Do **not** place live orders until Phase 4 dust UAT is explicitly authorized.

#### Rotate secrets

- Prefer keystore or remote signer in live environments.
- Rotate `CEX_*` credentials by updating env vars and restarting.
- See `docs/CUSTODY.md` for rotation cadence.

#### Debug execution failures

- Look for JSON logs with `event=tool_error` (and check `level`).
- In approve-each mode, inspect pending proposals with `GET /api/pending-approvals` and confirm with `POST /api/approve-trade` (HTTP API; there is no MCP approval tool). Start the MCP server and the API server with the same `EXECUTION_DB_PATH` and `EXECUTION_SESSION_ID`, or the API cannot see the MCP server's proposals (`EXEC_309`). A `409` `EXEC_313` means the proposal was made in the other mode (paper/live).
- A refused order names its rule: `risk_blocked` (the Risk Guardian: `error.data.risk` has the account value, the exposure added and the sentiment it used), `trading_halted`, `live_trading_disabled`, or a policy code such as `symbol_not_allowed`. `cex_error` / `execution_error` mean an unexpected exchange or RPC failure: the exception is in the log.
- Re-run failed operations with an `idempotency_key` to avoid duplicates.

#### Market data

- Public price/OHLCV data is pull-based via `get_crypto_price(symbol)` / `fetch_ohlcv(symbol, ...)`; there is no MCP
  tool to start/stop a public streaming feed. Check provider health with `GET /api/marketdata/status`.
- For private order updates, use `start_cex_private_ws(...)` (requires live execution to be allowed) /
  `stop_cex_private_ws(...)` (always available, even while halted), and inspect with `list_cex_private_updates(...)`.

______________________________________________________________________

### Incident playbooks (Phase 4)

#### 1) Rate limit storm (HTTP API returning `rate_limited`)

- **Symptoms**:
  - API calls (the dashboard) start failing with `rate_limited`; MCP tools are not rate-limited
  - Metrics show rising `counters.rate_limited_total`
- **Triage**:
  - Call `GET /api/metrics` and inspect:
    - `counters.rate_limit_checks_total`
    - `counters.rate_limited_total`
  - Check tool call patterns (agents may be looping/retrying too aggressively)
- **Mitigation**:
  - Reduce call frequency (prefer caching, batch calls, or use websocket streams)
  - Raise the limit (carefully): `RATE_LIMIT_DEFAULT_PER_MIN`

#### 2) Websocket disconnect loop (public streams)

- **Symptoms**:
  - `GET /api/marketdata/status` shows websocket stream `last_error`
  - Metrics show increasing websocket error/connect counters (e.g. `ws_*_error_total`)
- **Triage**:
  - Call `GET /api/marketdata/status` and inspect:
    - `ws_streams`
    - `stores.ws` freshness
  - Ensure outbound network access is available in the deployment environment
- **Mitigation**:
  - There is no tool to restart the public stream; `MarketDataBus` already fails over automatically across providers
    by priority (`exchange_ws` → `ingest` → `ccxt_rest`).
  - If unreliable, fall back to `ccxt_rest` and/or ingest your own feed.

#### 3) Exchange outage / degraded mode

- **Symptoms**:
  - CCXT calls failing (`ccxt_exchange_unavailable`, `ccxt_network_error`)
  - Private update pollers show errors / lag
- **Triage**:
  - Check `docs/EXCHANGES.md` (Supported vs Experimental expectations)
  - Use `get_cex_capabilities(exchange)` for `has.*` and market metadata
  - Check market data: `get_crypto_price(symbol)` (response names the serving provider) or
    `GET /api/marketdata/status` for per-provider candidates/health
- **Mitigation**:
  - Switch market data sources (prefer websocket/ingest, reduce REST usage)
  - Temporarily disable live execution with `TRADING_HALTED=true`

#### 4) Signer unreachable (remote signer / keystore issues)

- **Symptoms**:
  - Live DEX execution fails with signing errors
  - Errors like `remote_signer_error` or signer initialization failures
- **Triage**:
  - Confirm signer configuration (`SIGNER_TYPE`, keystore path/password, remote signer URL)
  - Check logs for `tool_error` around execution tools
- **Mitigation**:
  - Halt live trading (`TRADING_HALTED=true`)
  - Fix signer connectivity/credentials, then restart

#### 5) Policy blocks (allowlists / limits)

- **Symptoms**:
  - Errors like `token_not_allowed`, `trade_amount_too_large`, `router_not_allowed`
- **Triage**:
  - Review `env.example` and current env values for `ALLOW_*`, `MAX_*` (enforced on the live order path only; paper
    orders are not filtered by them)
  - If you are intentionally loosening limits, ensure Advanced Risk consent is accepted
- **Mitigation**:
  - Adjust allowlists/limits, or set a stricter risk profile
  - Keep `EXECUTION_APPROVAL_MODE=approve_each` while validating new configs

### Backup/restore (paper mode)

- Paper ledger is stored in `data/paper.db` (ignored by git).
- Back up by copying the file while the container is stopped.
