# .autoimprove/

## Purpose

Planning and evidence for a paper/CI-only auto-improve loop on ReadyTrader-Crypto. Not a runtime surface.

## Ownership

Agent Economy, LLC / Bill Wilson. Phase 0 artifacts live under `phase0/`. Phase 1 accept-round artifacts live under `phase1/`.

## Local Contracts

- Phase 0 is brainstorm + baseline only: no product code, no live-path edits, no merge
- Phase 1 is paper/CI Falling Knife accept rounds on the frozen harness in `phase1/harness.md`
- PR #9 (`EXECUTION_MODE=auto` routing) is out of scope unless Bill GOs separately
- Do not flip `PAPER_MODE`, `LIVE_TRADING_ENABLED`, or `TRADING_HALTED`
- Do not call authenticated exchange endpoints or spend funds
- Accept-round changes must stay paper/CI and fail closed
- Do not change the frozen train/held-out feed ids mid-run
- Add fixture feeds before lexicon edits; new feeds start held-out and do not change the primary-metric denominator

## Work Guidance

- Keep new files under `.autoimprove/` unless a product edit is accepted
- Record pass/fail counts and duration for every baseline rerun
- Prefer the frozen paper/safety pytest pack over ad-hoc scripts
- Prefer lexicon / rule tighten that can lift train crash-05 without calm FPs; do not retune against held-out in the same round

## Verification

- Phase 0 baseline: paper/safety pytest pack + `python examples/paper_btc_uat.py` (see `phase0/baseline.json`)
- Phase 1: frozen harness in `phase1/harness.md`; per-round notes in `phase1/rounds/`; report in `phase1/REPORT.md`

## Child DOX Index

| Path | Owns |
| ---- | ---- |
| [phase0/](phase0/) | Phase 0 report, baseline numbers, ranked opportunities, harness sketch |
| [phase1/](phase1/) | Frozen harness, accept-round notes, Phase 1 report and scorecard |
