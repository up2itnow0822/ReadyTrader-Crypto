## Changelog

This project follows a lightweight changelog format. Major changes are summarized here to help operators and integrators understand what changed between versions.

### Unreleased

- **Breaking (strategy sandbox):** agent-supplied strategy code (`run_backtest_simulation`, the
  stress lab) now runs in an isolated child process (`strategy_sandbox.py`) instead of
  in-process. Strategies can no longer import or reference `pandas`, `ta`, `string`, or
  `random` — only `math` — and private/underscore-prefixed names and `.format`/`.format_map`
  attribute access are rejected at a static pre-check. The contract is unchanged:
  `on_candle(price, rsi, state) -> "buy"|"sell"|"hold"` plus an optional top-level `PARAMS`
  dict. Limits: 20,000-character source, a wall-clock timeout, and (on POSIX) a 1 GiB address-
  space rlimit for the child. This is not a filesystem jail — the child runs as the same OS
  user; see `docs/STRATEGY_SANDBOX.md` for the full threat model and stated limitation.
- **Security (approval gate):** the approval gate is no longer switched off process-wide while
  an approved order executes — `app.tools.execution.approved_execution` is now a per-call
  `ContextVar`, so a second call in the same process during that window still gets a proposal
  instead of executing unchecked. Rejecting a proposal now requires the same authority as
  approving it (admin session or the proposal's `confirm_token`). New error codes: `AUTH_604`
  (not allowed to approve/reject), `EXEC_308` (already executed, 409), `EXEC_309` (unknown,
  404), `EXEC_310` (expired, 410), `EXEC_311` (cancelled/already-confirmed, 409), `EXEC_312`
  (malformed proposal or an order the engine refused, 422 — a refused order is never recorded
  as executed). `POST /api/approve-trade` accepts an admin JWT in place of `confirm_token`
  (token-less approval; live trading still requires auth per settings validation, so in
  practice this only fires in paper mode with auth off). JWTs must now carry `exp` and `sub`.
  **Known limitation, not yet fixed:** `ExecutionStore` deliberately ignores proposals created
  by a different process (a per-process session id — see `execution_store.py`'s module
  docstring). The MCP server and the API server are separate processes in every documented
  deployment, so a proposal created via an MCP tool call is invisible to, and cannot currently
  be approved or rejected from, the dashboard/API process. See
  `docs/ARCHITECTURE.md#approval-gate`.
- **Security (review follow-ups):** the sandbox child no longer has its rlimits applied from a
  `preexec_fn`. That runs Python in the forked child before `exec`, where only
  async-signal-safe work is allowed; in a multithreaded host a lock held at fork time can
  deadlock the child, and because `Popen()` does not return until `exec`, the parent's
  wall-clock timeout would never start and the calling worker would hang indefinitely. The
  child now applies its own limits after `exec` and still verifies them independently (fail
  closed); session isolation comes from `start_new_session=True`. Alongside that: non-finite
  numbers can no longer reach an approval summary (Starlette serializes with
  `allow_nan=False`, so one NaN amount made `GET /api/pending-approvals` return 500 for every
  operator until it expired); the stress lab validates strategy source before generating any
  scenarios, instead of after; and `deposit_paper_funds` returns an error envelope when the
  engine refuses a deposit at the accumulated-balance cap, rather than `ok: true` carrying the
  text "Deposit refused".
- **Security (dependencies):** `cryptography` 50.0.0, `fastapi` 0.133.0, `starlette` 1.3.1 (all
  bumped to clear pip-audit advisories), `RestrictedPython` 8.4 (reviewed for its wider builtin
  surface). `pip-audit -r requirements.txt` is clean.
- **Fixed (paper ledger):** paper orders (`place_cex_order`, `swap_tokens` in paper mode) and
  `deposit_paper_funds` now validate input and move funds atomically — a trade either happens
  and is reported in `data.fill` (numeric `side`, `symbol`, `amount`, `price`, `total_value`,
  `quote`), or nothing changes and the response is an error envelope with one of
  `invalid_symbol` | `invalid_side` | `invalid_amount` | `invalid_price` | `insufficient_funds`.
  Amounts/prices/deposits are capped at 1e12 per call and balances at 1e15 so tool output can
  never contain an infinity. Paper `swap_tokens` no longer rewrites the mark-to-market price
  cache (it fills at a synthetic 1.0, which is not a market price). See `docs/ERRORS.md`.
- **Fixed (data contracts):** new `app/core/jsonio.py` is now the one place every tool module
  serializes its JSON envelope through (`{"ok": ..., "data"/"error": ...}`), including safe
  handling of pandas/numpy scalars, Decimal, datetime, enums, and NaN/Infinity (never emitted
  as bare non-JSON tokens). `fetch_ohlcv` now returns both an ISO 8601 UTC `timestamp` and an
  integer `timestamp_ms` per candle, plus float OHLCV. `get_crypto_price` adds numeric `price`,
  `source`, and `timestamp` fields alongside its existing prose `result` sentence.
- **Docs truth (this milestone):** removed every phantom/stale MCP tool reference from shipped
  docs (`get_health`, `place_limit_order`, `check_orders`, `get_address_balance`,
  `run_synthetic_stress_test` presented as a tool, `get_ticker`/`start_marketdata_ws` presented
  as tools, a fabricated risk-disclosure-consent error taxonomy in `docs/ERRORS.md`, and a
  fully stale `prompts/READYTRADER_PROMPT_PACK.md`). Added `tests/test_docs_tool_roster.py`,
  which builds the real tool roster from `server.py` and fails the build on any future phantom
  reference or a `docs/TOOLS.md` that drifts from the registry. Added `docs/STRATEGY_SANDBOX.md`
  and an `## Approval gate` section in `docs/ARCHITECTURE.md`. Corrected the README's "CI/CD
  Quality Gates" table, which claimed a `mypy` gate that does not exist anywhere in this repo,
  and listed CodeQL/trivy/trufflehog as per-PR gates when they run on a schedule/dispatch
  (`security-audit.yml`) or on a tagged release (`release.yml`). `.github/workflows/ci.yml` now
  runs the real Python gate on every push and PR (`make check`, `make security`, `pip-audit -r
  requirements.lock.txt`, `npm ci`), so the separately staged Python CI workflow was dropped as
  redundant. `pyproject.toml` keeps `requires-python = ">=3.12"`: an earlier draft of this
  milestone relaxed it to `>=3.11` after a green full-suite run there, but the pinned lock now
  contains `numpy==2.5.3`, which requires >=3.12 — a 3.11 user could not install the locked
  set. `examples/stress_test_demo.py`'s closing line no longer tells the reader to run
  `run_synthetic_stress_test` "via MCP"; it is a Python function, not an MCP tool (see
  `docs/STRATEGY_SANDBOX.md`). Root `AGENTS.md` had its entire DOX framework duplicated (two
  near-identical copies); consolidated to one copy, added Work Guidance bullets for `jsonio`,
  `strategy_sandbox.run_strategy` as the only strategy-execution path, and the token-less-
  approval/`confirm_as_operator`/`approved_execution` HTTP-admin-only boundary, added
  Verification entries for the sandbox/approval/paper-ledger/JSON-contract/docs-roster test
  files, and added a `frontend/AGENTS.md` Child DOX Index row for the operator dashboard
  contract landing separately. Ran `mdformat` on every file this milestone touched that it
  flagged as unformatted — whitespace/table-alignment only, no content change.
- **Falling Knife protection was unreachable (fixed):** `analyze_social_sentiment` fetched tweets and Reddit titles but never read them; the score was `+0.2` per source that returned anything, so it could only be `0.0`, `0.2` or `0.4` and the Risk Guardian's `sentiment_score < -0.5` rule could never fire. Separately, the score was cached under the raw string passed to `get_social_sentiment` (`"BTC"`) while `validate_trade_risk` looked it up by pair (`"BTC/USDT"`), so the trade check always read neutral. The score is now a deterministic, local bull-bear spread over the fetched text (`intelligence/sentiment.py`: VADER's rule engine over a market-only vocabulary, no model or network call), cached per base asset. `validate_trade_risk` adds a `sentiment` block (`score`, `status`, sample counts, age) so missing, unconfigured or thin data is reported instead of passing as a measured neutral, and a degraded refresh cannot erase a bearish reading that is still fresh. On 86 simulated feeds written blind to the vocabulary the rule blocked 12 of 22 crashes and none of 50 calm, red, green or contested days; a 17-feed sample is pinned in `tests/fixtures/sentiment_feeds.json`. New dependency: `vaderSentiment==3.3.2`. See `docs/SENTIMENT.md`.
- **Live-safety gaps (issue #6):** `start_cex_private_ws` now requires live execution to be allowed (`LIVE_TRADING_ENABLED=true`, not `TRADING_HALTED`) before opening a private stream; `stop_cex_private_ws` and `list_cex_private_updates` remain available so a halt can still be observed/stopped. Paper `place_cex_order` no longer fills at a fabricated `100000.0` placeholder when `price` is omitted — it resolves a reference price from the market-data bus or fails with `paper_price_required`. Paper-mode `get_cex_balance` returns the paper wallet's balances without requiring CEX credentials. Docs: `env.example`/`RUNBOOK.md` now note that `ALLOW_*`/`MAX_*` policy limits are enforced on the live order path only; `RUNBOOK.md` no longer references the unregistered `start_marketdata_ws`/`stop_marketdata_ws`/`get_ticker` tools.
- **Fail-closed production gates:** `TRADING_HALTED` defaults to `true`; `api_server` refuses start when `DEV_MODE=false` without JWT auth or with CORS `*`; live/non-paper settings require auth + non-wildcard CORS; `SIGNER_TYPE=env_private_key` forbidden when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`.
- **SEC-001/002:** `/ws` requires JWT when auth is on; `.env.live` / `.env.*.local` gitignored; live MCP compose gets auth/CORS env so Settings can boot.
- **BTC ops pack:** `env.live.btc.example`, `docs/OPS_BTC_PRODUCTION.md`, Hermes stdio MCP guide `docs/HERMES_INTEGRATION.md`, UAT harness `examples/paper_btc_uat.py`, UAT evidence `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md`.
- **Hermes skill:** public package [readytrader-crypto-hermes](https://github.com/up2itnow0822/readytrader-crypto-hermes), installed at runtime into `~/.hermes/skills/` via `hermes skills install up2itnow0822/readytrader-crypto-hermes/skills/finance/readytrader-crypto --category finance` (`optional-skills/` in that package is its own contribution tree and is never loaded).
- **DOX:** root `AGENTS.md` plus `signing/` and `docs/` child contracts.
- **Live compose:** wire `ALLOW_CEX_SYMBOLS` / `ALLOW_CEX_MARKET_TYPES`; default `EXECUTION_MODE=cex` for BTC spot.

### 0.1.0 (2025-12-29)

- **Agent-first MCP server** for crypto trading workflows (paper mode + optional live execution).
- **Safety governance**: risk disclosure consent gate, kill switch, optional approve-each execution with replay protection.
- **Execution breadth**: CEX via CCXT + DEX swaps (1inch builder) with execution routing (`dex`/`cex`/`hybrid`).
- **Market data quality**: websocket-first public streams (opt-in), MarketDataBus freshness selection, plugin feed interface.
- **Stress lab**: deterministic synthetic stress testing with exportable artifacts + heuristic recommendations.
- **Operator layer**: structured logs with redaction, metrics snapshots, optional Prometheus text export, runbook and error catalog.
- **Custody hardening**: signer abstraction (env/keystore/remote), signing intents, defense-in-depth signer policy wrapper.
