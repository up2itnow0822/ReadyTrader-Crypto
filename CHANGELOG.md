## Changelog

This project follows a lightweight changelog format. Major changes are summarized here to help operators and integrators understand what changed between versions.

### 0.2.0 — unreleased (pending UAT graduation)

`pyproject.toml` already declares `version = "0.2.0"`; this is that version's changelog entry
— previously everything below sat under an open-ended "Unreleased" heading with no version
boundary. **No git tag or GitHub Release exists for 0.2.0 yet** (`git tag -l` and
`gh release list` are both empty as of 2026-09-23): this heading records what has shipped to
`main`, not a released version. Graduation is gated on `UAT.md` and
`docs/uat/2026-09-23-reverification.md`.

**Merged PRs in this release, grouped by area** (each verified live against GitHub with
`gh pr view <n>` on 2026-09-23):

- **BTC production hardening & Hermes surface:** #3 (BTC production-minus-dust hardening +
  Hermes ops pack), #4 (SEC-001/002 — `/ws` JWT, `.env.live` gitignored)
- **Execution & paper-trading correctness:** #5 (paper order path, enum/string settings
  compare, `app/main.py` entrypoint, stale tool docs), #7 (closed issue #6 live-safety gaps), #9 (`EXECUTION_MODE=auto`
  routes like `hybrid`; closed issue #8)
- **Risk / Falling Knife sentiment gate:** #10 (made the rule reachable), #11 (fail-closed
  across degraded refreshes), #17 (Phase 1: 8%+ printed drop counts as bearish evidence)
- **Security & quality gates:** #12 (restored real CI — `ci.yml` had been an 8-line Node stub
  since 2026-03-11 with no Python gate running on push; closed that half of issue #2), #13 (M2
  back-end hardening: strategy sandbox isolation, approval-gate `ContextVar`, paper-ledger
  atomicity), #18 (sentinel signer: required Bearer auth, fail-closed without a token, no host
  port; `RemoteSigner` enforces `REMOTE_SIGNER_REQUIRE_TLS` — addresses issue #2's P0)
- **Documentation truth & operator dashboard:** #14 (M3 — removed phantom tool references,
  added `tests/test_docs_tool_roster.py` as a CI drift guard), #15 (M4 — Next.js
  approve/reject-trades dashboard with an 18-journey Playwright e2e suite under
  `frontend/e2e/`; not yet wired into a CI workflow)

**Not part of this version:**

- **#16** (Phase 0 autoimprove baseline) was opened, then **closed unmerged**: Bill closed it
  as superseded by #17, whose Phase 1 work already includes the Phase 0 `.autoimprove` docs.
  Listed here for the record, not as a shipped change.

### Unreleased

