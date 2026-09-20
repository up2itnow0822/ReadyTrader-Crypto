# ReadyTrader-Crypto Phase 1 — Falling Knife accept rounds

Date: 2026-09-20. Branch: `autoimprove/rt-phase1-falling-knife-20260920`. Base: `main` @ `ac8d0d0`.

Paper/CI only. Money fence fail-closed. No merge to main.

## Attached briefs

`CLOUD_PROMPT_PREFIX.md`, `champion_r6.json`, `FENCE.md`, and `RT_FENCE.md` were not in this checkout (same as Phase 0). Operating fences used:

- `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`
- No live flags, no authenticated exchange, no `execution/router.py`, no PR #9
- No MCP operator confirm, no second paper-fill path
- Frozen train/held-out ids (see `harness.md`); new feeds start held-out and do not change the primary denominator

Phase 0 docs copied from `autoimprove/rt-phase0-20260920` (PR #16).

## Frozen harness

| Split | Crash ids | Baseline blocks |
| ----- | --------- | --------------- |
| Train | `crash-01`, `crash-07`, `crash-exchange-hack`, `crash-05` | 3/4 (`crash-05` known_limit, 3 bearish, score 0.0) |
| Held-out | `crash-03`, `crash-12`, `crash-02` | 2/3 (`crash-02` known_limit, 1 bearish, score 0.0) |

Primary: held-out crash-block recall = 2/3. Accept only if this rises by at least +1 held-out crash block and all guards hold.

## Rounds

| Round | Hypothesis | Train | Held-out | Guards | Verdict |
| ----- | ---------- | ----- | -------- | ------ | ------- |
| — | (in progress) | 3/4 | 2/3 | baseline | — |

Per-round notes: `rounds/rN.md`. Machine copy: `baseline.json` / `scorecard.json`.

## Stop / continue

Not yet finished. Max 5 rounds; plateau = 3 consecutive rejects.
