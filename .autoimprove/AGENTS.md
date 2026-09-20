# .autoimprove/

## Purpose

Planning and evidence for a paper/CI-only auto-improve loop on ReadyTrader-Crypto. Not a runtime surface.

## Ownership

Agent Economy, LLC / Bill Wilson. Phase 0 artifacts live under `phase0/`.

## Local Contracts

- Phase 0 is brainstorm + baseline only: no product code, no live-path edits, no merge
- PR #9 (`EXECUTION_MODE=auto` routing) is out of scope unless Bill GOs separately
- Do not flip `PAPER_MODE`, `LIVE_TRADING_ENABLED`, or `TRADING_HALTED`
- Do not call authenticated exchange endpoints or spend funds
- Accept-round changes must stay paper/CI and fail closed

## Work Guidance

- Keep new files under `.autoimprove/` until a later phase is explicitly opened
- Record pass/fail counts and duration for every baseline rerun
- Prefer the frozen paper/safety pytest pack over ad-hoc scripts

## Verification

- Phase 0 baseline: paper/safety pytest pack + `python examples/paper_btc_uat.py` (see `phase0/baseline.json`)
- No product-code verification required for Phase 0 docs

## Child DOX Index

| Path | Owns |
| ---- | ---- |
| [phase0/](phase0/) | Phase 0 report, baseline numbers, ranked opportunities, harness sketch |
