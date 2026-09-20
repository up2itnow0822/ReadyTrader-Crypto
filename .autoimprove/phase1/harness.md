# Frozen Falling Knife harness (Phase 1)

Frozen 2026-09-20. Do not change train or held-out ids mid-run.

Source: Phase 0 sketch in `.autoimprove/phase0/harness.md`. Product fixture:
`tests/fixtures/sentiment_feeds.json`.

## Money fence (fail-closed)

- Paper/CI only. `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`.
- No live flags, no authenticated exchange, no `execution/router.py`.
- No PR #9 (`EXECUTION_MODE=auto`). No MCP operator confirm. No second paper-fill path.
- `CLOUD_PROMPT_PREFIX.md`, `champion_r6.json`, `FENCE.md`, `RT_FENCE.md` were not in
  this checkout; this harness follows the reconstructed Phase 0 fences plus Bill GO 2026-09-20.

## Scope

Product files that may change after a hypothesis is written:

- `intelligence/sentiment.py`
- `tests/fixtures/sentiment_feeds.json` (add feeds **before** lexicon edits; new feeds start held-out)

Out of scope / forbidden: `execution/router.py`, live compose / `env.live.btc.example`
semantics, `ExecutionStore.confirm_as_operator`, `approved_execution`, any paper-fill path
besides `PaperTradingEngine.execute_trade_result`.

## Frozen split (by `id`, not by current verdict)

| Split | Feed ids |
| ----- | -------- |
| Train | `crash-01`, `crash-07`, `crash-exchange-hack`, `crash-05`, `calm-01`, `red_day-01`, `green_day-03`, `contested-01`, `alarming-jokes` |
| Held-out | `crash-03`, `crash-12`, `crash-02`, `calm-02`, `red_day-02`, `contested-05`, `alarming-anniversary`, `alarming-altcoin-implodes` |

Rules:

1. Add any new feed to the fixture **before** changing `intelligence/sentiment.py`.
2. New feeds default to held-out until Bill moves them. They do **not** change the
   primary-metric denominator (frozen ids only).
3. `known_limit` may be removed when a crash starts blocking; it may not be added to
   hide a new false positive.
4. Do not retune against held-out ids in the same round.
5. Do not game by deleting `known_limit` without a true score improvement.

## Primary metric

Held-out crash-block recall on the **frozen** held-out crash ids
(`crash-03`, `crash-12`, `crash-02` — three ids; Phase 0 wrote ~2/4 because
`crash-02` is `known_limit` and the fourth published crash miss is train `crash-05`):

```
recall = (# frozen held-out crash feeds with score < -0.5 and not known_limit)
         / (# frozen held-out crash feeds)
```

Baseline: train crash blocks 3/4 (`crash-05` is `known_limit`); held-out crash blocks
2/3 on the frozen ids (`crash-02` is `known_limit`; Phase 0 text said ~2/4).
Accept only if held-out recall rises by a meaningful step (at least +1 crash block on
held-out, or a clear recall increase) **and** every guard below holds.

## Guard metrics (any fail = REJECT / STOP)

- 0 blocks on held-out `calm` / `red_day` / `green_day` / `contested`
- no new alarming FPs (`alarming-altcoin-implodes` may stay `known_limit`)
- paper/safety pack still 278 pass (same file set as Phase 0)
- sentiment degraded-refresh: tighten-only
- `validate_trade_risk` `sentiment.status` contract intact
- `tests/test_risk.py` Falling Knife strings unchanged
- `tests/test_live_safety_gates.py` + `tests/test_paper_order_integrity.py` green
- `examples/paper_btc_uat.py` `pass: true`
- Flags: `PAPER_MODE=true` `LIVE_TRADING_ENABLED=false` `TRADING_HALTED=true`

## Round protocol (max 5; plateau = 3 consecutive rejects)

1. Diagnose train failures / known_limits (especially why `crash-05` misses; note `crash-02` as a held-out miss, do not retune to it).
2. One hypothesis → small diff in this branch.
3. Score train first; if train improves, score held-out + full guard pack.
4. ACCEPT only if held-out recall clears baseline by a meaningful step and all guards OK.
5. REJECT otherwise; archive notes under `.autoimprove/phase1/rounds/rN.md`.
6. Never retune against held-out in the same round. Never edit this split.

## Command (paper/safety pack)

```bash
PAPER_MODE=true LIVE_TRADING_ENABLED=false TRADING_HALTED=true SIGNER_TYPE=null DEV_MODE=true \
  python -m pytest -q --tb=short \
  tests/test_paper_engine.py \
  tests/test_paper_order_integrity.py \
  tests/test_paper_execution_path.py \
  tests/test_live_safety_gates.py \
  tests/test_policy_engine.py \
  tests/test_risk.py \
  tests/test_sentiment_gate.py \
  tests/test_approval_api.py \
  tests/test_docs_tool_roster.py \
  tests/test_tool_docs.py \
  tests/test_settings_validation.py \
  tests/test_tool_json_contract.py

PAPER_MODE=true LIVE_TRADING_ENABLED=false TRADING_HALTED=true SIGNER_TYPE=null DEV_MODE=true \
  python examples/paper_btc_uat.py
```
