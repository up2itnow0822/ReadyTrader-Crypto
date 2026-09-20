# ReadyTrader-Crypto Phase 0 — auto-improve baseline

Date: 2026-09-20. Repo: `up2itnow0822/ReadyTrader-Crypto` @ `ac8d0d0` (`main`). Throwaway branch: `autoimprove/rt-phase0-20260920`.

This is brainstorm + measurement only. No product code. No merge. No live-path edits.

## Attached briefs

`CLOUD_PROMPT_PREFIX.md`, `champion_r6.json`, `FENCE.md`, and `RT_FENCE.md` were **not** in this checkout, Gmail, or the repo. This report obeys the mission text plus DOX / trust-model / env defaults. Reconstructed operating fences:

- Paper/CI only. `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`.
- Fail closed. Do not weaken live gates, flip live flags, or call authenticated exchanges.
- No second paper-fill path. No MCP operator confirm.
- PR #9 (`EXECUTION_MODE=auto`) is out of scope unless Bill GOs separately.
- Sentiment vocabulary changes only with fresh feeds in `tests/fixtures/sentiment_feeds.json`.
- Accept rounds need a frozen train/held-out split and must stop on guard regressions.

## 1. Trust model and defaults

README trust model: the agent is intelligence only; the MCP server owns keys and the Risk Guardian. Paper is the default path; live needs an explicit opt-in.

| Source | `PAPER_MODE` | `LIVE_TRADING_ENABLED` | `TRADING_HALTED` | `EXECUTION_MODE` |
| --- | --- | --- | --- | --- |
| `app/core/settings.py` | `true` | `false` | **`true`** | **`auto`** |
| `env.example` | `true` | `false` | `true` | `hybrid` |
| `env.live.btc.example` | `false` | `true` | `true` | `cex` |
| README safety table | `true` | `false` | **`false` (drift)** | — |

`is_live_execution_allowed` is true only when paper is off, live is on, and halt is off. `SIGNER_TYPE=env_private_key` is forbidden in that regime. BTC production profile stays CEX spot + `approve_each`.

On `main`, `venue_allowed()` accepts only `dex` / `cex` / `hybrid`. Settings default `auto` is denied. That is issue #8 / PR #9 — **out of scope** for this loop.

## 2. CI and test inventory

| Workflow | Trigger | Notes |
| --- | --- | --- |
| `.github/workflows/ci.yml` | push/PR to `main` | lockfile venv, `make check`, `make security`, frontend `npm ci` + `npm audit` |
| `.github/workflows/live-path-tests.yml` | **manual** `workflow_dispatch` | safeguard job is paper/local; connectivity jobs tolerate missing creds |
| `.github/workflows/security-audit.yml` | daily cron + manual | pip-audit, bandit, TruffleHog, npm audit, Trivy, CodeQL |
| `.github/workflows/release.yml` | not used this phase | — |

Key packs (parent-owned under `tests/`):

- Paper: `test_paper_engine.py`, `test_paper_order_integrity.py`, `test_paper_execution_path.py`
- Live-safety (patched flags, no network): `test_live_safety_gates.py`
- Policy / risk: `test_policy_engine.py`, `test_risk.py`
- Sentiment / Falling Knife: `test_sentiment_gate.py` + `fixtures/sentiment_feeds.json`
- Approval / docs guards: `test_approval_api.py`, `test_docs_tool_roster.py`, `test_tool_docs.py`
- Settings / envelope: `test_settings_validation.py`, `test_tool_json_contract.py`

`make check` = ruff + full pytest-cov + bandit + pip-audit + `tools/verify_docs.py` + mdformat. Not rerun as a whole here; Phase 0 scoped the paper/safety pack only.

## 3. Baseline (no exchange keys)

Env: micromamba `ReadyTrader-Crypto` (Python 3.12.14), `pip install -r requirements-dev.txt`. Flags: `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`, `SIGNER_TYPE=null`, `DEV_MODE=true`. No CEX credentials. No authenticated exchange calls.

**Paper/safety pytest pack: 278 passed, 0 failed, 0 errors, 0 skipped, 9.739s.**

