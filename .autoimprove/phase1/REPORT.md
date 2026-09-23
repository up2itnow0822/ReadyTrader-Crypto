# ReadyTrader-Crypto Phase 1 — Falling Knife accept rounds

Date: 2026-09-20. Branch: `autoimprove/rt-phase1-falling-knife-20260920`. Base: `main` @ `ac8d0d0`. Accepted product: `89c7976`. PR: https://github.com/up2itnow0822/ReadyTrader-Crypto/pull/17``

Paper/CI only. Money fence fail-closed. **No merge to main.**

## Attached briefs

`CLOUD_PROMPT_PREFIX.md`, `champion_r6.json`, `FENCE.md`, and `RT_FENCE.md` were not in this checkout (same as Phase 0). Operating fences used:

- `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`
- No live flags, no authenticated exchange, no `execution/router.py`, no PR #9
- No MCP operator confirm, no second paper-fill path
- Frozen train/held-out ids (see `harness.md`); new feeds start held-out and do not change the primary denominator
- Do not delete `known_limit` without a true score improvement

Phase 0 docs copied from `autoimprove/rt-phase0-20260920` (PR #16).

## Frozen harness

| Split | Crash ids | Baseline | After R1 |
| ----- | --------- | -------- | -------- |
| Train | `crash-01`, `crash-07`, `crash-exchange-hack`, `crash-05` | 3/4 | **4/4** |
| Held-out | `crash-03`, `crash-12`, `crash-02` | 2/3 | **3/3** |

Primary: held-out crash-block recall on frozen ids. Baseline 2/3. After R1 **3/3** (+1 crash block). Phase 0 prose said ~2/4 because `crash-02` is `known_limit` and train `crash-05` is the other published miss; the frozen held-out crash id list is three.

## Rounds

| Round | Hypothesis | Train | Held-out | Guards | Verdict |
| ----- | ---------- | ----- | -------- | ------ | ------- |
| 1 | Printed 8%+ drop is bearish (minus on the number); 3 directional texts suffice when such a print is present | 3/4 → **4/4** | 2/3 → **3/3** | all pass | **ACCEPT** |

Stopped after 1 accept. Frozen held-out crash recall is maxed (3/3). Plateau rule (3 consecutive rejects) did not apply.

Per-round notes: `rounds/r1.md`. Machine copy: `baseline.json`, `scorecard.json`.

## Round 1 detail

**Train diagnosis:** `crash-05` had 3 lexicon hits (`dumped`, `dumping`, `bleeding`) and unused `-10%` / `(-9.8% 24h)` prints. `MIN_DIRECTIONAL=4` plus the 15-text share floor kept the score at 0.0.

**Change (feeds first, then rule):**

1. Added held-out extras `crash-pct-only`, `red_day-six-pct`, `calm-promo-pct` (pinned on the old scorer; none blocked).
2. `intelligence/sentiment.py`: `LARGE_DROP_PCT=8.0`. A printed drop that large is bearish. When at least one is present, consensus floor is 3. Promo ` - 92% WIN RATE` does not match.

**Scores:** `crash-05` 0.0 → -1.0 (5 bear). `crash-02` 0.0 → -1.0 (3 bear). `known_limit` removed only after those scores crossed `-0.5`. Extra `crash-pct-only` now blocks; `red_day-six-pct` and `calm-promo-pct` do not.

**Guards**

| Guard | Result |
| ----- | ------ |
| 0 held-out calm / red_day / green_day / contested blocks | pass |
| no new alarming FPs (`alarming-altcoin-implodes` stays `known_limit`) | pass |
| paper/safety pack, same 12 files as Phase 0 | **284 passed**, 0 failed, 24.592s (278 + 3 new feeds + 3 new tests) |
| degraded-refresh tighten-only | pass (`test_sentiment_gate` pack) |
| `validate_trade_risk` `sentiment.status` | pass |
| `tests/test_risk.py` Falling Knife strings | unchanged |
| `test_live_safety_gates` + `test_paper_order_integrity` | green |
| `examples/paper_btc_uat.py` | `pass: true` (20 fills, 1 risk block, live default false, halt ok) |
| Flags | `PAPER_MODE=true` `LIVE_TRADING_ENABLED=false` `TRADING_HALTED=true` |

Forbidden paths untouched: `execution/router.py`, live compose / `env.live.btc.example`, MCP operator confirm, second paper-fill path.

## Stop / continue

**Stop.** Best held-out recall delta: **+1 crash block** (2/3 → 3/3). Accepts: 1. Rejects: 0.

Do **not** continue this harness for more lexicon rounds: there is no remaining frozen held-out crash miss. Further work needs a new Bill GO (new held-out crashes, or a different metric such as shrinking the altcoin `known_limit` without calm FPs).

## DOX closeout

- Updated `.autoimprove/AGENTS.md` and `.autoimprove/phase1/AGENTS.md`; indexed `.autoimprove/` from root `AGENTS.md`.
- Root `AGENTS.md` sentiment bullet now names the 8%+ drop cue.
- `docs/SENTIMENT.md` kept in step with the scorer.
- Left unchanged: `docs/AGENTS.md` (still points at `SENTIMENT.md`), `frontend/AGENTS.md`, `signing/AGENTS.md`. `intelligence/` and `tests/` stay parent-owned.
