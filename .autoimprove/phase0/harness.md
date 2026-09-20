# Frozen harness sketch (Phase 1)

This is the accept-round contract. Freeze it before any lexicon or product edit.

## Scope

Paper/CI only. No live flags, no authenticated exchange, no `execution/router.py` edits, no PR #9.

## Train / held-out

`tests/fixtures/sentiment_feeds.json` is a 17-feed sample of the 86-feed eval in `docs/SENTIMENT.md`. The other 69 feeds are not in this repo, so they are **not** a runnable held-out set.

Declared split of the **in-repo** fixture (by `id`, not by current verdict):

| Split | Feed ids | Role |
| ----- | -------- | ---- |
| Train | `crash-01`, `crash-07`, `crash-exchange-hack`, `crash-05`, `calm-01`, `red_day-01`, `green_day-03`, `contested-01`, `alarming-jokes` | May inform a lexicon proposal |
| Held-out | `crash-03`, `crash-12`, `crash-02`, `calm-02`, `red_day-02`, `contested-05`, `alarming-anniversary`, `alarming-altcoin-implodes` | Scored only after the proposal is frozen |

Rules:

1. Add any new feed to the fixture **before** changing `intelligence/sentiment.py`.
2. New feeds default to held-out until Bill moves them.
3. `known_limit` may be removed when a crash starts blocking; it may not be added to hide a new false positive.
4. Do not retune against held-out ids in the same round.

## Primary metric

Held-out crash-block recall:

```
recall = (# held-out crash feeds with score < -0.5 and not known_limit)
         / (# held-out crash feeds)
```

Baseline on this split (current fixture + current scorer): train crash blocks = 3/4 (`crash-05` is `known_limit`); held-out crash blocks = 2/4 (`crash-02` is `known_limit`). Accept only if held-out recall rises (e.g. `crash-02` starts blocking) **and** every guard below holds.

## Guard metrics (any fail = STOP)

- 0 blocks on held-out `calm` / `red_day` / `green_day` / `contested`
- `alarming-altcoin-implodes` may stay `known_limit`; do not add new alarming false positives
- Entire paper/safety pack: 278 passed, 0 failed (see `baseline.json`)
- `tests/test_sentiment_gate.py` degraded-refresh cases: tighten-only, never relax
- `validate_trade_risk` still reports `sentiment.status` (`ok` / `no_data` / `not_configured` / `insufficient_data`)
- `tests/test_risk.py` Falling Knife / size / daily-loss / drawdown strings unchanged
- `tests/test_live_safety_gates.py` and `tests/test_paper_order_integrity.py` stay green
- `python examples/paper_btc_uat.py` still `pass: true`

## Command

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

## Forbidden files for Phase 1 accept rounds

- `execution/router.py`
- live compose / `env.live.btc.example` semantics
- MCP operator confirm (`ExecutionStore.confirm_as_operator`, `approved_execution`)
- Any second paper-fill path besides `PaperTradingEngine.execute_trade_result`

## Stop / go

- **GO** to run accept rounds on this harness.
- **STOP** a round if any guard fails, if a change needs live routing, or if the only way to move the primary metric is to implement PR #9.
