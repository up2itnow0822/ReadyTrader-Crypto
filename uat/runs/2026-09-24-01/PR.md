## UAT run `2026-09-24-01` — ready for release review (2 items blocked on credentials)

Acting as the user, exercised every surface of ReadyTrader-Crypto end to end (MCP server over stdio
and in Docker, approval API over real HTTP, the Next.js dashboard and its Playwright suite, CLI and
examples, compose stacks, config, docs, the Smithery manifest, and the Falling Knife decision for
crypto), fixed every failure on this branch, and retested each fix with fresh evidence. Money paths
ran in paper mode or against a recording exchange client only; no live order was placed.

This PR also carries **Part 1 of the Falling Knife request for Crypto**: the Risk Guardian
(`validate_trade_risk`'s rules) now runs inside every order path, with market data for sizing.
Crypto ships **no price-based Falling Knife rule** because both pre-registered crypto rules failed
held-out validation (`docs/FALLING_KNIFE.md`, `research/falling_knife/`); the sentiment rule stays.

Two independent adversarial reviews ran against the finished log (REV-*: 17 findings, REV2-*: 10);
every finding was fixed, regression-tested and retested here.

**Totals:** 82 checks · 21 pass · 59 fail (59 fixed & verified) · 2 blocked · `make check` exit 0
(710 passed, 5 skipped; ruff, bandit, pip-audit, docs verify, mdformat) · `make security` exit 0 ·
dashboard lint/typecheck/61 unit tests/build pass · Playwright 18/18.

| Section | Pass | Fail | Verified fixed | Blocked |
|---|---|---|---|---|
| preflight | 10 | 0 | 0 | 0 |
| backend | 2 | 22 | 22 | 0 |
| data | 1 | 7 | 7 | 0 |
| memory | 1 | 0 | 0 | 0 |
| frontend | 3 | 3 | 3 | 0 |
| integrations | 1 | 2 | 2 | 2 |
| cli | 0 | 1 | 1 | 0 |
| config | 1 | 11 | 11 | 0 |
| docs | 0 | 13 | 13 | 0 |
| regression | 2 | 0 | 0 | 0 |

### What was broken and is now fixed
- **critical** BE-01 — Risk Guardian runs in the order path (README: every request is filtered; a 50% bet is blocked automatically) → Every order path (place_cex_order, swap_tokens, replace_cex_order; paper and live; before a proposal and again at approval) runs app/tools/trading.pre_trade_check / swap_check: the Risk Guardian sizes the exposure an order adds against the account (paper / exchange / signer wallet) and fails closed when it cannot value the order or read the account (or the account is worth nothing) (`9e25268`, `9c65746`)
- **critical** BE-04 — Paper mode never touches a real exchange account (cancel/replace/read tools) → In paper mode the exchange-order tools answer paper_mode_not_supported before any exchange client is built (`9e25268`)
- **critical** BE-05 — Live replace_cex_order passes the approval gate, allowlists and size limit → replace_cex_order is refused (approval_required) under approve_each and otherwise runs validate_cex_order and the Risk Guardian on the replacement order (`9e25268`)
- **critical** BE-12 — An operator can sign in to the dashboard API in production mode (DEV_MODE=false, bcrypt admin hash) → api_server uses bcrypt.checkpw/hashpw (72-byte limit handled; constant-time username and dev plaintext compares); PyJWT and bcrypt are runtime requirements; passlib removed; hash command updated in env.example, env.live.btc.example, docker-compose.yml (`d760186`)
- **critical** DOCK-01 — README Docker path: docker build -t readytrader-crypto . ; docker run -i --rm readytrader-crypto serves MCP over stdio → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`)
- **critical** REV-01 — Live Risk Guardian sizes an order at the market price, not the caller's → Orders are valued at the market-data price (a limit at max(limit, market)); no market price refuses an order that adds exposure; order_type passed from every path (`011fa78`)
- **high** BE-02 — Paper fills use the market price (a limit fills only when marketable; a market order ignores an invented price) → Paper place_cex_order fills at the market-data price: market orders ignore a passed price; a limit fills (at market) only when marketable, else limit_not_marketable (`9e25268`)
- **high** BE-03 — Paper swap_tokens trades at the market rate → Paper swap_tokens trades at the market rate (FROM/TO, inverse, or through USDT) and is risk-checked; paper_price_required when no rate (`9e25268`)
- **high** BE-08 — An approve_each proposal made by the MCP server can be approved from the API server / dashboard (UAT.md T5) → ExecutionStore takes EXECUTION_SESSION_ID; with persistence the database is the source of truth (list/confirm/cancel read it; confirm and cancel are conditional UPDATEs); proposals record paper_mode and /api/approve-trade answers 409 EXEC_313 in the other mode (`9e25268`)
- **high** CF-01 — Server started by an MCP client (README configs: absolute python + server.py, client's working directory) keeps its data in the repo → storage_paths.data_path anchors every default data file to <repo>/data (READYTRADER_DATA_DIR overrides; *_PATH still wins) (`9e25268`)
- **high** DATA-01 — Paper risk metrics: drawdown is the current fall from the peak; resting orders keep their reserved value → get_risk_metrics reports the current drawdown (max_drawdown_pct keeps the record); portfolio value counts funds reserved by resting orders (`9e25268`)
- **high** DOCK-02 — The image carries no local secrets or local data → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`)
- **high** DOCK-04 — docker-compose up -d (compose header) starts the API and MCP services with the shipped defaults → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`)
- **high** DOCK-05 — The BTC-live compose stack (docs/OPS_BTC_PRODUCTION.md) lets the dashboard approve the MCP server's proposals → Both live services get EXECUTION_DB_PATH=/app/data/execution.db and a required EXECUTION_SESSION_ID; env.live.btc.example sets EXECUTION_SESSION_ID=btc-live-desk-1 (`ccaa6c4`)
- **high** REV-02 — With the kill switch on, open orders can still be listed and cancelled → Reads and cancels pass allowed_while_halted=True; the emergency procedure is restart halted, cancel_all_cex_orders, revert to paper (`011fa78`, `6ef8957`)
- **high** REV2-01 — A contract symbol cannot be traded as spot to dodge the position check → Contract symbols never read a spot position; _order_args refuses a contract symbol with market_type=spot (`839bcb4`)
- **medium** BE-06 — A refused live order says why (kill switch, allowlist, size limit) → Live gates raise LiveGateRefused(code) and policy refusals keep their PolicyError code/message/data; only unexpected exceptions become cex_error (`9e25268`)
- **medium** BE-09 — approve_each proposes only an order the live policy allows → Policy (validate_cex_order / validate_swap / validate_transfer_native), then the Risk Guardian, run before _maybe_propose and again when the approved call executes (`84507d2`)
- **medium** CLI-01 — tools/setup_wizard.py (docs/ERRORS.md: 'Run python tools/setup_wizard.py') guides a new paper user correctly → ask() treats a closed stdin as no; the key report shows SIGNER_TYPE (env_private_key called out as dev-only), needs no exchange key in paper mode, lists feed keys as optional; a 451 from Binance explains MARKETDATA_EXCHANGES (`46b42fb`)
- **medium** DATA-02 — Asset codes are case-insensitive in the paper ledger → The paper ledger upper-cases asset codes (orders, deposits, lookups) (`9e25268`)
- **medium** DOC-03 — README configuration defaults match the code → README corrected (see commit) (`e152134`)
- **medium** DOC-04 — README feature list describes what ships → README corrected (see commit) (`e152134`)
- **medium** DOCK-03 — Containers keep the fail-closed kill-switch default → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`)
- **medium** FE-01 — Documented dashboard e2e command (UAT.md T6) runs on a fresh clone → e2e/constants.ts HARNESS_PYTHON (repo .venv, else python3, PW_PYTHON_PATH overrides) is used by playwright.config.ts and apiControl.ts; report in frontend/playwright-report; ESLint ignores playwright-report/ and test-results/ (`ce047ec`)
- **medium** INT-01 — A news/sentiment source that cannot answer is an error, not a result → News and sentiment sources raise intelligence.SourceError; get_financial_news, get_news, get_social_sentiment, get_free_news and get_sentiment return not_configured / source_unavailable (`9e25268`)
- **medium** REV-03 — The paper drawdown halt reads current equity and a deposit does not clear it → Snapshots record net deposits (valued when made); drawdown/daily loss read results net of deposits against the equity at the peak, with the current marked value appended; the Guardian marks prices before reading metrics (`011fa78`)
- **medium** REV-04 — A SELL on a crypto-quoted pair sizes the asset it acquires → A SELL into a non-cash quote sizes the acquired quote (CASH_QUOTES = USD stables + major fiat) (`011fa78`)
- **medium** REV-05 — The Docker build context excludes secrets in subfolders → Secret, key and database patterns are **/-prefixed (`e858eb3`)
- **medium** REV-06 — Docs say which Risk Guardian rules apply to live orders → Docs say the daily-loss and drawdown limits run on the paper account and are reported as inactive_rules live (`6ef8957`)
- **medium** REV-07 — The documented Docker MCP config keeps the paper account between sessions → Configs and README mount readytrader-crypto-data on /app/data (`e858eb3`)
- **medium** REV-17 — docker-compose.sentinel.yml keeps the readytrader service running → readytrader builds target api with the API's required settings (`e858eb3`)
- **medium** REV2-02 — The daily-loss rule measures today's loss → Baseline = previous UTC day's last snapshot, else the day-open mark (mark_day_open at the first risk check) (`839bcb4`)
- **medium** REV2-03 — Loss limits measure losses against the capital now in the account → Time-weighted performance index: each period's return excludes deposits; drawdown and daily loss read the index (`839bcb4`)
- **low** BE-07 — API server log lines carry the time of the event → log_event stamps ts_ms at emit time (`9e25268`)
- **low** CF-02 — Every variable the code reads is in env.example → env.example lists ONEINCH_API_KEY, LOG_LEVEL, CEX_* tuning, signing, OTEL, stores, EXECUTION_SESSION_ID, READYTRADER_DATA_DIR (`9e25268`)
- **low** CF-03 — env.example's signer is safe to start from → env.example: SIGNER_TYPE=null with the live signers listed and env_private_key described as development-only (`d9a23b2`)
- **low** DOC-01 — docs/TOOLS.md is what the README says: generated from the live registry → docs/TOOLS.md corrected tool by tool against the code (curated, roster-tested); generate_tool_docs.py prints the registry and refuses to overwrite TOOLS.md (`9e25268`, `e152134`)
- **low** DOC-02 — README prerequisites name what the install needs → README corrected (see commit) (`e152134`)
- **low** DOC-05 — README Agent Zero UI instructions run the image the README builds → README corrected (see commit) (`e152134`)
- **low** FK-01 — The crypto no-price-rule decision is reproducible as described → README says only the v2 scoring scripts check the hash and that git history cannot show freeze-before-score; FALLING_KNIFE.md says the same (`5506954`)
- **low** REV-08 — The dashboard labels the current drawdown correctly → Drawdown from peak + Max drawdown; stablecoin set matches the server (`2d8f827`)
- **low** REV-09 — A NaN amount is refused on every order path → Shared _order_args validation for place and replace; pre_trade_check refuses a non-positive or non-finite amount (`011fa78`)
- **low** REV-10 — transfer_eth refuses a NaN or negative amount before proposing → transfer_eth refuses a non-finite or non-positive amount with invalid_amount before policy or proposal (`011fa78`)
- **low** REV-11 — The paper account values every USD stablecoin the Guardian knows at 1 USD → paper_engine.USD_STABLES is the one list; trading imports it (`011fa78`)
- **low** REV-12 — get_social_sentiment says when a configured source fails → social_sentiment_report returns each source's state; all configured sources erroring answers source_unavailable (`e8290a8`)
- **low** REV-13 — Login takes the same time for an unknown username as for a wrong password → The password check runs for every username; both must pass (`e8290a8`)
- **low** REV-14 — API log lines carry a per-request request_id → request_id_middleware sets a per-request id (per connection on /ws); logs use _ctx(); X-Request-ID header (`e8290a8`)
- **low** REV-15 — RISK_PROFILE does what the docs say → Documented as reserved and not applied; removed from the smithery config schema and both Hermes samples (`e858eb3`, `3b58fa4`)
- **low** REV-16 — Hermes guide, smithery manifest and README match the server → Hermes guide, smithery description and README compose line match the server (`e858eb3`)
- **low** REV2-04 — Docs say which exits the Guardian treats as exits → Docs say derivatives positions are unknown and closing orders are sized; contract symbols need market_type swap/future (`2f4795e`)
- **low** REV2-05 — A paper deposit cannot end a drawdown halt → deposit_paper_funds refuses a non-stable asset it cannot price (paper_price_required); the engine comment says what direct callers get (`839bcb4`)
- **low** REV2-06 — The Falling Knife rule applies to what an order buys → On a crypto-quoted SELL the quote's sentiment is checked as a BUY of the quote; risk.sentiment_asset names it (`839bcb4`)
- **low** REV2-07 — Paper orders refuse contract symbols; the exchange gets the normalised order → Paper ledger refuses contract symbols; policy, proposal, exchange and summary get the normalised side/order_type (`839bcb4`)
- **low** REV2-08 — An unhandled API error still carries the request id and security headers → request_id_middleware catches, logs with the request id, answers JSON SYS_803 with security headers and X-Request-ID (`839bcb4`)
- **low** REV2-09 — Docs give the kill switch's default and how to use it → Default true; halting is a restart with TRADING_HALTED=true; README says reads and cancels still work (`2f4795e`)
- **low** REV2-10 — smithery.yaml passes its settings to the server → startCommand.configSchema lists the optional keys; commandFunction always sets the paper profile and passes the keys (`2f4795e`)

