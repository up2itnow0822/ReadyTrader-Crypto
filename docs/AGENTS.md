# docs/

## Purpose

Operator-facing documentation: architecture, security review, live protocol, Hermes MCP integration, UAT evidence.

## Ownership

ReadyTrader-Crypto documentation tree. Keep contracts accurate to code in `app/core/settings.py` and compose files.

## Local Contracts

- `HERMES_INTEGRATION.md` — stdio MCP config for Hermes (`mcp_servers.readytrader-crypto`); skill package: https://github.com/up2itnow0822/readytrader-crypto-hermes
- `OPS_BTC_PRODUCTION.md` — halted live compose, CEX key hygiene, monitoring
- `LIVE_TESTING_PROTOCOL.md` — Phases 1–5; Phase 4 dust is optional/future; sentiment validation refreshes the feed and then recomputes the risk result
- `UAT_BTC_PRODUCTION_MINUS_DUST.md` — evidence for production-minus-dust gate
- `SECURITY_REVIEW.md` / `CUSTODY.md` / `RUNBOOK.md` — production ops
- `SENTIMENT.md` — feed setup plus the Falling Knife score contract (scale, threshold, no-data semantics); keep in step with `intelligence/sentiment.py` and the `sentiment` block of `validate_trade_risk`
- Root templates: `env.example`, `env.live.btc.example`

## Work Guidance

- Document fail-closed defaults (auth, halt, signer, CORS) whenever code changes them
- Never put real secrets in examples
- BTC path defaults to CEX spot allowlists

## Verification

- Docs reviewed as part of UAT closeout; links resolve from repo root
- `python tools/generate_tool_docs.py` and `python tools/verify_docs.py` read the registered tools through FastMCP's public async `mcp.list_tools()` API

## Child DOX Index

(none)
