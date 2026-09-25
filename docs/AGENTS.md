# docs/

## Purpose

Operator-facing documentation: architecture, security review, live protocol, Hermes MCP integration, UAT evidence.

## Ownership

ReadyTrader-Crypto documentation tree. Keep contracts accurate to code in `app/core/settings.py` and compose files.

## Local Contracts

- `HERMES_INTEGRATION.md` — stdio MCP config for Hermes (`mcp_servers.readytrader-crypto`); skill package: https://github.com/up2itnow0822/readytrader-crypto-hermes
- `OPS_BTC_PRODUCTION.md` — halted live compose, CEX key hygiene, monitoring
- `LIVE_TESTING_PROTOCOL.md` — Phases 1–5; Phase 4 dust is optional/future; sentiment validation refreshes the feed and then recomputes the risk result; 4.5 is the emergency procedure (restart with `TRADING_HALTED=true`, then `cancel_all_cex_orders`; there is no HTTP cancel endpoint)
- `UAT_BTC_PRODUCTION_MINUS_DUST.md` — 2026-09-14 evidence pass; superseded, kept for history
  (see the note at its top)
- `uat/` — dated re-verification passes that supersede the file above as they land (e.g.
  `uat/2026-09-23-reverification.md`): exact commands, pass/fail/skip counts, and limits for
  one pass. Files here are never rewritten after the fact — a later pass adds a new dated file
  and updates the pointers in `../UAT.md` and this file instead
- `SECURITY_REVIEW.md` / `CUSTODY.md` / `RUNBOOK.md` — production ops
- `SENTIMENT.md` — feed setup plus the Falling Knife score contract (scale, threshold, no-data semantics); keep in step with `intelligence/sentiment.py` and the `sentiment` block of `validate_trade_risk`
- `STRATEGY_SANDBOX.md` — strategy contract, isolation layers, limits, and stated (non-)guarantees for `run_backtest_simulation` / the stress lab; keep in step with `strategy_sandbox.py`
- `ARCHITECTURE.md#approval-gate` — how `EXECUTION_APPROVAL_MODE=approve_each` and `POST /api/approve-trade` work, including the shared proposal session (`EXECUTION_SESSION_ID`) and the mode check; keep in step with `execution_store.py` and `api_server.py`
- `FALLING_KNIFE.md` — the Risk Guardian's Falling Knife rule for crypto (sentiment only) and the held-out results that rejected a price rule; keep in step with `risk_manager.py` and `research/falling_knife/`
- `ERRORS.md` — every error code a tool or the approval API answers with; add a code here in the same change that introduces it
- `TOOLS.md` — the curated tool catalog (not regenerated: `tools/generate_tool_docs.py` only prints the live registry to compare against); its roster is guarded by `tests/test_docs_tool_roster.py`
- Root templates: `env.example`, `env.live.btc.example`

## Work Guidance

- Document fail-closed defaults (auth, halt, signer, CORS) whenever code changes them
- Settings are read at start-up: halting or un-halting is a restart with `TRADING_HALTED` set, never an `export` into a running server; while halted, reads and cancels still work
- Never put real secrets in examples
- BTC path defaults to CEX spot allowlists

## Verification

- Docs reviewed as part of UAT closeout; links resolve from repo root
- `python tools/generate_tool_docs.py` (prints the live registry) and `python tools/verify_docs.py` read the registered tools through FastMCP's public async `mcp.list_tools()` API; `pytest tests/test_docs_tool_roster.py` checks the roster in `TOOLS.md` and the README

## Child DOX Index

(none)