### Cross-check against the FOREX and Stocks reviews (`AR-*`)
The adversarial review of the FOREX and Stocks fixes found classes that could exist here too. Checked
in this repo: the API's auth is a per-route dependency (no path check a Host header could steer past),
prices are validated finite, the live gates answer first, and the image's user did not change. Three
did apply, and are fixed with regression tests that fail on the code before them and retested (the
44-probe regression sweep and the quality gate re-ran afterwards: REG-06, REG-07):
- **low** AR-01 — Every numeric tool parameter refuses true → Every numeric tool parameter is typed Number or Integer (a validator refuses booleans first). (`fdbdcd4`)
- **low** AR-02 — The API's own 429 and 500 answers carry CORS headers → CORS is added after them and wraps every answer. (`fdbdcd4`)
- **low** AR-03 — The docs say how the daily-loss baseline is taken → TOOLS.md gives the baseline and that it errs toward halting. (`fdbdcd4`)

### Still blocked (needs the owner)
- **INT-03** Keyed news and social sources (NewsAPI, CryptoPanic, X, Reddit) with real keys. Unblock: run `get_financial_news`, `get_news`, `get_social_sentiment` with `NEWSAPI_KEY`, `CRYPTOPANIC_API_KEY`, `TWITTER_BEARER_TOKEN`, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` set. Without keys each answers `not_configured`, verified (INT-01).
- **INT-04** Live exchange account, 1inch swaps and an EVM signer. Unblock: exchange sandbox keys, `ONEINCH_API_KEY`, a remote signer and RPC URLs, plus written authorization for any live step (Phase 4). Every order-path gate was verified against a recording exchange client.

### Review these fixes with extra care
- **Breaking, trading:** every order now passes the Risk Guardian (BE-01), valued at the market price, never the caller's (REV-01); orders that add exposure without a market price are refused. Crypto-quoted SELLs (ETH/BTC) are sized and checked against the bought asset's sentiment (REV-04, REV2-06). Contract symbols (`BTC/USDT:USDT`) need `market_type` swap/future (REV2-01).
- **Breaking, paper:** fills at the market price; limits only when marketable (BE-02); swaps at the market rate (BE-03); paper deposits of an asset with no price are refused (REV2-05). Drawdown and daily loss now use a time-weighted index (REV-03, REV2-02, REV2-03): a halt that deposits used to clear stays; a tiny loss after a top-up no longer halts.
- **Kill switch:** `TRADING_HALTED=true` now lets reads and cancels through (REV-02). The emergency procedure changed (restart halted, then `cancel_all_cex_orders`).
- **Auth / API:** login uses `bcrypt` directly and runs the password check for every username (BE-12, REV-13); per-request `X-Request-ID`, including on 500s (REV-14, REV2-08).
- **Approvals:** proposals record their mode and cross processes via `EXECUTION_SESSION_ID` with single-use approval (BE-08); the policy runs before a proposal is made (BE-09).
- **Docker/config:** `docker build .` is the MCP server; the image starts halted; `.dockerignore` is `**/` (REV-05); compose defaults changed (DOCK-04/05); the Smithery manifest always starts the paper profile (REV2-10).

### Evidence
Full log: [`uat/UAT-LOG.md`](uat/UAT-LOG.md) · captures under `uat/evidence/2026-09-24-01/` · regression tests in `tests/test_uat_2026_09_24.py` (one per code finding; each fails on the code before its fix).

### DOX pass
- `AGENTS.md` (root): Guardian contract (market-price sizing, crypto-quote and contract-symbol rules, time-weighted loss limits, one stablecoin list), kill switch exemptions, Docker/compose/smithery contracts, the regression-test index; Child DOX Index gains `uat/` and `research/`.
- `docs/AGENTS.md`: the emergency procedure and "settings are read at start-up".
- `frontend/AGENTS.md`: the e2e harness's Python and fixed prices (earlier in this run).
- `uat/AGENTS.md`: created by the UAT tooling.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01JoGpymL6LG3N8Mx7Btuxp5
