# Fresh Automated Re-verification — 2026-09-23

**Date:** 2026-09-23\
**Main SHA verified:** `fa52d1e3cf4698560d5c93e62af6415562e4393d` (`fa52d1e`, PR #17 — current
`origin/main` tip at time of writing)\
**Conductor:** automated re-verification pass, Lane A2 (docs + re-verification), run from an
isolated clone under this machine's consolidation work tree — not Bill's working checkout\
**Scope:** CI-equivalent suite (Makefile / `.github/workflows/ci.yml`), an MCP stdio smoke
test, and the frontend Playwright e2e suite (bounded to ~25 minutes per instructions)

This document supersedes `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md` (2026-09-14) as the current
evidence source; that document is kept for history and now links here. See `UAT.md` at the
repo root for the graduation gates this evidence feeds into.

______________________________________________________________________

## 1. Environment

| Field         | Value                                                                                      |
| :------------ | :----------------------------------------------------------------------------------------- |
| OS            | macOS 27.2 (Darwin 27.2.0, `Bills-Mac.local`)                                              |
| Arch          | arm64 (Apple Silicon)                                                                      |
| Python (venv) | 3.13.14                                                                                    |
| Node          | v26.5.0                                                                                    |
| npm           | 11.17.0                                                                                    |
| Repo clone    | fresh `git clone --reference` clone, isolated work tree (not Bill's `~/Projects` checkout) |

**Two environment discrepancies from CI, noted for honesty:**

1. **Python version.** `.github/workflows/ci.yml` pins Python 3.12 exactly
   (`actions/setup-python@v5`, `python-version: "3.12"`). Python 3.12 is not installed on this
   Mac (`/opt/homebrew/bin/python3.11`, `python3.13`, `python3.14` are; no `3.12`). This pass
   used **3.13.14** as the closest available interpreter. `requirements.lock.txt` installed
   cleanly under 3.13 (`pip check` → "No broken requirements found"), so this is not shown to
   be a problem — but it is a real, undisclosed difference from CI's exact interpreter, and is
   the most likely explanation for the pytest failures in Section 3.
1. **`NODE_ENV=production` is set globally in this Mac's shell profile**, and `npm config get omit` accordingly returns `dev`. Under that default, `npm ci` and `npm audit` silently
   **omit devDependencies** — which on a first pass produced an artificially clean-looking
   `npm ci` (only 69 packages) and an `npm audit` that never touched `eslint`/`typescript`/
   `vitest`/`playwright` at all. `frontend/AGENTS.md` already documents this exact trap
   ("`npm audit --omit=dev` is not the gate — it hides eslint/tsc toolchain advisories.").
   **Every command below was re-run with `NODE_ENV` explicitly unset** to match what CI's
   runner actually does (GitHub Actions does not set `NODE_ENV=production` for this workflow).
   This is a property of this Mac's shell profile, not of the repository.

______________________________________________________________________

## 2. Exact commands and results

### 2.1 Python dependency install (locked, matches `ci.yml`)

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --no-deps -r requirements.lock.txt
.venv/bin/python -m pip check
```

**Result: PASS.** "No broken requirements found."

### 2.2 Frontend dependency install (matches `ci.yml`'s `npm ci --prefix frontend`)

```bash
env -u NODE_ENV npm ci --include=dev
```

**Result: PASS.** 471 packages added, 472 audited (0 vulnerabilities in the install-time
summary).

### 2.3 `make check`

```bash
PATH="$PWD/.venv/bin:$PATH" make check
```

| Step                                                         | Result                                 |
| :----------------------------------------------------------- | :------------------------------------- |
| `ruff check .`                                               | **PASS** — "All checks passed!"        |
| `ruff format --check .`                                      | **PASS** — 129 files already formatted |
| `cd frontend && npm run lint` (eslint)                       | **PASS** — 0 errors/warnings           |
| `pytest --cov=. --cov-report=term-missing --cov-report=html` | **FAIL** — see Section 3               |

`make` stops at the first failed prerequisite (`lint test-cov` are both prerequisites of
`check`), so once `test-cov` failed, `make check` exited without running the remaining recipe
steps (`bandit`, `pip-audit -r requirements.txt`, `tools/verify_docs.py`,
`mdformat --check ...`). Those four are covered directly in 2.4 and 2.5 below so this pass has
complete coverage regardless.

______________________________________________________________________

## 3. `pytest` result and root cause of every failure

```
PAPER_MODE=true SIGNER_TYPE=null DEV_MODE=true pytest --cov=. --cov-report=term-missing --cov-report=html
```

**543 passed, 55 failed, 5 skipped, 257 warnings in 68.46s. Coverage: 60.88% (6725 stmts).**

### 3.1 The 5 skips (all credential-gated, expected)

```
SKIPPED tests/integration/test_exchange_sandbox.py:215  Binance testnet credentials not configured
SKIPPED tests/integration/test_exchange_sandbox.py:243  Binance testnet credentials not configured
SKIPPED tests/integration/test_exchange_sandbox.py:340  Kraken credentials not configured
SKIPPED tests/integration/test_exchange_sandbox.py:414  Coinbase sandbox credentials not configured
SKIPPED tests/integration/test_exchange_sandbox.py:500  ETH_RPC_URL not configured
```

These are LIMITS (no live credentials in this environment, by design), not failures.

### 3.2 The 55 failures — all one root cause

Every failure is in `tests/test_backtest.py` (1), `tests/test_strategy_sandbox.py` (53), or
`tests/test_synthetic_stress.py` (1) — i.e. every test that exercises
`strategy_sandbox.run_strategy`. All 55 raise the identical underlying error:

```
strategy_sandbox.StrategyError: sandbox limit RLIMIT_AS was not applied
(soft=9223372036854775807, expected<=1073741824); refusing to run
```

`9223372036854775807` is `2**63 - 1` (`RLIM_INFINITY` on this platform) — i.e. after
`strategy_sandbox.py`'s child calls `resource.setrlimit` with `RLIMIT_AS` to request a 1 GiB
address-space cap, reading the limit back shows it was **not applied**. The sandbox's own
fail-closed self-check (added in PR #13, see `CHANGELOG.md`) correctly detects this and refuses
to run rather than executing unconstrained — which is its documented fail-closed intent — but
every test in these files consequently reports as a failure rather than a pass, because the
tests expect the sandboxed strategy to actually execute.

**Assessment:** this is consistent with a known macOS/Darwin behavior — `RLIMIT_AS` is not
enforced by `setrlimit` on Darwin the way it is on Linux (the requested limit silently does
not take effect). `CHANGELOG.md` itself already scopes this limit as "(on POSIX)"; Darwin is
POSIX but its `RLIMIT_AS` support differs from Linux's in practice, and the code's own runtime
self-check is what is surfacing that gap here — not a logic bug being newly discovered. This
reads as **an environment limitation of this macOS host, not a demonstrated code regression**:

- `.github/workflows/ci.yml` runs on `ubuntu-latest` (Linux), where `RLIMIT_AS` enforcement is
  the normal case this code was written against.
- GitHub Actions' own last recorded run of `ci.yml` on this exact commit (`fa52d1e`,
  2026-09-20T13:39 UTC) reported **success** — i.e. these same 55 tests passed on Linux CI for
  this SHA.

**This was not independently re-verified against Linux in this pass** (no Docker run of the
suite was performed here) — recorded as a **LIMIT**, not confirmed either way beyond the point
above. See `SECURITY.md` and `UAT.md` for how this is carried forward.

Full list of the 23 distinct failing test functions (some parametrized into multiple failing
cases, totaling 55):

```
tests/test_backtest.py::test_safe_execution
tests/test_strategy_sandbox.py::test_a_huge_exception_message_is_capped_before_it_reaches_the_parent
tests/test_strategy_sandbox.py::test_an_action_object_cannot_run_attacker_code_in_the_comparison
tests/test_strategy_sandbox.py::test_attribute_writes_are_refused (parametrized)
tests/test_strategy_sandbox.py::test_backtest_engine_read_csv_canary_does_not_leak
tests/test_strategy_sandbox.py::test_backtest_runtime_error_keeps_its_documented_shape
tests/test_strategy_sandbox.py::test_base_exceptions_are_the_strategys_error_never_the_sandboxs_voice (parametrized)
tests/test_strategy_sandbox.py::test_both_engines_survive_an_infinite_loop
tests/test_strategy_sandbox.py::test_child_cannot_write_file_contents
tests/test_strategy_sandbox.py::test_child_environment_contains_nothing_from_the_parent
tests/test_strategy_sandbox.py::test_dangerous_builtins_are_not_defined (parametrized)
tests/test_strategy_sandbox.py::test_infinite_loop_is_stopped_by_the_wall_clock
tests/test_strategy_sandbox.py::test_inner_layer_holds_with_the_static_precheck_disabled (parametrized)
tests/test_strategy_sandbox.py::test_legit_strategy_returns_aligned_actions_and_params
tests/test_strategy_sandbox.py::test_math_is_available_and_unknown_actions_become_hold
tests/test_strategy_sandbox.py::test_missing_on_candle_is_a_compile_error
tests/test_strategy_sandbox.py::test_no_module_is_reachable_from_strategy_globals (parametrized)
tests/test_strategy_sandbox.py::test_oversized_params_are_dropped_not_returned
tests/test_strategy_sandbox.py::test_pathological_nesting_is_a_compile_error_not_a_parent_crash (parametrized)
tests/test_strategy_sandbox.py::test_state_persists_within_a_series_and_resets_between_series
tests/test_strategy_sandbox.py::test_stress_engine_read_csv_canary_does_not_leak
tests/test_strategy_sandbox.py::test_the_child_applies_the_limits_it_then_verifies
tests/test_synthetic_stress.py::test_run_synthetic_stress_outputs_artifacts_and_seeds
```

Per the DOX/task boundary for this lane (docs-only; `strategy_sandbox.py` and its tests are
code, out of scope here), no code change was attempted. This is reported, not repaired.

______________________________________________________________________

### 2.4 `verify_docs.py` and `mdformat --check` (run directly — `make check` aborted before reaching them; see 2.3)

```bash
PATH="$PWD/.venv/bin:$PATH" python tools/verify_docs.py
PATH="$PWD/.venv/bin:$PATH" mdformat --check docs README.md RUNBOOK.md SECURITY.md CONTRIBUTING.md CHANGELOG.md
```

**Result: PASS on unmodified `main`, before this PR's own edits.**

```
Checking for non-portable links...      ✓ 0 issues found
Checking naming consistency...          ✓ 0 issues found
Checking env.example matches settings...✓ 0 issues found
Checking version consistency...         ✓ 0 issues found
Checking tool documentation...          ✓ 0 issues found
Documentation verification PASSED
```

`mdformat --check` produced no output and exit code 0 (all six files already clean). This PR's
own doc edits (`CHANGELOG.md`, `SECURITY.md`, `README.md`, this file, `UAT.md`) were run
through the same `mdformat` afterward — see the PR description / commit history for that pass.

### 2.5 `make security`

```bash
PATH="$PWD/.venv/bin:$PATH" make security
```

| Step                                                           | Result                                                                                                                                            |
| :------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bandit -r . -c bandit.yaml`                                   | **PASS** — "No issues identified." 10,582 lines scanned; 2 `#nosec` lines; 7 specifically-disabled-test skips (all pre-existing, none added here) |
| `pip-audit -r requirements.txt`                                | **PASS** — "No known vulnerabilities found"                                                                                                       |
| `npm audit --prefix frontend`                                  | Ran under this Mac's default `omit=dev` (see Section 1, discrepancy #2) — superseded by the explicit re-run below                                 |
| `npm audit --include=dev --json` (frontend/, `NODE_ENV` unset) | **PASS** — **0 vulnerabilities** across all severities; 549 dependencies (63 prod, 448 dev, 89 optional, 43 peer)                                 |

### 2.6 `pip-audit -r requirements.lock.txt`

**Result: PASS.** "No known vulnerabilities found."

### 2.7 Frontend typecheck + unit tests (beyond `ci.yml`'s own gate; per `frontend/AGENTS.md` Verification section)

```bash
env -u NODE_ENV npm run typecheck   # tsc --noEmit
env -u NODE_ENV npm test -- --run   # vitest run
```

**Result: PASS on both.** `tsc --noEmit` clean. Vitest: 7 test files, **59 tests passed**,
1.87s (`src/lib/api.test.ts` 8, `src/lib/format.test.ts` 18, `src/lib/useWebSocket.test.ts` 7,
`src/providers/HealthProvider.test.tsx` 4, `src/components/ApprovalCard.test.tsx` 7,
`src/providers/AuthProvider.test.tsx` 5, `src/hooks/useApprovals.test.tsx` 10).

______________________________________________________________________

## 4. MCP stdio smoke test

Started the server exactly as `README.md`'s "Zero-key quickstart" documents — the venv's
`python` running `server.py` over stdio — using the official `mcp` Python client SDK
(`stdio_client` + `ClientSession`), with the README's documented paper profile:
`PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`, `EXECUTION_MODE=cex`,
`SIGNER_TYPE=null`. The driver script is ad hoc evidence tooling, kept outside this repo (not
committed — it is not product code).

| Step                                                                                                      | Result                                                                                                                                                                                            |
| :-------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `initialize`                                                                                              | **PASS** — `serverInfo.name="ReadyTrader-Crypto"`, `protocolVersion="2025-11-25"`                                                                                                                 |
| `list_tools()`                                                                                            | **PASS** — **29 tools**, matching `docs/TOOLS.md`'s generated catalog and README's "29 MCP tools" claim exactly (also CI-enforced by `tests/test_docs_tool_roster.py`, which passed in Section 3) |
| `call_tool` → `deposit_paper_funds(asset="USDC", amount=10000.0)`                                         | **PASS** — `isError=false`, `{"balance": 10000.0, "result": "Deposited 10000.0 USDC. New Balance: 10000.0"}`                                                                                      |
| `call_tool` → `validate_trade_risk(side="buy", symbol="BTC/USDT", amount_usd=600, portfolio_value=10000)` | **PASS** — `isError=false`, `result.allowed=false`, `reason="Position size too large (6.0%). Max allowed is 5%."` — reproduces the exact behavior README's own example #3 documents               |

Full 29-tool roster returned by `list_tools()`:

```
cancel_all_cex_orders, cancel_cex_order, deposit_paper_funds, fetch_ohlcv, get_cex_balance,
get_cex_capabilities, get_cex_my_trades, get_cex_order, get_crypto_price, get_financial_news,
get_free_news, get_latest_insights, get_market_regime, get_news, get_sentiment,
get_social_sentiment, list_cex_open_orders, list_cex_orders, list_cex_private_updates,
place_cex_order, post_market_insight, replace_cex_order, run_backtest_simulation,
start_cex_private_ws, stop_cex_private_ws, swap_tokens, transfer_eth, validate_trade_risk,
wait_for_cex_order
```

**Limit:** network-dependent market-data tools (`get_crypto_price`, `fetch_ohlcv`,
`get_sentiment`, live CEX order tools, etc.) were **not** exercised against real exchanges or
live endpoints in this pass, per instructions (avoid live endpoints; no live CEX keys are
configured in this environment). This matches README's own documented caveat that such calls
can return an environmental network error (`NET_501`) in a restricted network without that
indicating a server defect.

______________________________________________________________________

## 5. Frontend e2e (Playwright, `frontend/e2e/`) — LIMIT, not run

Per instructions, e2e was to run only if it completed within ~25 minutes; otherwise it is
recorded as a limit with the reason. That is the outcome here.

`npx playwright install chromium` was attempted twice in this environment:

1. First attempt: the 129.7 MiB Chromium download completed (100%), then extraction into
   `~/Library/Caches/ms-playwright/chromium-1194/.../Assets.car` stalled at a fixed byte
   offset (435,335 bytes) with **zero progress for over 7 minutes** (confirmed via `lsof` and
   repeated file-size checks) before being killed.
1. After clearing the cache directory and retrying with a hard `timeout 240`, the identical
   pattern reproduced: download completes, then extraction makes no further observable
   progress; the process was killed by the timeout (exit 124) rather than completing.

Two consecutive hangs at the same stage indicate a host-specific condition on this Mac (most
plausibly contention with other concurrent work on this shared machine during this
consolidation effort, or a local Gatekeeper/quarantine-scan stall on a freshly-downloaded
signed macOS app bundle) rather than a flaky one-off. `npm run e2e`, `next build`, and the
18-journey Playwright suite itself were **never reached** — no pass/fail signal exists for
`frontend/e2e/` from this pass. This is recorded as a **LIMIT**, not a pass or a fail.

What partial frontend evidence does exist from this pass: `npm run lint` (eslint), `npm run typecheck` (tsc), and `npm test` (vitest, 59 unit/integration tests) all passed — see 2.3 and
2.7. None of those exercise the built app against the real API harness the way the Playwright
suite does, so they are not a substitute for it.

______________________________________________________________________

## 6. Pass / fail / skip summary

| Check                                           | Result                               | Detail                                                                |
| :---------------------------------------------- | :----------------------------------- | :-------------------------------------------------------------------- |
| `ruff check .`                                  | PASS                                 | 0 issues                                                              |
| `ruff format --check .`                         | PASS                                 | 129 files clean                                                       |
| Frontend `eslint` (`npm run lint`)              | PASS                                 | 0 errors/warnings                                                     |
| `pytest` (backend)                              | **55 failed**, 543 passed, 5 skipped | all 55 failures = 1 root cause, Section 3; 5 skips = credential-gated |
| `bandit -r . -c bandit.yaml`                    | PASS                                 | 0 issues, 10,582 LOC scanned                                          |
| `pip-audit -r requirements.txt`                 | PASS                                 | 0 known vulnerabilities                                               |
| `pip-audit -r requirements.lock.txt`            | PASS                                 | 0 known vulnerabilities                                               |
| `npm audit --include=dev` (frontend)            | PASS                                 | 0 vulnerabilities / 549 deps                                          |
| `python tools/verify_docs.py`                   | PASS                                 | 0 issues across 5 checks                                              |
| `mdformat --check` (pre-PR files)               | PASS                                 | clean                                                                 |
| Frontend `tsc --noEmit`                         | PASS                                 | clean                                                                 |
| Frontend `vitest run`                           | PASS                                 | 59/59 tests                                                           |
| MCP stdio: `initialize`                         | PASS                                 | protocol 2025-11-25                                                   |
| MCP stdio: `list_tools`                         | PASS                                 | 29/29, matches `docs/TOOLS.md`                                        |
| MCP stdio: `deposit_paper_funds`                | PASS                                 | paper deposit succeeded                                               |
| MCP stdio: `validate_trade_risk`                | PASS                                 | correctly blocked oversized position                                  |
| Frontend e2e (Playwright, 18 journeys)          | **LIMIT — not run**                  | Chromium install hung twice; Section 5                                |
| Live CEX auth / live orders / live market tools | **LIMIT — not exercised**            | no live keys, by design/instructions                                  |
| Remote signer reachability                      | **LIMIT — not exercised**            | no remote signer configured                                           |
| Phase 4 live dust trades                        | **LIMIT — not exercised**            | explicitly out of scope, needs separate owner authorization           |

## 7. Limits (consolidated)

- **Python 3.13.14 used, not CI's pinned 3.12** — 3.12 is not installed on this Mac. Not shown
  to cause any problem (`pip check` clean, only the sandbox-file tests failed and those trace
  to an OS `rlimit` difference, not a Python-version difference) — but is a genuine,
  undisclosed difference from CI's exact interpreter and is noted rather than hidden.
- **55 pytest failures, all one root cause** (Section 3): this macOS host does not honor
  `RLIMIT_AS` the way the Linux CI runner does; the sandbox's own fail-closed self-check
  correctly refuses to run rather than executing unconstrained. Not independently re-verified
  on Linux in this pass; GitHub Actions' own last run on this exact SHA was green.
- **Frontend e2e not run** — Playwright's Chromium install hung twice in this environment
  (Section 5).
- **No live CEX API keys** — the CEX auth probe, live order placement, and live-market-data
  MCP tools were not exercised.
- **No remote signer configured/reachable** — `SIGNER_TYPE=remote` reachability and TLS were
  not verified.
- **No Phase 4 live dust trades performed** — explicitly out of scope; requires a separate,
  owner-authorized UAT pass (see `UAT.md`).
- **This Mac's `NODE_ENV=production` shell default** silently omits devDependencies from
  `npm ci`/`npm audit` unless overridden; every frontend command in this document was run with
  `NODE_ENV` explicitly unset to match CI (Section 1).

## 8. Reproduction (non-secret)

```bash
git clone --reference <local-mirror> https://github.com/up2itnow0822/ReadyTrader-Crypto.git
cd ReadyTrader-Crypto
python3.13 -m venv .venv   # CI pins 3.12; use 3.12 if available
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --no-deps -r requirements.lock.txt
.venv/bin/python -m pip check

env -u NODE_ENV npm ci --include=dev --prefix frontend
env -u NODE_ENV npm audit --include=dev --prefix frontend

PATH="$PWD/.venv/bin:$PATH" make check     # stops at first pytest failure on this host; see Section 3
PATH="$PWD/.venv/bin:$PATH" make security
PATH="$PWD/.venv/bin:$PATH" python tools/verify_docs.py
PATH="$PWD/.venv/bin:$PATH" mdformat --check docs README.md RUNBOOK.md SECURITY.md CONTRIBUTING.md CHANGELOG.md
PATH="$PWD/.venv/bin:$PATH" pip-audit -r requirements.lock.txt

env -u NODE_ENV npm run typecheck --prefix frontend
env -u NODE_ENV npm test --prefix frontend -- --run

# MCP stdio smoke (ad hoc client using the `mcp` Python SDK's stdio_client/ClientSession,
# launching `.venv/bin/python server.py` with PAPER_MODE=true, LIVE_TRADING_ENABLED=false,
# TRADING_HALTED=true, EXECUTION_MODE=cex, SIGNER_TYPE=null — see Section 4)
```

No live orders were placed. No secrets were used or written anywhere in this pass.