| File | Tests |
| --- | ---: |
| `tests/test_paper_engine.py` | 18 |
| `tests/test_paper_order_integrity.py` | 46 |
| `tests/test_paper_execution_path.py` | 7 |
| `tests/test_live_safety_gates.py` | 10 |
| `tests/test_policy_engine.py` | 26 |
| `tests/test_risk.py` | 5 |
| `tests/test_sentiment_gate.py` | 86 |
| `tests/test_approval_api.py` | 31 |
| `tests/test_docs_tool_roster.py` | 4 |
| `tests/test_tool_docs.py` | 1 |
| `tests/test_settings_validation.py` | 23 |
| `tests/test_tool_json_contract.py` | 21 |

**`python examples/paper_btc_uat.py`: PASS in 0.096s** — 20 paper fills, 1 risk block (50% size), live-execution default false, halt gate ok. Printed totals show binary-float residue (`600.3000000000001`). The harness still calls `execute_trade` (prose), not `execute_trade_result`.

Machine copy: `baseline.json`.

## 4. Ranked opportunities (8–12)

Full records: `opportunities.json`.

1. **Falling Knife crash-recall WFA** — paper-safe, medium. Published eval is 12/22 crashes blocked, 0/50 calm-red-green-contested. In-repo fixture is 17 feeds including known misses (`crash-02`, `crash-05`, altcoin false positive). Best first *loop* target.
2. **Docs/default truth pack** — paper-safe, easy. README `TRADING_HALTED` default is wrong; `env.example` `EXECUTION_MODE` disagrees with Settings. Do **not** “fix” this by implementing `auto`.
3. **Paper BTC UAT on `execute_trade_result` + CI** — paper-safe, easy. Makes the UAT a structured metric instead of string matching.
4. **Policy allowlists on paper CEX orders** — paper-safe behavior change, medium. Today `place_cex_order` paper-mode skips `PolicyEngine`.
5. **Dedicated CI job for this 278-test pack** — paper-safe, easy.
6. **Stop session-wide `EXECUTION_MODE=dex` in `tests/conftest.py`** — paper-safe, easy. Hides CEX paper regressions.
7. **Optional paper-mode Risk Guardian on `place_cex_order`** — paper-safe behavior change, medium. Paper fills never call `RiskGuardian` today.
8. **Finite/rounded paper totals** — paper-safe, medium. UAT float residue.
9. **Approval JWT fixture ≥32 bytes** — paper-safe, easy. Baseline emitted `InsecureKeyLengthWarning`.
10. **Dedup `live-path-tests.yml` inline python** — paper-safe, easy. Point safeguard steps at `test_risk.py` / `test_policy_engine.py`.
11. **Wire `RISK_PROFILE` into `RiskGuardian` (default stays conservative)** — paper-safe if defaults hold; funds-adjacent if live thresholds loosen.
12. **PR #9 `EXECUTION_MODE=auto`** — **OUT OF SCOPE.** Funds-adjacent live routing. Separate Bill GO only.

## 5. Recommended Phase 1 target

**One target: Falling Knife crash-recall on a frozen fixture split** (`sentiment-wfa-recall`).

Why this, not a docs one-shot: it already has a published metric, a blind fixture, and a tighten-only refresh contract. It is paper/CI. It does not touch live venue routing.

Why not PR #9: `auto` routing changes who may hit a live venue after flags are opened. That is a funds-adjacent semantic. Leave it on `fix/issue-8-execution-mode-auto` until Bill GOs.

Harness: `harness.md`. Short version:

- Train/held-out split of the 17 in-repo feeds (ids listed in the harness). New feeds are held-out until moved.
- Primary metric: held-out crash-block recall.
- Guards: 0 new false positives; `known_limit` may shrink not grow; degraded refresh never relaxes; 278/278 paper/safety pack; UAT still passes; no `execution/router.py`.

## 6. Stop / go for accept rounds

**GO** — run accept rounds on the frozen sentiment harness.

Stop a round if:

- any guard metric fails
- a patch edits live routing, live flags, or signer-live rules
- the only way to move the primary metric is PR #9
- a change would call an authenticated exchange or spend funds

First accept-round commit should add the split comment / helper only (no lexicon edit), then a later round may add feeds and then vocabulary.

## DOX closeout

- Added `.autoimprove/AGENTS.md` and indexed it from the root `AGENTS.md`.
- `docs/AGENTS.md`, `frontend/AGENTS.md`, `signing/AGENTS.md` left unchanged: no operator-doc, dashboard, or signer contract change.
- Parent-owned `app/`, `execution/`, `intelligence/`, `tests/` left unchanged (no product code).
