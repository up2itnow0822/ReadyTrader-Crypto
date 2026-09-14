## Changelog

This project follows a lightweight changelog format. Major changes are summarized here to help operators and integrators understand what changed between versions.

### Unreleased

- **Fail-closed production gates:** `TRADING_HALTED` defaults to `true`; `api_server` refuses start when `DEV_MODE=false` without JWT auth or with CORS `*`; live/non-paper settings require auth + non-wildcard CORS; `SIGNER_TYPE=env_private_key` forbidden when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`.
- **BTC ops pack:** `env.live.btc.example`, `docs/OPS_BTC_PRODUCTION.md`, Hermes stdio MCP guide `docs/HERMES_INTEGRATION.md`, UAT harness `examples/paper_btc_uat.py`, UAT evidence `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md`.
- **Hermes skill:** public package [readytrader-crypto-hermes](https://github.com/up2itnow0822/readytrader-crypto-hermes) (install as `optional-skills/finance/readytrader-crypto`).
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
