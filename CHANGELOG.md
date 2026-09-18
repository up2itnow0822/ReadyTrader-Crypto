## Changelog

This project follows a lightweight changelog format. Major changes are summarized here to help operators and integrators understand what changed between versions.

### Unreleased

- **`EXECUTION_MODE=auto` routing (issue #8):** `venue_allowed()` now treats `auto` — the `Settings` default — like `hybrid` (either venue per call). Previously the default silently denied every live venue check (`Execution blocked by EXECUTION_MODE=auto …`) for operators who never set `EXECUTION_MODE`; `dex`/`cex`/`hybrid` behavior and the fail-closed denial of unknown values are unchanged.
- **Live-safety gaps (issue #6):** `start_cex_private_ws` now requires live execution to be allowed (`LIVE_TRADING_ENABLED=true`, not `TRADING_HALTED`) before opening a private stream; `stop_cex_private_ws` and `list_cex_private_updates` remain available so a halt can still be observed/stopped. Paper `place_cex_order` no longer fills at a fabricated `100000.0` placeholder when `price` is omitted — it resolves a reference price from the market-data bus or fails with `paper_price_required`. Paper-mode `get_cex_balance` returns the paper wallet's balances without requiring CEX credentials. Docs: `env.example`/`RUNBOOK.md` now note that `ALLOW_*`/`MAX_*` policy limits are enforced on the live order path only; `RUNBOOK.md` no longer references the unregistered `start_marketdata_ws`/`stop_marketdata_ws`/`get_ticker` tools.
- **Fail-closed production gates:** `TRADING_HALTED` defaults to `true`; `api_server` refuses start when `DEV_MODE=false` without JWT auth or with CORS `*`; live/non-paper settings require auth + non-wildcard CORS; `SIGNER_TYPE=env_private_key` forbidden when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`.
- **SEC-001/002:** `/ws` requires JWT when auth is on; `.env.live` / `.env.*.local` gitignored; live MCP compose gets auth/CORS env so Settings can boot.
- **BTC ops pack:** `env.live.btc.example`, `docs/OPS_BTC_PRODUCTION.md`, Hermes stdio MCP guide `docs/HERMES_INTEGRATION.md`, UAT harness `examples/paper_btc_uat.py`, UAT evidence `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md`.
- **Hermes skill:** public package [readytrader-crypto-hermes](https://github.com/up2itnow0822/readytrader-crypto-hermes) (install with `hermes skills install up2itnow0822/readytrader-crypto-hermes/skills/finance/readytrader-crypto --category finance`).
- **DOX:** root `AGENTS.md` plus `signing/` and `docs/` child contracts.
- **Live compose:** wire `ALLOW_CEX_SYMBOLS` / `ALLOW_CEX_MARKET_TYPES`; default `EXECUTION_MODE=cex` for BTC spot.

### 0.1.0 (2025-12-29)

- **Agent-first MCP server** for crypto trading workflows (paper mode + optional live execution).
- **Safety governance**: risk disclosure consent gate, kill switch, optional approve-each execution with replay protection.
- **Execution breadth**: CEX via CCXT + DEX swaps (1inch builder) with execution routing (`dex`/`cex`/`hybrid`).
- **Market data quality**: websocket-first public streams (opt-in), MarketDataBus freshness selection, plugin feed interface.
- **Stress lab**: deterministic synthetic stress testing with exportable artifacts + heuristic recommendations.
- **Operator layer**: structured logs with redaction, metrics snapshots, optional Prometheus text export, runbook and error catalog.
- **Custody hardening**: signer abstraction (env/keystore/remote), signing intents, defense-in-depth signer policy wrapper.