- **Public-release UAT, 2026-09-24** (`uat/UAT-LOG.md`, run `2026-09-24-01`):

  - **Cross-checked against the FOREX and Stocks reviews** (AR-01..AR-03): `true`/`false` sent
    where a tool takes a number is refused by MCP argument validation (all 18 numeric parameters
    took `true` as 1: `deposit_paper_funds(amount=true)` deposited 1). CORS now wraps every API
    answer, so a rate-limit `429` or the JSON `500` reaches the dashboard instead of reading as a
    network error. The docs say how the daily-loss baseline is taken.
  - **Breaking — the Risk Guardian runs on every order.** `place_cex_order`, `swap_tokens`,
    `replace_cex_order` and approved proposals now refuse (`risk_blocked`, with the numbers in
    `error.data.risk`) what `validate_trade_risk` would refuse; before, only that advisory tool
    applied the rules and a 50% bet executed. The part of an order that adds exposure is sized
    against the account (paper account; the exchange account for live CEX orders; the signer
    wallet for live swaps); selling what is held is an exit; an order that adds exposure and
    cannot be valued, or whose account cannot be read, fails closed. Live orders are checked
    before a proposal is made and again when it is approved. Crypto has no price-based Falling
    Knife rule: both pre-registered rules failed held-out validation (`docs/FALLING_KNIFE.md`,
    `research/falling_knife/`).
  - **Breaking — paper fills at the market.** A paper market order ignores any price passed; a
    limit fills (at the market) only when marketable, else `limit_not_marketable`; paper swaps
    trade at the market rate (they filled at a fixed 1.0: 1 ETH became 1 USDC).
  - **Paper mode never reaches an exchange account:** `get_cex_order`, `cancel_cex_order`,
    `cancel_all_cex_orders`, `list_cex_*`, `get_cex_my_trades`, `replace_cex_order` and
    `wait_for_cex_order` answer `paper_mode_not_supported` (they called the real exchange with
    any configured keys, past the kill switch).
  - **`replace_cex_order` (live)** is refused under `approve_each` (`approval_required`) and
    otherwise passes the same policy checks as `place_cex_order`; it skipped the approval gate,
    the allowlists and `MAX_CEX_ORDER_AMOUNT`.
  - **Refusals name their rule:** `live_trading_disabled`, `trading_halted`,
    `execution_mode_blocked` and the policy codes (`symbol_not_allowed`, ...) instead of
    `cex_error` "Exchange operation failed.".
  - **Approvals across processes:** `EXECUTION_SESSION_ID` (with a shared `EXECUTION_DB_PATH`)
    lets the API server and the dashboard see and approve the MCP server's proposals; approval is
    single-use across processes; a proposal executes only in the mode it was made in (`EXEC_313`).
  - **Paper account:** drawdown is the current fall from the peak (`max_drawdown_pct` keeps the
    record; one dip used to block BUYs forever); funds held by resting limit orders count as
    equity; asset codes are case-insensitive.
  - **Data files** default to `<repo>/data/` (or `READYTRADER_DATA_DIR`), not the MCP client's
    working directory; the server died at startup when that folder was not writable.
  - **News and sentiment sources** that cannot answer return `not_configured` /
    `source_unavailable` instead of an `ok: true` payload holding the error text.
  - **Dashboard login in production works.** With `DEV_MODE=false` every login answered 401
    (passlib 1.7.4 cannot drive the pinned bcrypt 5.0.0) or, in the Docker API image, 500 (no
    passlib); `api_server.py` now uses `bcrypt` directly, and PyJWT and bcrypt are runtime
    requirements (passlib dropped). Generate the hash with
    `python -c "import bcrypt; print(bcrypt.hashpw(b'...', bcrypt.gensalt()).decode())"` and keep it
    in single quotes in `.env`.
  - **Docker:** `docker build .` now produces the MCP server (it produced the API server, which
    refused to start, so every README Docker config failed); the API is `--target api`. The image
    starts halted (`TRADING_HALTED=true`); `.dockerignore` keeps every `.env*`, key file, local
    database, virtualenv, `.git` and the dashboard out of the build context (a gitignored `.env.live`
    was baked into the image). `docker-compose.yml` starts with its own defaults (null signer, API
    auth on, `API_JWT_SECRET` required up front) and both compose files share a proposal session
    between the api and mcp services.
  - The live policy runs before a proposal is made (approve_each proposed orders the allowlists
    would refuse); `env.example` starts from `SIGNER_TYPE=null`; `tools/setup_wizard.py` no longer
    flags a missing raw `PRIVATE_KEY` and survives a closed stdin.
  - API server log lines carry the time of the event; `validate_trade_risk` rejects a bad side or
    a non-positive amount (`invalid_request`); the dashboard e2e suite finds the repo's `.venv`.
  - Docs: README feature list, defaults (`TRADING_HALTED` defaults to `true`), prerequisites and
    examples corrected; `docs/TOOLS.md` checked against the code (it described simulated data and
    fields the tools do not return); `tools/generate_tool_docs.py` prints the live registry
    instead of overwriting the curated catalog.
  - **Adversarial review of the UAT run (two rounds, `REV-*`, `REV2-*`):**
    - **Breaking — the Risk Guardian values orders at the market.** It sized an order at the
      price the caller passed, so a live market BUY carrying `price=1` passed the 5% cap. Orders
      are valued at the market-data price (a limit at the higher of limit and market); with no
      market price an order that adds exposure is refused. A SELL into a crypto quote (ETH/BTC)
      buys the quote asset: it is sized, and checked against that asset's sentiment.
    - **Breaking — contract symbols.** `BTC/USDT:USDT` with `market_type=spot` was sized as an
      exit of the spot balance while ccxt sent it to the futures account; it is now refused as
      spot, never sized from a spot balance, and refused by the paper ledger (spot only).
    - **Kill switch:** `TRADING_HALTED=true` no longer blocks reading the account or cancelling
      orders (`get_cex_*`, `list_cex_*`, `cancel_*`, `wait_for_cex_order`). The documented
      `POST /api/emergency-cancel-all` never existed; the procedure is restart halted, then
      `cancel_all_cex_orders` (`docs/LIVE_TESTING_PROTOCOL.md` 4.5).
    - **Paper loss limits** read a time-weighted performance index: deposits are neither gains
      nor losses (a top-up used to end a drawdown halt, or make a 0.1% loss read as 10%), the
      account's current marked value counts before the next trade, and the daily baseline is
      the previous day's last snapshot or the day's first risk check (a week-old snapshot used
      to be "the start of today"). `deposit_paper_funds` refuses an asset it cannot price. Live
      orders report the daily-loss and drawdown rules as `inactive_rules` (docs said they ran).
    - Refused: NaN/negative amounts on `replace_cex_order`, `pre_trade_check` and
      `transfer_eth` proposals. One stablecoin list (8) for the paper account, the Guardian and
      the dashboard. `get_social_sentiment` answers `source_unavailable` when every configured
      source failed. Login runs the password check for every username (timing showed which
      usernames exist). API log lines and responses carry a per-request `request_id` /
      `X-Request-ID`, unhandled errors included.
    - Docker: `.dockerignore` patterns now match in subfolders; the documented MCP configs mount
      a named volume so the paper account persists; `docker-compose.sentinel.yml` runs the API
      stage. `smithery.yaml` passes its settings (it had none wired) and always starts paper.
      The dashboard labels the current drawdown and the record separately. `RISK_PROFILE` is
      documented as not applied.

- **`EXECUTION_MODE=auto` routing (issue #8):** `venue_allowed()` now treats `auto` — the `Settings` default — like `hybrid` (either venue per call). Previously the default silently denied every live venue check (`Execution blocked by EXECUTION_MODE=auto …`) for operators who never set `EXECUTION_MODE`; `dex`/`cex`/`hybrid` behavior and the fail-closed denial of unknown values are unchanged.

- **Falling Knife (paper/CI):** `intelligence/sentiment.py` now treats a printed 8%+ drop
  (`-10%`, `down 11%`) as bearish even without a lexicon panic word, and three directional
  texts are enough consensus when such a print is present. Promo ` - 92% WIN RATE` does not
  count. In-repo fixture crashes `crash-05` and `crash-02` now block; the altcoin-implosion
  `known_limit` remains.

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
  **Known limitation (fixed 2026-09-24 by `EXECUTION_SESSION_ID`, above):** `ExecutionStore` deliberately ignores proposals created
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
  runs the real Python gate on every push and PR (`make check`, `make security`, `pip-audit -r requirements.lock.txt`, `npm ci`), so the separately staged Python CI workflow was dropped as
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
