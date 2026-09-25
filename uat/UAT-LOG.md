# UAT Log

> Rendered by `uat_log.py render` from `uat/runs/<run-id>/findings.json`. Do not hand-edit;
> update the ledger and re-render. Latest run is expanded; earlier runs are summarized.

## Run 2026-09-24-01 — ReadyTrader-Crypto

- Branch: `uat/2026-09-24-crypto`  |  Base: `main@67fd39c`
- Started: 2026-09-24T16:18:30+00:00  |  Updated: 2026-09-25T12:33:05+00:00
- Scope: In: MCP server (stdio), FastAPI approval API, Next.js dashboard, CLI/examples, config, docs, registry manifest, the Falling Knife decision for crypto. Money paths paper only; no live orders, no dust trades (Phase 4 needs Bill's authorization); signer paths with test keys only.
- Verdict: **CLEAN with BLOCKED items**
- Totals: 82 checks · 21 pass · 59 fail (59 verified fixed, 0 open, 0 fixed-unverified, 0 regressed, 0 wontfix) · 2 blocked

### User journeys exercised

- As an operator evaluating ReadyTrader-Crypto, I install it from the README and connect it to my MCP client (Claude Desktop / Agent Zero / Hermes) so that my agent can research and paper-trade BTC
- As an AI agent, I research BTC (price, candles, sentiment, news) and paper-trade it through the Risk Guardian so that I can practice with zero risk
- As an operator running approve_each, I see each proposal on the dashboard and approve or reject it so that nothing executes without me
- As an operator preparing live BTC, I configure the live profile (env.live.btc.example, signer, kill switch) and confirm it refuses anything unsafe so that a mistake cannot cost money
- As a Hermes user, I install the readytrader-crypto skill and its stdio MCP server so that Hermes runs the paper BTC workflow
- As a strategy developer, I backtest and stress-test a strategy in the sandbox so that I know how it behaves before it trades

### Section summary

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

### Findings (61)

#### BE-01 — Risk Guardian runs in the order path (README: every request is filtered; a 50% bet is blocked automatically)  [FAIL · critical · **VERIFIED**]

- Section: `backend`  |  Journey: trade BTC in paper behind the Risk Guardian
- Steps: paper: deposit 10000 USDT; validate_trade_risk buy 5000/10000; place_cex_order buy 0.05 BTC @100000 (5000 USDT)
- Expected: place_cex_order refused with the same Risk Guardian reason validate_trade_risk gives
- Observed: validate_trade_risk: allowed=false (Position size 50%); place_cex_order executes the same 50% buy; no order path (place/replace/swap, paper or live) calls the Risk Guardian
- Evidence: [BE-01.txt](evidence/2026-09-24-01/BE-01.txt)
- Fix: Every order path (place_cex_order, swap_tokens, replace_cex_order; paper and live; before a proposal and again at approval) runs app/tools/trading.pre_trade_check / swap_check: the Risk Guardian sizes the exposure an order adds against the account (paper / exchange / signer wallet) and fails closed when it cannot value the order or read the account (or the account is worth nothing)
  - Root cause: The Guardian lived only in the advisory validate_trade_risk tool; no order path called it
  - Files: `app/tools/trading.py`, `app/tools/execution.py`, `risk_manager.py`
  - Commit: `9e25268,9c65746`
  - Regression test: tests/test_uat_2026_09_24.py::test_paper_order_is_refused_for_the_same_reason_validate_trade_risk_gives
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — Same MCP session: validate_trade_risk refuses 5000/10000 and place_cex_order now answers risk_blocked for the 0.05 BTC buy (exposure 4211.88 USD vs 10000 equity, error.data.risk has the numbers); the wallet stays 10000 USDT · evidence: [BE-01-retest.txt](evidence/2026-09-24-01/BE-01-retest.txt)
- Retest 2 (2026-09-24T19:44:24+00:00): **PASS** — Strengthened with the live path: over MCP (paper) the 50% order is refused risk_blocked with the same reason validate_trade_risk gives; live (recording exchange) every oversized order is refused at the market price whatever price it carries, and a 840 USD market BUY passes and reaches the exchange. · evidence: [BE-01-retest-2.txt](evidence/2026-09-24-01/BE-01-retest-2.txt)

#### BE-04 — Paper mode never touches a real exchange account (cancel/replace/read tools)  [FAIL · critical · **VERIFIED**]

- Section: `backend`
- Steps: PAPER_MODE=true TRADING_HALTED=true; call replace_cex_order, cancel_cex_order, cancel_all_cex_orders, get_cex_order, list_cex_open_orders with a recording exchange client
- Expected: paper_mode_not_supported (nothing reaches an authenticated exchange client)
- Observed: all five reach the authenticated client (replace_order places a new BTC/USDT buy 5 @90000); _require_live_allowed returns early in paper mode, so the kill switch and live flags are skipped; with CEX keys in .env a 'zero-risk' paper session edits the real account
- Evidence: [BE-04.txt](evidence/2026-09-24-01/BE-04.txt)
- Fix: In paper mode the exchange-order tools answer paper_mode_not_supported before any exchange client is built
  - Root cause: _require_live_allowed returns early in paper mode, so the account tools fell through to the authenticated exchange client
  - Files: `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_paper_mode_never_reaches_an_exchange_account
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — all five tools answer paper_mode_not_supported; the recording exchange client was called 0 times · evidence: [BE-04-retest.txt](evidence/2026-09-24-01/BE-04-retest.txt)

#### BE-05 — Live replace_cex_order passes the approval gate, allowlists and size limit  [FAIL · critical · **VERIFIED**]

- Section: `backend`
- Steps: live, approve_each, ALLOW_CEX_SYMBOLS=ETH/USDT, MAX_CEX_ORDER_AMOUNT=0.1; place_cex_order then replace_cex_order(123 -> BTC/USDT buy 5)
- Expected: replace refused (needs approval; BTC/USDT not allowlisted; 5 > 0.1)
- Observed: place_cex_order proposes (approval_required), but replace_cex_order sends replace_order BTC/USDT buy 5 @90000 straight to the exchange: no proposal, no validate_cex_order, no Risk Guardian
- Evidence: [BE-05.txt](evidence/2026-09-24-01/BE-05.txt)
- Fix: replace_cex_order is refused (approval_required) under approve_each and otherwise runs validate_cex_order and the Risk Guardian on the replacement order
  - Root cause: replace_cex_order only called validate_cex_access and never _maybe_propose
  - Files: `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_live_replace_passes_policy_and_the_guardian
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — place_cex_order still proposes; replace_cex_order now answers approval_required and sends nothing (0 exchange calls). The probe now also gives the Guardian's account read a 100,000 USDT recorder so the gates, not an unreadable account, decide. Policy/Guardian on an auto-mode replace: tests/test_uat_2026_09_24.py::test_live_replace_passes_policy_and_the_guardian · evidence: [BE-05-retest.txt](evidence/2026-09-24-01/BE-05-retest.txt)

#### BE-12 — An operator can sign in to the dashboard API in production mode (DEV_MODE=false, bcrypt admin hash)  [FAIL · critical · **VERIFIED**]

- Section: `backend`  |  Journey: As an operator running approve_each, I see each proposal on the dashboard and approve or reject it so that nothing executes without me
- Steps: (a) pip install -r requirements-dev.txt: login with a correct bcrypt hash; the documented hash generator; (b) the Docker API image: the same login
- Expected: 200 with a token for the right password, 401 for a wrong one; the documented generator prints a hash
- Observed: (a) the right password is refused 401 (passlib 1.7.4 cannot drive bcrypt 5.0.0, the pinned version) and the documented generator 'from passlib.hash import bcrypt; bcrypt.hash(...)' raises ValueError; (b) the image has no passlib (only in requirements-dev.txt): 500 'Password hashing not available'. Nobody can approve a trade from the dashboard in production; e2e passed only because its harness runs DEV_MODE=true with a plaintext password
- Evidence: [BE-12.txt](evidence/2026-09-24-01/BE-12.txt)
- Fix: api_server uses bcrypt.checkpw/hashpw (72-byte limit handled; constant-time username and dev plaintext compares); PyJWT and bcrypt are runtime requirements; passlib removed; hash command updated in env.example, env.live.btc.example, docker-compose.yml
  - Root cause: passlib 1.7.4 is incompatible with bcrypt >= 4.1, and the auth libraries were only dev requirements
  - Files: `api_server.py`, `requirements.txt`, `requirements-dev.txt`, `requirements.lock.txt`, `env.example`, `env.live.btc.example`, `docker-compose.yml`
  - Commit: `d760186`
  - Regression test: tests/test_uat_2026_09_24.py::test_production_login_with_a_bcrypt_hash
- Retest 1 (2026-09-24T18:21:59+00:00): **PASS** — venv: right password 200 with a token, wrong 401; Docker API image: right password 200 with a token (was 500). (The probe's last line shows the old passlib generator still fails in a venv that has passlib; the documented command is now bcrypt.hashpw, which made the hash used here.) · evidence: [BE-12-retest.txt](evidence/2026-09-24-01/BE-12-retest.txt)
- Retest 2 (2026-09-24T19:41:01+00:00): **PASS** — Strengthened: in the Docker API image (DEV_MODE=false, bcrypt hash) the right password gets a token; a wrong password and a wrong username get 401; no token -> 401. · evidence: [BE-12-retest-2.txt](evidence/2026-09-24-01/BE-12-retest-2.txt)

#### DOCK-01 — README Docker path: docker build -t readytrader-crypto . ; docker run -i --rm readytrader-crypto serves MCP over stdio  [FAIL · critical · **VERIFIED**]

- Section: `config`  |  Journey: As an operator evaluating ReadyTrader-Crypto, I install it from the README and connect it to my MCP client (Claude Desktop / Agent Zero / Hermes) so that my agent can research and paper-trade BTC
- Steps: build the base checkout the README's way (sandbox proxy-CA shim only), run it with the README's MCP client config (docker run -i --rm -e PAPER_MODE=true readytrader-crypto)
- Expected: 29 tools over stdio
- Observed: the default build target is the API server (FROM api AS production, CMD uvicorn); with the image's DEV_MODE=false it refuses to start (RuntimeError: API_AUTH_REQUIRED must be true...) and the MCP client gets 'Connection closed'. Every Docker config in the README (standalone, Agent Zero, Claude Desktop) is affected
- Evidence: [DOCK-01.txt](evidence/2026-09-24-01/DOCK-01.txt)
- Fix: See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID
  - Root cause: The Dockerfile's default stage, ignore file and compose defaults predated the fail-closed rules
  - Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `README.md`
  - Commit: `cd6076b`
- Retest 1 (2026-09-24T18:23:36+00:00): **PASS** — docker build . now yields the MCP server: the README's docker run -i config lists 29 tools, deposits and reads the paper wallet · evidence: [DOCK-01-retest.txt](evidence/2026-09-24-01/DOCK-01-retest.txt)

#### REV-01 — Live Risk Guardian sizes an order at the market price, not the caller's  [FAIL · critical · **VERIFIED**]

- Section: `backend`
- Observed: Live market BUY 1 BTC with price=1 (market 84,000) passes the 5% cap on a 100k account and is sent to the exchange; pre_trade_check(price=1) sizes it at 1 USD.
- Evidence: [REV-01.txt](evidence/2026-09-24-01/REV-01.txt)
- Fix: Orders are valued at the market-data price (a limit at max(limit, market)); no market price refuses an order that adds exposure; order_type passed from every path
  - Root cause: pre_trade_check took reference = the caller's price when one was given
  - Files: `app/tools/trading.py`, `app/tools/execution.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_live_market_order_is_sized_at_the_market_not_the_callers_price
- Retest 1 (2026-09-24T19:36:35+00:00): **PASS** — Market BUY 1 BTC with price=1, price=0.01, a futures limit SELL @1, a replace and an approve_each order are all valued at 84,000 (the market) and refused risk_blocked; no exchange call. · evidence: [REV-01-retest.txt](evidence/2026-09-24-01/REV-01-retest.txt)

#### BE-02 — Paper fills use the market price (a limit fills only when marketable; a market order ignores an invented price)  [FAIL · high · **VERIFIED**]

- Section: `backend`  |  Journey: trade BTC in paper behind the Risk Guardian
- Steps: market 84520; limit BUY 0.005 @40000; market SELL 0.005 with price=200000
- Expected: limit buy below market refused or left unfilled; market order fills at the market price
- Observed: both filled at the caller's price; 10000 USDT became 10800 USDT from two round-trip orders (fabricated +8% PnL)
- Evidence: [BE-02.txt](evidence/2026-09-24-01/BE-02.txt)
- Fix: Paper place_cex_order fills at the market-data price: market orders ignore a passed price; a limit fills (at market) only when marketable, else limit_not_marketable
  - Root cause: The paper branch filled at whatever price the caller passed
  - Files: `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_paper_limit_below_market_is_not_filled
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — limit BUY 0.005 @40000 with market 84237.6 -> limit_not_marketable (limit and market price in data); market SELL with price=200000 no longer fills at the invented price (insufficient_funds: nothing held); wallet unchanged at 10000 USDT · evidence: [BE-02-retest.txt](evidence/2026-09-24-01/BE-02-retest.txt)
- Retest 2 (2026-09-24T19:41:01+00:00): **PASS** — Strengthened: with 0.05 BTC held, a market SELL carrying price=10,000,000 fills at the market (84,000); a limit SELL at 10,000,000 is refused limit_not_marketable; the round trip ends at exactly 100,000 USDT (no invented profit). · evidence: [BE-02-retest-2.txt](evidence/2026-09-24-01/BE-02-retest-2.txt)

#### BE-03 — Paper swap_tokens trades at the market rate  [FAIL · high · **VERIFIED**]

- Section: `backend`  |  Journey: trade BTC in paper behind the Risk Guardian
- Steps: deposit 1 ETH; swap ETH->USDC 1 (ETH/USDC 2695); deposit 100 USDC; swap USDC->ETH 100
- Expected: about 2695 USDC for 1 ETH; about 0.037 ETH for 100 USDC (or a refusal when no rate)
- Observed: every paper swap fills at a fixed 1.0: 1 ETH became 1 USDC; 100 USDC became 100 ETH (~270,000 USD of phantom value)
- Evidence: [BE-03.txt](evidence/2026-09-24-01/BE-03.txt)
- Fix: Paper swap_tokens trades at the market rate (FROM/TO, inverse, or through USDT) and is risk-checked; paper_price_required when no rate
  - Root cause: The paper swap used a hard-coded price of 1.0
  - Files: `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_paper_swap_trades_at_the_market_rate
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — 1 ETH -> 2670.24 USDC (ETH/USDC 2670.24); 100 USDC -> 0.03745 ETH (1/2670.24 each): paper swaps trade at the market rate · evidence: [BE-03-retest.txt](evidence/2026-09-24-01/BE-03-retest.txt)

#### BE-08 — An approve_each proposal made by the MCP server can be approved from the API server / dashboard (UAT.md T5)  [FAIL · high · **VERIFIED**]

- Section: `backend`  |  Journey: As an operator running approve_each, I see each proposal on the dashboard and approve or reject it so that nothing executes without me
- Steps: process A (MCP) proposes; process B (API) lists and confirms with the token; process C confirms again - same EXECUTION_DB_PATH and EXECUTION_SESSION_ID
- Expected: B sees and confirms it; C is refused (single use)
- Observed: B sees nothing and gets 'Unknown request_id' even with the right token: every process has a random session id, so the dashboard approval flow cannot work in any documented deployment (a documented known limitation and an open graduation gate in UAT.md)
- Evidence: [BE-08.txt](evidence/2026-09-24-01/BE-08.txt)
- Fix: ExecutionStore takes EXECUTION_SESSION_ID; with persistence the database is the source of truth (list/confirm/cancel read it; confirm and cancel are conditional UPDATEs); proposals record paper_mode and /api/approve-trade answers 409 EXEC_313 in the other mode
  - Root cause: A random per-process session id made every proposal invisible to any other process
  - Files: `execution_store.py`, `api_server.py`, `errors.py`, `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_proposals_cross_processes_that_share_a_session
- Retest 1 (2026-09-24T17:48:36+00:00): **PASS** — process B (API) lists the MCP process's proposal and confirms it with the token; process C (a second API worker) is refused: already_confirmed (single use across processes) · evidence: [BE-08-retest.txt](evidence/2026-09-24-01/BE-08-retest.txt)
- Retest 2 (2026-09-24T19:41:01+00:00): **PASS** — Strengthened: a proposal made in one process is listed by the real uvicorn API server (auth on, shared EXECUTION_DB_PATH/SESSION_ID), approved with the admin JWT (paper fill at the live market price), and a second approval is refused EXEC_308. · evidence: [BE-08-retest-2.txt](evidence/2026-09-24-01/BE-08-retest-2.txt)

#### CF-01 — Server started by an MCP client (README configs: absolute python + server.py, client's working directory) keeps its data in the repo  [FAIL · high · **VERIFIED**]

- Section: `config`
- Steps: launch server.py from the base commit with the README env block, cwd = an empty folder, then cwd = an unwritable folder (as '/' is for Claude Desktop on macOS)
- Expected: starts; data/*.db under the repo (shared with the API server and dashboard)
- Observed: empty cwd: paper.db, insights.db, strategies.db created in the client's folder (the dashboard never sees that account); unwritable cwd: the server dies at startup (FileNotFoundError: 'data') and the client sees 'Connection closed'. All six DB defaults are cwd-relative 'data/...'
- Evidence: [CF-01.txt](evidence/2026-09-24-01/CF-01.txt)
- Fix: storage_paths.data_path anchors every default data file to <repo>/data (READYTRADER_DATA_DIR overrides; *_PATH still wins)
  - Root cause: Six defaults were cwd-relative 'data/...'
  - Files: `storage_paths.py`, `paper_engine.py`, `execution_store.py`, `idempotency_store.py`, `observability/audit.py`, `intelligence/insights.py`, `strategy/marketplace.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_server_started_from_another_folder_keeps_its_data_out_of_it
- Retest 1 (2026-09-24T17:48:36+00:00): **PASS** — from an empty client folder nothing is written there (data goes to <repo>/data); from an unwritable folder the server starts and lists 29 tools · evidence: [CF-01-retest.txt](evidence/2026-09-24-01/CF-01-retest.txt)

#### DATA-01 — Paper risk metrics: drawdown is the current fall from the peak; resting orders keep their reserved value  [FAIL · high · **VERIFIED**]

- Section: `data`
- Steps: engine: (a) deposit 10000, rest a 2000 limit buy; (b) lose 12%, then recover to a new high (10100) and ask the Risk Guardian about a 100 USDT buy
- Expected: (a) equity 10000, drawdown 0; (b) drawdown 0 after recovery, BUY allowed
- Observed: (a) equity 8000, daily -20%, drawdown 20% (reserved funds vanish, tripping both limits); (b) drawdown stays 12% at a new high and every BUY is refused forever (historical max reported as current)
- Evidence: [DATA-01.txt](evidence/2026-09-24-01/DATA-01.txt)
- Fix: get_risk_metrics reports the current drawdown (max_drawdown_pct keeps the record); portfolio value counts funds reserved by resting orders
  - Root cause: drawdown_pct was the historical maximum; reserved funds were excluded from equity
  - Files: `paper_engine.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_drawdown_is_current_and_recovers
- Retest 1 (2026-09-24T17:48:07+00:00): **PASS** — (a) resting 2000 buy: equity 10000, drawdown 0; (b) 12% loss then a new high: drawdown_pct 0.0, max_drawdown_pct 0.12, and the small BUY is allowed · evidence: [DATA-01-retest.txt](evidence/2026-09-24-01/DATA-01-retest.txt)

#### DOCK-02 — The image carries no local secrets or local data  [FAIL · high · **VERIFIED**]

- Section: `config`
- Steps: a checkout with a gitignored .env.live (canary value) and data/*.db, built as the README says; list /app inside the image
- Expected: no .env* files and no data/*.db in the image
- Observed: /app/.env.live (the canary) and /app/data/{insights,paper,strategies}.db are in the image: .dockerignore excludes only '.env', so a live-credentials file and a developer's databases are baked into image layers (and COPY . . also carries .git/.venv/node_modules in its layer before the later rm)
- Evidence: [DOCK-01.txt](evidence/2026-09-24-01/DOCK-01.txt)
- Fix: See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID
  - Root cause: The Dockerfile's default stage, ignore file and compose defaults predated the fail-closed rules
  - Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `README.md`
  - Commit: `cd6076b`
- Retest 1 (2026-09-24T18:23:36+00:00): **PASS** — built from a working clone that has .env.live (canary), data/*.db, .venv, .git and uat/: none of them is in /app (/app/data is empty; 2.3M of app code) · evidence: [DOCK-01-retest.txt](evidence/2026-09-24-01/DOCK-01-retest.txt)
- Retest 2 (2026-09-24T19:41:01+00:00): **PASS** — Strengthened: image built from the branch with canaries at the root and in subfolders (deploy/.env.live, configs/signer.pem, configs/tls.key, app/keystore-main.json) plus the local data/paper.db: none is in the image (0 canary files). · evidence: [DOCK-02-retest.txt](evidence/2026-09-24-01/DOCK-02-retest.txt)

#### DOCK-04 — docker-compose up -d (compose header) starts the API and MCP services with the shipped defaults  [FAIL · high · **VERIFIED**]

- Section: `config`
- Steps: no .env; docker compose up -d api mcp from images of the same checkout
- Expected: both services up; /api/health answers
- Observed: both crash-loop: SIGNER_TYPE defaults to env_private_key with no PRIVATE_KEY (ValueError); with that fixed the API would still refuse DEV_MODE=false + API_AUTH_REQUIRED=false; the header says 'Copy .env.example' (the file is env.example); no EXECUTION_SESSION_ID so the dashboard could not approve the MCP service's proposals
- Evidence: [DOCK-04.txt](evidence/2026-09-24-01/DOCK-04.txt)
- Fix: See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID
  - Root cause: The Dockerfile's default stage, ignore file and compose defaults predated the fail-closed rules
  - Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `README.md`
  - Commit: `cd6076b`
- Retest 1 (2026-09-24T18:23:36+00:00): **PASS** — without API_JWT_SECRET compose stops with a clear message; with the two secrets both services come up healthy, defaults are halted/null signer/auth on/shared session, /api/health answers, the admin logs in with the bcrypt hash, pending approvals need the token. (Found while retesting: an unquoted hash in .env is mangled by compose's $ expansion - the templates now say to single-quote it.) · evidence: [DOCK-04-retest-2.txt](evidence/2026-09-24-01/DOCK-04-retest-2.txt)

#### DOCK-05 — The BTC-live compose stack (docs/OPS_BTC_PRODUCTION.md) lets the dashboard approve the MCP server's proposals  [FAIL · high · **VERIFIED**]

- Section: `config`
- Steps: the ops pack's section 3 literally: cp env.live.btc.example .env.live; docker compose -f docker-compose.live.yml --env-file .env.live config; read both services' approval settings
- Expected: api and mcp share EXECUTION_DB_PATH and EXECUTION_SESSION_ID (approve_each is mandated for live BTC)
- Observed: both run approve_each, but neither sets EXECUTION_SESSION_ID (and the mcp service has no EXECUTION_DB_PATH): every proposal the agent makes is invisible to the dashboard, so the mandated live flow cannot be approved
- Evidence: [DOCK-05.txt](evidence/2026-09-24-01/DOCK-05.txt)
- Fix: Both live services get EXECUTION_DB_PATH=/app/data/execution.db and a required EXECUTION_SESSION_ID; env.live.btc.example sets EXECUTION_SESSION_ID=btc-live-desk-1
  - Root cause: The live stack predated EXECUTION_SESSION_ID
  - Files: `docker-compose.live.yml`, `env.live.btc.example`
  - Commit: `ccaa6c4`
- Retest 1 (2026-09-24T18:25:23+00:00): **PASS** — the ops pack's config check passes and both live services share EXECUTION_DB_PATH=/app/data/execution.db and EXECUTION_SESSION_ID=btc-live-desk-1, approve_each, halted · evidence: [DOCK-05-retest.txt](evidence/2026-09-24-01/DOCK-05-retest.txt)

#### REV-02 — With the kill switch on, open orders can still be listed and cancelled  [FAIL · high · **VERIFIED**]

- Section: `backend`
- Observed: TRADING_HALTED=true refuses cancel_all_cex_orders, cancel_cex_order and list_cex_open_orders (trading_halted); the documented POST /api/emergency-cancel-all (LIVE_TESTING_PROTOCOL.md:352) returns 404.
- Evidence: [REV-02.txt](evidence/2026-09-24-01/REV-02.txt)
- Fix: Reads and cancels pass allowed_while_halted=True; the emergency procedure is restart halted, cancel_all_cex_orders, revert to paper
  - Root cause: _require_live_allowed refused every live call while halted, including cancels; the doc named an endpoint that was never built
  - Files: `app/tools/execution.py`, `docs/LIVE_TESTING_PROTOCOL.md`, `RUNBOOK.md`, `docs/TOOLS.md`
  - Commit: `011fa78,6ef8957`
  - Regression test: tests/test_uat_2026_09_24.py::test_kill_switch_stops_new_orders_but_not_cancels_or_reads
- Retest 1 (2026-09-24T19:36:35+00:00): **PASS** — With TRADING_HALTED=true, cancel_all_cex_orders, cancel_cex_order and list_cex_open_orders reach the (recording) exchange; LIVE_TESTING_PROTOCOL 4.5 and RUNBOOK now give the restart-halted + cancel_all_cex_orders procedure (the 404 route is no longer documented). · evidence: [REV-02-retest.txt](evidence/2026-09-24-01/REV-02-retest.txt)

#### REV2-01 — A contract symbol cannot be traded as spot to dodge the position check  [FAIL · high · **VERIFIED**]

- Section: `backend`
- Observed: Live, market_type=spot: SELL 0.5 BTC/USDT:USDT is sized as an exit of the 0.5 BTC spot balance (exposure 0) and four in a row are sent; ccxt routes a contract symbol to the USD-M futures endpoint (fapiPrivatePostOrder) whatever market_type says, so each opens a 0.5 BTC short.
- Evidence: [REV2-01.txt](evidence/2026-09-24-01/REV2-01.txt)
- Fix: Contract symbols never read a spot position; _order_args refuses a contract symbol with market_type=spot
  - Root cause: split_symbol dropped the :SETTLE suffix and _account_state read the spot balance whenever market_type=spot
  - Files: `app/tools/trading.py`, `app/tools/execution.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_contract_symbol_is_never_a_spot_exit
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — Contract symbol with market_type=spot: pre_trade_check position_units None (no spot exit); four place_cex_order SELLs refused, 0 orders sent (invalid_symbol: pass market_type swap/future). · evidence: [REV2-01-retest.txt](evidence/2026-09-24-01/REV2-01-retest.txt)

#### BE-06 — A refused live order says why (kill switch, allowlist, size limit)  [FAIL · medium · **VERIFIED**]

- Section: `backend`
- Steps: live, TRADING_HALTED=true, then false with ALLOW_CEX_SYMBOLS=ETH/USDT, MAX_CEX_ORDER_AMOUNT=0.1 (recording exchange client), run in a checkout of the base commit
- Expected: distinct codes: trading_halted, symbol_not_allowed, order_amount_too_large, with the rule in data
- Observed: all three answer cex_error 'Exchange operation failed.' - the reason exists only in the server log (docs/ERRORS.md documents this as a limitation); an agent cannot tell the kill switch from an exchange outage. (BE-06.txt shows the same from the working tree before the error-mapping change; BE-06-2.txt is the base commit.)
- Evidence: [BE-06-2.txt](evidence/2026-09-24-01/BE-06-2.txt), [BE-06.txt](evidence/2026-09-24-01/BE-06.txt)
- Fix: Live gates raise LiveGateRefused(code) and policy refusals keep their PolicyError code/message/data; only unexpected exceptions become cex_error
  - Root cause: _json_internal_error mapped every exception, including the operator's own switches, to a fixed 'Exchange operation failed.'
  - Files: `app/tools/execution.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_live_refusals_name_the_rule
- Retest 1 (2026-09-24T17:47:43+00:00): **PASS** — trading_halted, symbol_not_allowed (allow_cex_symbols in data), order_amount_too_large (max_cex_order_amount in data); the allowed order still goes through · evidence: [BE-06-retest.txt](evidence/2026-09-24-01/BE-06-retest.txt)

#### BE-09 — approve_each proposes only an order the live policy allows  [FAIL · medium · **VERIFIED**]

- Section: `backend`
- Steps: live, approve_each, ALLOW_CEX_SYMBOLS=BTC/USDT, MAX_CEX_ORDER_AMOUNT=0.01: place_cex_order DOGE/USDT; place_cex_order BTC/USDT 5.0
- Expected: symbol_not_allowed / order_amount_too_large; no proposal
- Observed: both return a proposal (2 pending): the policy ran only after proposing, so the operator is asked to approve orders that are refused when they execute
- Evidence: [BE-09.txt](evidence/2026-09-24-01/BE-09.txt)
- Fix: Policy (validate_cex_order / validate_swap / validate_transfer_native), then the Risk Guardian, run before _maybe_propose and again when the approved call executes
  - Root cause: The policy check sat after the proposal step
  - Files: `app/tools/execution.py`
  - Commit: `84507d2`
  - Regression test: tests/test_uat_2026_09_24.py::test_a_proposal_is_made_only_for_an_order_the_policy_allows
- Retest 1 (2026-09-24T17:47:44+00:00): **PASS** — symbol_not_allowed and order_amount_too_large before any proposal; 0 pending proposals · evidence: [BE-09-retest.txt](evidence/2026-09-24-01/BE-09-retest.txt)

#### CLI-01 — tools/setup_wizard.py (docs/ERRORS.md: 'Run python tools/setup_wizard.py') guides a new paper user correctly  [FAIL · medium · **VERIFIED**]

- Section: `cli`
- Steps: fresh copy, no .env: answer n; answer y then read the key report; stdin closed
- Expected: paper needs no keys; nothing tells a user to put a raw private key in .env; a closed stdin does not crash
- Observed: with the env.example .env it marks PRIVATE_KEY as a MISSING critical key (red) - SIGNER_TYPE=env_private_key is dev-only and forbidden for live, so this steers users to paste a raw key; optional CRYPTOPANIC_API_KEY is also red 'MISSING'; with stdin closed it dies with EOFError (exit 1)
- Evidence: [CLI-01.txt](evidence/2026-09-24-01/CLI-01.txt)
- Fix: ask() treats a closed stdin as no; the key report shows SIGNER_TYPE (env_private_key called out as dev-only), needs no exchange key in paper mode, lists feed keys as optional; a 451 from Binance explains MARKETDATA_EXCHANGES
  - Root cause: The key list predated the signer policy and treated optional keys as critical; input() without EOF handling
  - Files: `tools/setup_wizard.py`, `tests/test_setup_wizard.py`
  - Commit: `46b42fb`
  - Regression test: tests/test_setup_wizard.py
- Retest 1 (2026-09-24T18:00:47+00:00): **PASS** — answering n explains paper needs no .env; the key report no longer calls anything MISSING in paper mode (feed keys optional, no exchange key needed) and calls out the env_private_key signer the old env.example set (CF-03 then changed that default); stdin closed exits 0; a Binance 451 is explained · evidence: [CLI-01-retest-2.txt](evidence/2026-09-24-01/CLI-01-retest-2.txt)

#### DATA-02 — Asset codes are case-insensitive in the paper ledger  [FAIL · medium · **VERIFIED**]

- Section: `data`
- Steps: deposit 'usdt' 1000; buy BTC/USDT; buy btc/usdt; get_cex_balance
- Expected: one USDT balance; both spellings trade against it
- Observed: the deposit lands in a separate lower-case 'usdt' balance: BTC/USDT is refused 'Have 0.0 USDT'; btc/usdt fills and creates a separate 'btc' balance; the wallet shows {btc, usdt} beside any upper-case holdings
- Evidence: [DATA-02.txt](evidence/2026-09-24-01/DATA-02.txt)
- Fix: The paper ledger upper-cases asset codes (orders, deposits, lookups)
  - Root cause: Balances were keyed by the caller's spelling
  - Files: `paper_engine.py`, `app/tools/trading.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_asset_codes_are_case_insensitive
- Retest 1 (2026-09-24T17:48:07+00:00): **PASS** — 'usdt' deposit lands in USDT; BTC/USDT and btc/usdt both fill against it into one BTC balance (0.001); wallet {BTC, USDT} · evidence: [DATA-02-retest.txt](evidence/2026-09-24-01/DATA-02-retest.txt)

#### DOC-03 — README configuration defaults match the code  [FAIL · medium · **VERIFIED**]

- Section: `docs`
- Steps: README config table vs Settings() with an empty environment
- Expected: TRADING_HALTED default true (fail closed)
- Observed: README says TRADING_HALTED defaults to false; the code defaults to true (the README's own Status section says true) - an operator reading the table believes live trading is not halted by default
- Evidence: [DOC-02.txt](evidence/2026-09-24-01/DOC-02.txt)
- Fix: README corrected (see commit)
  - Root cause: README drifted from the code
  - Files: `README.md`
  - Commit: `e152134`
- Retest 1 (2026-09-24T17:49:40+00:00): **PASS** — README table says TRADING_HALTED defaults to true, as Settings() does; the safeguards table's Kill Switch row is TRADING_HALTED · evidence: [DOC-02-retest.txt](evidence/2026-09-24-01/DOC-02-retest.txt)

#### DOC-04 — README feature list describes what ships  [FAIL · medium · **VERIFIED**]

- Section: `docs`
- Steps: each README feature claim checked against the code
- Expected: every claimed feature reachable by the agent or the dashboard
- Observed: 'Deep DeFi Integration: direct support for Aave V3 / Uniswap V3' - nothing imports defi/; 'Strategy Marketplace for saving and sharing' - no tool saves a strategy (read-only list at /api/strategies); 'Mobile Guard: push notifications' - the dashboard has no push; get_financial_news listed as 'simulated' (it is NewsAPI); 'Kill Switch = 10% max drawdown' (the kill switch is TRADING_HALTED)
- Evidence: [DOC-02.txt](evidence/2026-09-24-01/DOC-02.txt)
- Fix: README corrected (see commit)
  - Root cause: README drifted from the code
  - Files: `README.md`
  - Commit: `e152134`
- Retest 1 (2026-09-24T17:49:40+00:00): **PASS** — the feature grep no longer finds Deep DeFi / Strategy Marketplace / Mobile Guard / simulated news; the feature list says what ships (defi/ is a library not exposed as tools; no push notifications; strategy research = backtest + stress lab). (The defi import scan also walked this clone's .venv - noise, not repo code.) · evidence: [DOC-02-retest.txt](evidence/2026-09-24-01/DOC-02-retest.txt)

#### DOCK-03 — Containers keep the fail-closed kill-switch default  [FAIL · medium · **VERIFIED**]

- Section: `config`
- Steps: image ENV and docker-compose.yml effective config
- Expected: TRADING_HALTED=true unless the operator sets false (the code default and the AGENTS.md rule)
- Observed: Dockerfile sets ENV TRADING_HALTED=false and docker-compose.yml defaults both services to ${TRADING_HALTED:-false}
- Evidence: [DOCK-04.txt](evidence/2026-09-24-01/DOCK-04.txt)
- Fix: See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID
  - Root cause: The Dockerfile's default stage, ignore file and compose defaults predated the fail-closed rules
  - Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `README.md`
  - Commit: `cd6076b`
- Retest 1 (2026-09-24T18:23:36+00:00): **PASS** — image env TRADING_HALTED=true (and compose defaults true: DOCK-04 retest) · evidence: [DOCK-01-retest.txt](evidence/2026-09-24-01/DOCK-01-retest.txt)

#### FE-01 — Documented dashboard e2e command (UAT.md T6) runs on a fresh clone  [FAIL · medium · **VERIFIED**]

- Section: `frontend`
- Steps: cd frontend && npm ci && env -u NODE_ENV npm run e2e
- Expected: Playwright starts the API harness and runs the suite
- Observed: webServer fails: /home/claude/work/venv-rt/bin/python3 not found (playwright.config.ts defaults to the original author's sandbox paths, report dir too)
- Evidence: [FE-01.txt](evidence/2026-09-24-01/FE-01.txt)
- Fix: e2e/constants.ts HARNESS_PYTHON (repo .venv, else python3, PW_PYTHON_PATH overrides) is used by playwright.config.ts and apiControl.ts; report in frontend/playwright-report; ESLint ignores playwright-report/ and test-results/
  - Root cause: Two copies of a machine-specific default; the first retest caught the second copy
  - Files: `frontend/e2e/constants.ts`, `frontend/e2e/apiControl.ts`, `frontend/playwright.config.ts`, `frontend/eslint.config.mjs`
  - Commit: `ce047ec`
- Retest 1 (2026-09-24T17:50:58+00:00): **FAIL** — 17 passed, 1 failed: the resilience spec restarts the harness through e2e/apiControl.ts, which has its own copy of the old default (/home/claude/work/venv-rt/bin/python3): spawn ENOENT · evidence: [FE-01-retest.txt](evidence/2026-09-24-01/FE-01-retest.txt)
- Retest 2 (2026-09-24T17:55:15+00:00): **PASS** — the documented command with PW_PYTHON_PATH unset: 18 passed (55.8s), E2E_EXIT=0; npm run lint afterwards is clean (LINT_EXIT=0) · evidence: [FE-01-retest-2.txt](evidence/2026-09-24-01/FE-01-retest-2.txt)

#### INT-01 — A news/sentiment source that cannot answer is an error, not a result  [FAIL · medium · **VERIFIED**]

- Section: `integrations`
- Steps: zero-key install: get_financial_news, get_news, get_social_sentiment, get_free_news over stdio
- Expected: not_configured (or source_unavailable) errors naming the missing key; real headlines where a source answers
- Observed: get_financial_news, get_news and get_social_sentiment all answer ok:true with 'Unavailable ... not configured' text as the payload (an agent reads it as data); get_financial_news is described as 'simulated high-tier financial news (Bloomberg/Reuters)' but calls NewsAPI; get_free_news works (Cointelegraph headlines)
- Evidence: [INT-01.txt](evidence/2026-09-24-01/INT-01.txt)
- Fix: News and sentiment sources raise intelligence.SourceError; get_financial_news, get_news, get_social_sentiment, get_free_news and get_sentiment return not_configured / source_unavailable
  - Root cause: The source functions returned their failures as text and the tools wrapped it in ok:true
  - Files: `intelligence/core.py`, `app/tools/research.py`, `app/tools/market_data.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_unconfigured_sources_are_errors
- Retest 1 (2026-09-24T17:48:36+00:00): **PASS** — get_financial_news, get_news and get_social_sentiment answer not_configured naming the missing key; get_free_news still returns Cointelegraph headlines · evidence: [INT-01-retest.txt](evidence/2026-09-24-01/INT-01-retest.txt)

#### REV-03 — The paper drawdown halt reads current equity and a deposit does not clear it  [FAIL · medium · **VERIFIED**]

- Section: `data`
- Observed: After BTC halves, the first BUY is allowed (metrics are the last snapshot); after a 5,000 USDT deposit drawdown_pct reads 0.0 and BUYs pass again.
- Evidence: [REV-03.txt](evidence/2026-09-24-01/REV-03.txt)
- Fix: Snapshots record net deposits (valued when made); drawdown/daily loss read results net of deposits against the equity at the peak, with the current marked value appended; the Guardian marks prices before reading metrics
  - Root cause: drawdown measured raw equity (deposits counted as gains) and only up to the last snapshot
  - Files: `paper_engine.py`, `app/tools/trading.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_a_deposit_does_not_end_a_drawdown_halt
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — After BTC halves the first BUY is refused (Max Drawdown 47.2%); after a 5,000 USDT deposit drawdown stays 47.25% and the BUY is still refused. · evidence: [REV-03-retest.txt](evidence/2026-09-24-01/REV-03-retest.txt)

#### REV-04 — A SELL on a crypto-quoted pair sizes the asset it acquires  [FAIL · medium · **VERIFIED**]

- Section: `backend`
- Observed: SELL 40 ETH on ETH/BTC is treated as an exit (exposure 0) and fills; the account then holds 1.19 BTC = 50% of equity against a 5% cap.
- Evidence: [REV-04.txt](evidence/2026-09-24-01/REV-04.txt)
- Fix: A SELL into a non-cash quote sizes the acquired quote (CASH_QUOTES = USD stables + major fiat)
  - Root cause: exposure_added looked only at the base asset, so any SELL within holdings was an exit
  - Files: `app/tools/trading.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_selling_into_a_crypto_quote_sizes_what_it_buys
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — SELL 40 ETH/BTC sizes the acquired BTC at 100,000 USD and is refused risk_blocked; no BTC acquired. · evidence: [REV-04-retest.txt](evidence/2026-09-24-01/REV-04-retest.txt)

#### REV-05 — The Docker build context excludes secrets in subfolders  [FAIL · medium · **VERIFIED**]

- Section: `config`
- Observed: The repo .dockerignore patterns (.env*, *.pem, *.key, keystore*.json) match only at the root: deploy/.env.live, secrets/signer.pem, secrets/tls.key and secrets/keystore-main.json were copied into the image.
- Evidence: [REV-05.txt](evidence/2026-09-24-01/REV-05.txt)
- Fix: Secret, key and database patterns are **/-prefixed
  - Root cause: Docker ignore patterns without **/ match only at the context root
  - Files: `.dockerignore`
  - Commit: `e858eb3`
  - Regression test: tests/test_uat_2026_09_24.py::test_nested_secrets_stay_out_of_the_docker_build_context
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — Same canary context: deploy/.env.live, deploy/.env, secrets/signer.pem, secrets/tls.key, secrets/keystore-main.json and the root .env.live are all excluded; only app/ok.py and .dockerignore reach the image. · evidence: [REV-05-retest.txt](evidence/2026-09-24-01/REV-05-retest.txt)

#### REV-06 — Docs say which Risk Guardian rules apply to live orders  [FAIL · medium · **VERIFIED**]

- Section: `docs`
- Observed: Live pre_trade_check reports inactive_rules [daily_loss_limit, max_drawdown]; README:77 and 593 and docs/TOOLS.md:72 and 252-256 say those limits apply in both modes.
- Evidence: [REV-06.txt](evidence/2026-09-24-01/REV-06.txt)
- Fix: Docs say the daily-loss and drawdown limits run on the paper account and are reported as inactive_rules live
  - Root cause: docs written before live accounts were known to lack loss history
  - Files: `README.md`, `docs/TOOLS.md`, `docs/ERRORS.md`, `docs/FALLING_KNIFE.md`, `docs/ARCHITECTURE.md`
  - Commit: `6ef8957`
  - Regression test: tests/test_uat_2026_09_24.py::test_live_order_that_cannot_be_sized_fails_closed
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — Live pre_trade_check still lists inactive_rules [daily_loss_limit, max_drawdown]; README:77/594-595, TOOLS.md:72-75 and ERRORS.md now say those limits run on the paper account and are reported as inactive live. · evidence: [REV-06-retest.txt](evidence/2026-09-24-01/REV-06-retest.txt)

#### REV-07 — The documented Docker MCP config keeps the paper account between sessions  [FAIL · medium · **VERIFIED**]

- Section: `docs`
- Observed: Two client sessions with configs/claude_desktop.mcp-server-config.json args: each deposit of 100 USDT reports balance 100.0; no volume is mounted, so the paper account resets every session.
- Evidence: [REV-07.txt](evidence/2026-09-24-01/REV-07.txt)
- Fix: Configs and README mount readytrader-crypto-data on /app/data
  - Root cause: docker run --rm with no volume discards /app/data at exit
  - Files: `configs/agent_zero.mcp.yaml`, `configs/claude_desktop.mcp-server-config.json`, `README.md`
  - Commit: `e858eb3`
  - Regression test: tests/test_uat_2026_09_24.py::test_docker_mcp_configs_keep_the_paper_account
- Retest 1 (2026-09-24T19:38:40+00:00): **PASS** — Two client sessions with the documented config (now -v readytrader-crypto-data:/app/data), image rebuilt from the branch: the second deposit reports balance 200.0, so the paper account persists. · evidence: [REV-07-retest.txt](evidence/2026-09-24-01/REV-07-retest.txt)

#### REV-17 — docker-compose.sentinel.yml keeps the readytrader service running  [FAIL · medium · **VERIFIED**]

- Section: `config`
- Observed: readytrader has build: . with no target, so it gets the default MCP stage; with no stdin it exits (Exited (0)) while sentinel stays healthy.
- Evidence: [REV-17.txt](evidence/2026-09-24-01/REV-17.txt)
- Fix: readytrader builds target api with the API's required settings
  - Root cause: the Dockerfile's default stage changed to MCP; the sentinel stack relied on the old default
  - Files: `docker-compose.sentinel.yml`
  - Commit: `e858eb3`
  - Regression test: tests/test_uat_2026_09_24.py::test_sentinel_stack_runs_the_api_server
- Retest 1 (2026-09-24T19:38:40+00:00): **PASS** — docker-compose.sentinel.yml up: readytrader builds target api and stays Up (healthy) next to sentinel; GET /api/health from inside the stack returns status ok, trading_halted true. · evidence: [REV-17-retest.txt](evidence/2026-09-24-01/REV-17-retest.txt)

#### REV2-02 — The daily-loss rule measures today's loss  [FAIL · medium · **VERIFIED**]

- Section: `data`
- Observed: The last snapshot a week old and BTC 6% lower since, no move today: daily_pnl_pct -5.9% on 09-24, 09-25 and 09-26 and every BUY is refused 'Daily Loss Limit Hit'; the baseline is the last snapshot before today however old.
- Evidence: [REV2-02.txt](evidence/2026-09-24-01/REV2-02.txt)
- Fix: Baseline = previous UTC day's last snapshot, else the day-open mark (mark_day_open at the first risk check)
  - Root cause: the daily baseline was the last snapshot before today, however old
  - Files: `paper_engine.py`, `app/tools/trading.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_daily_loss_is_measured_from_the_start_of_the_day
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — Same week-old snapshot and -6% drift: daily_pnl_pct 0.0 on 09-24/25/26 and the 0.3% BUY passes each day (the drawdown still reads 5.9%). · evidence: [REV2-02-retest.txt](evidence/2026-09-24-01/REV2-02-retest.txt)

#### REV2-03 — Loss limits measure losses against the capital now in the account  [FAIL · medium · **VERIFIED**]

- Section: `data`
- Observed: 1,000 USDT account, 0.2% dip, then a 100,000 top-up and a 101 USD loss (0.1% of equity): same day 'Daily Loss Limit Hit (-10.1%)'; next day 'Max Drawdown Limit Hit (10.1%)' - both divide by the equity at the peak or start of day, before the top-up.
- Evidence: [REV2-03.txt](evidence/2026-09-24-01/REV2-03.txt)
- Fix: Time-weighted performance index: each period's return excludes deposits; drawdown and daily loss read the index
  - Root cause: drawdown divided by equity at the peak and daily loss by equity at day start, ignoring later deposits
  - Files: `paper_engine.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_loss_limits_measure_against_the_capital_in_the_account_now
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — Same top-up scenario: daily -0.1% and drawdown 0.1% (same day and next day); the small BUY passes. · evidence: [REV2-03-retest.txt](evidence/2026-09-24-01/REV2-03-retest.txt)

#### AR-01 — Every numeric tool parameter refuses true  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Expected: true/false for a numeric MCP parameter is refused, not converted to 1/0.
- Observed: At 4a03c09 all 18 numeric MCP parameters accepted true as 1: deposit_paper_funds deposited 1 USD, validate_trade_risk judged 1 USD, post_market_insight stored confidence 1.0, place_cex_order/swap_tokens took amount 1.
- Evidence: [AR-01.txt](evidence/2026-09-24-01/AR-01.txt)
- Fix: Every numeric tool parameter is typed Number or Integer (a validator refuses booleans first).
  - Root cause: pydantic's lax mode converts bool to float/int before the tools' own checks run.
  - Files: `app/tools/params.py`, `app/tools/execution.py`, `app/tools/trading.py`, `app/tools/market_data.py`, `app/tools/research.py`, `tests/test_tool_docs.py`
  - Commit: `fdbdcd4`
  - Regression test: tests/test_uat_2026_09_24.py::test_every_numeric_tool_parameter_refuses_true
- Retest 1 (2026-09-25T12:16:39+00:00): **PASS** — All 18 numeric MCP parameters refuse true ('a number is required, not true/false'). · evidence: [AR-01-retest.txt](evidence/2026-09-24-01/AR-01-retest.txt)

#### AR-02 — The API's own 429 and 500 answers carry CORS headers  [FAIL · low · **VERIFIED**]

- Section: `frontend`
- Expected: Every answer the dashboard's browser gets carries Access-Control-Allow-Origin for its origin.
- Observed: CORSMiddleware was innermost: 200s carried the header, but the rate-limit 429 and the JSON 500 (written by the outer http middlewares) had none, so the dashboard saw a network error instead.
- Evidence: [AR-02.txt](evidence/2026-09-24-01/AR-02.txt)
- Fix: CORS is added after them and wraps every answer.
  - Root cause: CORSMiddleware was added before the @app.middleware functions, so it sat inside them.
  - Files: `api_server.py`
  - Commit: `fdbdcd4`
  - Regression test: tests/test_uat_2026_09_24.py::test_the_outer_middlewares_answers_carry_cors_headers
- Retest 1 (2026-09-25T12:16:39+00:00): **PASS** — CORS is outermost: the 429s and the JSON 500 carry Access-Control-Allow-Origin for http://localhost:3000. · evidence: [AR-02-retest.txt](evidence/2026-09-24-01/AR-02-retest.txt)

#### AR-03 — The docs say how the daily-loss baseline is taken  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Expected: docs/TOOLS.md describes the daily baseline as the code computes it.
- Observed: TOOLS.md:72 and ARCHITECTURE.md say '5% daily loss' / '5% loss today' without the baseline (the previous UTC day's last recorded value, else today's first), so a late move a day never recorded counts toward the next day too.
- Evidence: [AR-03.txt](evidence/2026-09-24-01/AR-03.txt)
- Fix: TOOLS.md gives the baseline and that it errs toward halting.
  - Root cause: The docs described the rule, not its baseline.
  - Files: `docs/TOOLS.md`
  - Commit: `fdbdcd4`
  - Regression test: evidence only (docs)
- Retest 1 (2026-09-25T12:16:39+00:00): **PASS** — TOOLS.md:72-76 gives the daily baseline (the previous UTC day's last recorded value, else today's first) and that a late move errs toward halting. · evidence: [AR-03-retest.txt](evidence/2026-09-24-01/AR-03-retest.txt)

#### BE-07 — API server log lines carry the time of the event  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Steps: run the dashboard e2e suite (FE-02) and read the API server's JSON log lines
- Expected: each event has its own ts_ms
- Observed: all 23 events over the 54 s run carry the same ts_ms (the API context is built once at import and log_event copies its ts_ms), so the log cannot order or time an incident
- Evidence: [BE-07.txt](evidence/2026-09-24-01/BE-07.txt)
- Fix: log_event stamps ts_ms at emit time
  - Root cause: The API's log context is built once at import and log_event copied its ts_ms
  - Files: `observability/logging.py`
  - Commit: `9e25268`
  - Regression test: tests/test_uat_2026_09_24.py::test_log_lines_carry_the_time_of_the_event
- Retest 1 (2026-09-24T17:55:15+00:00): **PASS** — two logins 1.5 s apart through the real API app: auth_success events at ts_ms 1790272506413 and 1790272507921 (1508 ms apart) · evidence: [BE-07-retest.txt](evidence/2026-09-24-01/BE-07-retest.txt)

#### CF-02 — Every variable the code reads is in env.example  [FAIL · low · **VERIFIED**]

- Section: `config`
- Steps: scan os.getenv/os.environ names in the Python sources vs env.example
- Expected: all present (CEX_<EXCHANGE>_* are built dynamically; proxies are OS-level)
- Observed: missing: ONEINCH_API_KEY (needed for any live swap), LOG_LEVEL, CEX_MARKET_TYPE, CEX_RETRY_*, COINBASE_WS_PRODUCTS, DISALLOW_SIGN_CONTRACT_CREATION, DEPLOYMENT_ENV, OTEL_*, PORTFOLIO_CHAINS/EXCHANGES, SENTINEL_AUTH_TOKEN, STORE_BACKEND/REDIS_URL/DATABASE_URL, READYTRADER_*_DB_PATH aliases
- Evidence: [CF-02.txt](evidence/2026-09-24-01/CF-02.txt)
- Fix: env.example lists ONEINCH_API_KEY, LOG_LEVEL, CEX_* tuning, signing, OTEL, stores, EXECUTION_SESSION_ID, READYTRADER_DATA_DIR
  - Root cause: Variables added to code without env.example
  - Files: `env.example`
  - Commit: `9e25268`
- Retest 1 (2026-09-24T17:48:36+00:00): **PASS** — only the READYTRADER_*_DB_PATH aliases (documented as a prefix rule in env.example) and OS proxy variables remain; CEX_<EXCHANGE>_* are built dynamically · evidence: [CF-02-retest.txt](evidence/2026-09-24-01/CF-02-retest.txt)

#### CF-03 — env.example's signer is safe to start from  [FAIL · low · **VERIFIED**]

- Section: `config`
- Steps: read env.example's signer section; source it and make the README's live-but-halted switch
- Expected: SIGNER_TYPE=null (the README quickstart value); env_private_key described as development only
- Observed: env.example sets SIGNER_TYPE=env_private_key under a header saying the signer is 'required only for PAPER_MODE=false', yet env_private_key is refused whenever PAPER_MODE=false (SettingsValidationError); the template's own default is the one the project forbids for live
- Evidence: [CF-03.txt](evidence/2026-09-24-01/CF-03.txt)
- Fix: env.example: SIGNER_TYPE=null with the live signers listed and env_private_key described as development-only
  - Root cause: The template predated the env_private_key ban
  - Files: `env.example`, `tests/test_uat_2026_09_24.py`
  - Commit: `d9a23b2`
  - Regression test: tests/test_uat_2026_09_24.py::test_env_example_starts_from_a_signer_the_live_profile_accepts
- Retest 1 (2026-09-24T18:00:47+00:00): **PASS** — env.example now sets SIGNER_TYPE=null; with the live-but-halted switches the settings load (only the expected allowlist warning), no env_private_key refusal · evidence: [CF-03-retest.txt](evidence/2026-09-24-01/CF-03-retest.txt)

#### DOC-01 — docs/TOOLS.md is what the README says: generated from the live registry  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Steps: README:474 - run python tools/generate_tool_docs.py
- Expected: no diff (the committed catalog is the generator's output)
- Observed: the documented command rewrites docs/TOOLS.md: 783 lines deleted - the per-tool usage, parameters, examples and error codes are not in the code docstrings (the file was curated by hand after generation); 'make docs' would erase them
- Evidence: [DOC-01.txt](evidence/2026-09-24-01/DOC-01.txt)
- Fix: docs/TOOLS.md corrected tool by tool against the code (curated, roster-tested); generate_tool_docs.py prints the registry and refuses to overwrite TOOLS.md
  - Root cause: The catalog was hand-edited after generation and drifted (simulated data, fields that do not exist)
  - Files: `docs/TOOLS.md`, `tools/generate_tool_docs.py`, `Makefile`, `docs/SCORECARD.md`
  - Commit: `9e25268,e152134`
- Retest 1 (2026-09-24T17:49:30+00:00): **PASS** — the README's command prints the live registry and leaves docs/TOOLS.md untouched (git status empty); --write docs/TOOLS.md is refused; roster test 4 passed; the fabricated fields (simulated data, analyst_commentary, price_targets, Bitcoin Magazine) are gone (the one hit is a sentence saying the field does not exist) · evidence: [DOC-01-retest-2.txt](evidence/2026-09-24-01/DOC-01-retest-2.txt)

#### DOC-02 — README prerequisites name what the install needs  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Steps: README Prerequisites vs pyproject
- Expected: Python 3.12+ named (the zero-key quickstart and local dev use a venv)
- Observed: Prerequisites list only Docker; pyproject requires-python >=3.12 and PRE-03 showed a python3 older than 3.12 is the default on some hosts
- Evidence: [DOC-02.txt](evidence/2026-09-24-01/DOC-02.txt)
- Fix: README corrected (see commit)
  - Root cause: README drifted from the code
  - Files: `README.md`
  - Commit: `e152134`
- Retest 1 (2026-09-24T17:49:40+00:00): **PASS** — Prerequisites now name Python 3.12+ (matches pyproject) or Docker · evidence: [DOC-02-retest.txt](evidence/2026-09-24-01/DOC-02-retest.txt)

#### DOC-05 — README Agent Zero UI instructions run the image the README builds  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Steps: README Option A UI args vs the docker build tag
- Expected: same image name
- Observed: UI args end with 'readytrader'; the README builds 'readytrader-crypto' (the agent.yaml block two lines below uses readytrader-crypto) - the UI config fails with 'image not found'
- Evidence: [DOC-02.txt](evidence/2026-09-24-01/DOC-02.txt)
- Fix: README corrected (see commit)
  - Root cause: README drifted from the code
  - Files: `README.md`
  - Commit: `e152134`
- Retest 1 (2026-09-24T17:49:40+00:00): **PASS** — Agent Zero UI args end with readytrader-crypto, the image the README builds · evidence: [DOC-02-retest.txt](evidence/2026-09-24-01/DOC-02-retest.txt)

#### FK-01 — The crypto no-price-rule decision is reproducible as described  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Observed: All three FROZEN files match their SHA-256 and the v2 scoring scripts assert it; the fresh-coin result fails the pre-registered criterion (lift 1.21 < 1.5); the price rule is inactive in code. But research/falling_knife/README.md says the scoring scripts refuse to run if the frozen file changed, and v1's heldout.py has no such check; and the frozen files and scored results were committed together (FOREX 19e21754), so git history cannot show the freeze preceded scoring. The docs do not say so.
- Evidence: [FK-01.txt](evidence/2026-09-24-01/FK-01.txt)
- Fix: README says only the v2 scoring scripts check the hash and that git history cannot show freeze-before-score; FALLING_KNIFE.md says the same
  - Root cause: the README described v2's hash check as universal and did not state the commit ordering
  - Files: `research/falling_knife/README.md`, `docs/FALLING_KNIFE.md`
  - Commit: `5506954`
  - Regression test: none (docs)
- Retest 1 (2026-09-24T19:42:17+00:00): **PASS** — Hashes still match and the result still fails the criterion; the research README now says only the v2 scripts check the hash and that git history does not show freeze-before-score (README:50-57); FALLING_KNIFE.md says the same. · evidence: [FK-01-retest-2.txt](evidence/2026-09-24-01/FK-01-retest-2.txt)
- Retest 2 (2026-09-24T19:42:25+00:00): **PASS** — Hashes still match and the result still fails the criterion; the research README now says only the v2 scripts check the hash (line 40) and that git history does not show freeze-before-score (line 44); FALLING_KNIFE.md:56 says the same. · evidence: [FK-01-retest-2.txt](evidence/2026-09-24-01/FK-01-retest-2.txt)

#### REV-08 — The dashboard labels the current drawdown correctly  [FAIL · low · **VERIFIED**]

- Section: `frontend`
- Observed: PortfolioSummary.tsx:39-40 labels metrics.drawdown_pct (the current fall from the peak) 'Max drawdown'; the API returns max_drawdown_pct separately.
- Evidence: [REV-08.txt](evidence/2026-09-24-01/REV-08.txt)
- Fix: Drawdown from peak + Max drawdown; stablecoin set matches the server
  - Root cause: the label predates the split of drawdown_pct (current) and max_drawdown_pct (record)
  - Files: `frontend/src/components/PortfolioSummary.tsx`, `frontend/src/lib/types.ts`
  - Commit: `2d8f827`
  - Regression test: tests/test_uat_2026_09_24.py::frontend/src/components/PortfolioSummary.test.tsx
- Retest 1 (2026-09-24T19:37:10+00:00): **PASS** — PortfolioSummary shows 'Drawdown from peak' (drawdown_pct) and 'Max drawdown' (max_drawdown_pct); the component test passes (2/2). · evidence: [REV-08-retest.txt](evidence/2026-09-24-01/REV-08-retest.txt)

#### REV-09 — A NaN amount is refused on every order path  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: replace_cex_order(amount=nan) is sent to the exchange (replace_order amount nan); pre_trade_check(amount=nan) answers allowed with exposure nan.
- Evidence: [REV-09.txt](evidence/2026-09-24-01/REV-09.txt)
- Fix: Shared _order_args validation for place and replace; pre_trade_check refuses a non-positive or non-finite amount
  - Root cause: replace_cex_order and pre_trade_check did not validate the amount
  - Files: `app/tools/execution.py`, `app/tools/trading.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_nan_amounts_never_reach_the_exchange_or_a_proposal
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — replace_cex_order(amount=nan) -> invalid_amount with no exchange call; pre_trade_check(amount=nan) -> allowed False. · evidence: [REV-09-retest.txt](evidence/2026-09-24-01/REV-09-retest.txt)

#### REV-10 — transfer_eth refuses a NaN or negative amount before proposing  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: Live approve_each: transfer_eth(nan) and transfer_eth(-3.0) each return ok with a pending proposal.
- Evidence: [REV-10.txt](evidence/2026-09-24-01/REV-10.txt)
- Fix: transfer_eth refuses a non-finite or non-positive amount with invalid_amount before policy or proposal
  - Root cause: transfer_eth proposed before validating the amount
  - Files: `app/tools/execution.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_nan_amounts_never_reach_the_exchange_or_a_proposal
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — transfer_eth(nan) and transfer_eth(-3.0) -> invalid_amount; no pending proposal. · evidence: [REV-10-retest.txt](evidence/2026-09-24-01/REV-10-retest.txt)

#### REV-11 — The paper account values every USD stablecoin the Guardian knows at 1 USD  [FAIL · low · **VERIFIED**]

- Section: `data`
- Observed: 1,000 each of USDT FDUSD TUSD USDP BUSD: paper portfolio value 1000.0 (only USDT counted); paper_engine.py:147/372/444 list 4 stables vs the Guardian's 8.
- Evidence: [REV-11.txt](evidence/2026-09-24-01/REV-11.txt)
- Fix: paper_engine.USD_STABLES is the one list; trading imports it
  - Root cause: two stablecoin lists
  - Files: `paper_engine.py`, `app/tools/trading.py`
  - Commit: `011fa78`
  - Regression test: tests/test_uat_2026_09_24.py::test_every_usd_stablecoin_counts_at_one_dollar_in_the_paper_account
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — 1,000 each of USDT FDUSD TUSD USDP BUSD: paper portfolio value 5000.0. · evidence: [REV-11-retest.txt](evidence/2026-09-24-01/REV-11-retest.txt)

#### REV-12 — get_social_sentiment says when a configured source fails  [FAIL · low · **VERIFIED**]

- Section: `integrations`
- Observed: X configured with a failing token, Reddit unset: ok=true with 'Twitter Error: 401 Unauthorized' in the text.
- Evidence: [REV-12.txt](evidence/2026-09-24-01/REV-12.txt)
- Fix: social_sentiment_report returns each source's state; all configured sources erroring answers source_unavailable
  - Root cause: the tool checked only 'configured', not whether a configured source answered
  - Files: `intelligence/core.py`, `app/tools/research.py`, `docs/TOOLS.md`
  - Commit: `e8290a8`
  - Regression test: tests/test_uat_2026_09_24.py::test_social_sentiment_says_when_every_configured_source_failed
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — Same failing-X setup: get_social_sentiment ok=false code=source_unavailable. · evidence: [REV-12-retest.txt](evidence/2026-09-24-01/REV-12-retest.txt)

#### REV-13 — Login takes the same time for an unknown username as for a wrong password  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: Median 3.5 ms for a wrong username vs 286.6 ms for the right username with a wrong password: username validity is visible by timing.
- Evidence: [REV-13.txt](evidence/2026-09-24-01/REV-13.txt)
- Fix: The password check runs for every username; both must pass
  - Root cause: the username check returned before the bcrypt check
  - Files: `api_server.py`
  - Commit: `e8290a8`
  - Regression test: tests/test_uat_2026_09_24.py::test_login_checks_the_password_whatever_the_username
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — Wrong username 282.0 ms vs wrong password 289.1 ms median: both run the bcrypt check. · evidence: [REV-13-retest.txt](evidence/2026-09-24-01/REV-13-retest.txt)

#### REV-14 — API log lines carry a per-request request_id  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: Two separate login requests log the same request_id; API_CTX is built once at import (api_server.py:48).
- Evidence: [REV-14.txt](evidence/2026-09-24-01/REV-14.txt)
- Fix: request_id_middleware sets a per-request id (per connection on /ws); logs use _ctx(); X-Request-ID header
  - Root cause: API_CTX (with its request_id) was built once at import
  - Files: `api_server.py`
  - Commit: `e8290a8`
  - Regression test: tests/test_uat_2026_09_24.py::test_each_api_request_logs_its_own_request_id
- Retest 1 (2026-09-24T19:36:36+00:00): **PASS** — Two login requests log two distinct request_ids. · evidence: [REV-14-retest.txt](evidence/2026-09-24-01/REV-14-retest.txt)

#### REV-15 — RISK_PROFILE does what the docs say  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Observed: RISK_PROFILE is documented (README:179 'Presets for sizing and safety limits', smithery.yaml, compose, env templates) but only settings.risk_config reads it and nothing uses that; the Guardian limits are fixed.
- Evidence: [REV-15.txt](evidence/2026-09-24-01/REV-15.txt)
- Fix: Documented as reserved and not applied; removed from the smithery config schema and both Hermes samples
  - Root cause: RISK_PROFILE presets were never wired to the Guardian
  - Files: `README.md`, `smithery.yaml`, `docs/HERMES_INTEGRATION.md`
  - Commit: `e858eb3,3b58fa4`
  - Regression test: none (docs)
- Retest 1 (2026-09-24T19:37:10+00:00): **PASS** — RISK_PROFILE appears only in the README row that says it is reserved and not applied; smithery.yaml and the Hermes guide no longer offer it. · evidence: [REV-15-retest-2.txt](evidence/2026-09-24-01/REV-15-retest-2.txt)

#### REV-16 — Hermes guide, smithery manifest and README match the server  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Observed: HERMES_INTEGRATION.md:126-131 says account tools make authenticated calls in paper mode (they now refuse); smithery.yaml advertises DeFi (Aave, Uniswap) and approval of every trade; README:117 says compose runs the dashboard (it needs --profile with-frontend).
- Evidence: [REV-16.txt](evidence/2026-09-24-01/REV-16.txt)
- Fix: Hermes guide, smithery description and README compose line match the server
  - Root cause: docs not updated with the paper-isolation and fill changes
  - Files: `docs/HERMES_INTEGRATION.md`, `smithery.yaml`, `README.md`
  - Commit: `e858eb3`
  - Regression test: tests/test_uat_2026_09_24.py::none (docs)
- Retest 1 (2026-09-24T19:37:10+00:00): **PASS** — Hermes guide: paper orders at the market, account tools answer paper_mode_not_supported; smithery describes 1inch swaps and live-only approve_each; README names --profile with-frontend; no stale Aave/every-trade/authenticated-in-paper claims remain (README:76 says the DeFi helpers are not exposed). · evidence: [REV-16-retest.txt](evidence/2026-09-24-01/REV-16-retest.txt)

#### REV2-04 — Docs say which exits the Guardian treats as exits  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Observed: Live futures: SELL 0.5 BTC (closing) is refused 'Position size too large (20%)' because derivatives positions are unknown; TOOLS.md:262 and ERRORS.md:42 say selling what is held into cash is never refused.
- Evidence: [REV2-04.txt](evidence/2026-09-24-01/REV2-04.txt)
- Fix: Docs say derivatives positions are unknown and closing orders are sized; contract symbols need market_type swap/future
  - Root cause: docs described spot behaviour as universal
  - Files: `docs/TOOLS.md`, `docs/ERRORS.md`
  - Commit: `2f4795e`
  - Regression test: none (docs)
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — TOOLS.md and ERRORS.md now say that on a futures/swap account the position cannot be read, so closing orders are sized (the behaviour the probe still shows). · evidence: [REV2-04-retest.txt](evidence/2026-09-24-01/REV2-04-retest.txt)

#### REV2-05 — A paper deposit cannot end a drawdown halt  [FAIL · low · **VERIFIED**]

- Section: `data`
- Observed: During a 15% drawdown, deposit_paper_funds('ETH', 10) while ETH/USDT has no price is booked at 0 USD; once the price returns the deposit reads as a +220% gain and the BUY passes (drawdown 0.0).
- Evidence: [REV2-05.txt](evidence/2026-09-24-01/REV2-05.txt)
- Fix: deposit_paper_funds refuses a non-stable asset it cannot price (paper_price_required); the engine comment says what direct callers get
  - Root cause: an unpriced deposit was valued at 0 USD
  - Files: `app/tools/trading.py`, `paper_engine.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_a_paper_deposit_that_cannot_be_valued_is_refused
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — deposit_paper_funds('ETH', 10) with no ETH price is refused; the BUY after prices return stays halted (drawdown 15%). · evidence: [REV2-05-retest.txt](evidence/2026-09-24-01/REV2-05-retest.txt)

#### REV2-06 — The Falling Knife rule applies to what an order buys  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: BTC sentiment -0.9: swap_check ETH->BTC is blocked, but place_cex_order SELL 1 ETH/BTC (which buys 0.05 BTC) passes - the rule read ETH's sentiment and applies only to side=buy.
- Evidence: [REV2-06.txt](evidence/2026-09-24-01/REV2-06.txt)
- Fix: On a crypto-quoted SELL the quote's sentiment is checked as a BUY of the quote; risk.sentiment_asset names it
  - Root cause: sentiment was read for the symbol's base and the rule applied only to side=buy
  - Files: `app/tools/trading.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_falling_knife_judges_the_asset_a_crypto_quoted_sell_buys
- Retest 1 (2026-09-24T20:22:43+00:00): **PASS** — With BTC sentiment -0.9, SELL 1 ETH/BTC is refused by the Falling Knife rule like swap ETH->BTC and BUY BTC/USDT; no BTC acquired. · evidence: [REV2-06-retest.txt](evidence/2026-09-24-01/REV2-06-retest.txt)

#### REV2-07 — Paper orders refuse contract symbols; the exchange gets the normalised order  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: Paper SELL 0.01 BTC/USDT:USDT fills into a phantom 'USDT:USDT' balance that equity ignores (500 USD lost); live, side ' SELL ' and order_type 'LIMIT' pass validation but reach the exchange un-normalised.
- Evidence: [REV2-07.txt](evidence/2026-09-24-01/REV2-07.txt)
- Fix: Paper ledger refuses contract symbols; policy, proposal, exchange and summary get the normalised side/order_type
  - Root cause: _validate_order accepted ':' in the quote; the live path passed raw side/order_type
  - Files: `paper_engine.py`, `app/tools/execution.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_paper_refuses_contract_symbols_and_live_sends_normalised_orders
- Retest 1 (2026-09-24T20:22:44+00:00): **PASS** — Paper SELL BTC/USDT:USDT refused invalid_symbol (no phantom balance); live side ' SELL ' / 'LIMIT' reach the exchange as 'sell' / 'limit'. · evidence: [REV2-07-retest.txt](evidence/2026-09-24-01/REV2-07-retest.txt)

#### REV2-08 — An unhandled API error still carries the request id and security headers  [FAIL · low · **VERIFIED**]

- Section: `backend`
- Observed: A route that raises returns 500 with no X-Request-ID, no X-Frame-Options, and no log line carrying a request_id (a 429 does carry both).
- Evidence: [REV2-08.txt](evidence/2026-09-24-01/REV2-08.txt)
- Fix: request_id_middleware catches, logs with the request id, answers JSON SYS_803 with security headers and X-Request-ID
  - Root cause: unhandled exceptions went to Starlette's outer ServerErrorMiddleware, past the app's middlewares
  - Files: `api_server.py`
  - Commit: `839bcb4`
  - Regression test: tests/test_uat_2026_09_24.py::test_an_unhandled_api_error_keeps_its_request_id_and_headers
- Retest 1 (2026-09-24T20:22:44+00:00): **PASS** — A raising route returns 500 with X-Request-ID and X-Frame-Options DENY, and the api_unhandled_error log line carries the same request_id; 429s unchanged. · evidence: [REV2-08-retest.txt](evidence/2026-09-24-01/REV2-08-retest.txt)

#### REV2-09 — Docs give the kill switch's default and how to use it  [FAIL · low · **VERIFIED**]

- Section: `docs`
- Observed: ARCHITECTURE.md:540 lists TRADING_HALTED default false (code: true); CUSTODY.md:157-165 and 222-228 say 'export TRADING_HALTED=true' then check /api/health (a running server reads settings at start-up); README says the kill switch halts all live actions (reads and cancels still work).
- Evidence: [REV2-09.txt](evidence/2026-09-24-01/REV2-09.txt)
- Fix: Default true; halting is a restart with TRADING_HALTED=true; README says reads and cancels still work
  - Root cause: docs predate the fail-closed default and the read/cancel exemption
  - Files: `docs/ARCHITECTURE.md`, `docs/CUSTODY.md`, `docs/LIVE_TESTING_PROTOCOL.md`, `README.md`
  - Commit: `2f4795e`
  - Regression test: none (docs)
- Retest 1 (2026-09-24T20:22:44+00:00): **PASS** — ARCHITECTURE.md:540 default true; CUSTODY.md says restart with TRADING_HALTED=true/false; the testing protocol's emergency stop is a restart; README says reads and cancels still work; no 'halt all live actions' remains. · evidence: [REV2-09-retest.txt](evidence/2026-09-24-01/REV2-09-retest.txt)

#### REV2-10 — smithery.yaml passes its settings to the server  [FAIL · low · **VERIFIED**]

- Section: `config`
- Observed: configSchema sits at the top level and startCommand has no commandFunction, so no setting reaches the process; its PAPER_MODE='false' option stops the server at start-up (SettingsValidationError).
- Evidence: [REV2-10.txt](evidence/2026-09-24-01/REV2-10.txt)
- Fix: startCommand.configSchema lists the optional keys; commandFunction always sets the paper profile and passes the keys
  - Root cause: configSchema outside startCommand and no commandFunction
  - Files: `smithery.yaml`
  - Commit: `2f4795e`
  - Regression test: tests/test_uat_2026_09_24.py::test_smithery_listing_passes_its_settings_and_stays_paper
- Retest 1 (2026-09-24T20:22:44+00:00): **PASS** — smithery.yaml's commandFunction, evaluated with node, returns python app/main.py with PAPER_MODE/TRADING_HALTED/SIGNER_TYPE forced to the paper profile and the given key passed through (PAPER_MODE='false' ignored); the server started with that env lists 29 tools and takes a paper deposit. · evidence: [REV2-10-retest.txt](evidence/2026-09-24-01/REV2-10-retest.txt)

#### INT-03 — Keyed news and social sources (NewsAPI, CryptoPanic, X, Reddit) with real keys  [BLOCKED · **BLOCKED**]

- Section: `integrations`
- Steps: call get_financial_news / get_news / get_social_sentiment with keys set
- Observed: no NEWSAPI_KEY, CRYPTOPANIC_API_KEY, TWITTER_BEARER_TOKEN or REDDIT_CLIENT_ID/SECRET in this environment; without them each tool answers not_configured (INT-01 retest)
- Blocked on: Bill supplies NEWSAPI_KEY, CRYPTOPANIC_API_KEY, TWITTER_BEARER_TOKEN, REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET (optional feeds)
- Evidence: [INT-02.txt](evidence/2026-09-24-01/INT-02.txt)

#### INT-04 — Live exchange account, 1inch swaps and an EVM signer (read-only / sandbox)  [BLOCKED · **BLOCKED**]

- Section: `integrations`
- Steps: get_cex_balance / list_cex_open_orders against an exchange sandbox; swap quote via 1inch; remote signer address
- Observed: no CEX_* keys, ONEINCH_API_KEY, SIGNER_REMOTE_URL / MPC_SIGNER_URL or RPC URLs here; live money paths are out of scope for this UAT (paper/sandbox only; Phase 4 needs Bill's written authorization). Order-path gates were verified against a recording client (BE-04..06, BE-09)
- Blocked on: Bill supplies exchange sandbox/testnet keys (trade+read, no withdraw) and, for DEX, ONEINCH_API_KEY + a testnet RPC and signer; then run tests/integration/test_exchange_sandbox.py and a read-only get_cex_balance
- Evidence: [INT-02.txt](evidence/2026-09-24-01/INT-02.txt)

### Passed checks (21)

| ID | Section | Check | Observed |
|---|---|---|---|
| PRE-01 | preflight | The repo's quality gate (make check / make security) passes | ruff, format, bandit, pip-audit (no known vulnerabilities), verify_docs and mdformat pass; pytest: 635 passed, 9 skipped, 6 failed - all 6 in tests/integration, which call public exchange APIs (see PRE-02) |
| PRE-02 | preflight | Integration tests against the public Kraken/Coinbase APIs pass | As-is 6 fail with CERTIFICATE_VERIFY_FAILED: this sandbox intercepts TLS and ccxt/aiohttp trusts only certifi's bundle (an environment property, not a defect; curl, which trusts the proxy CA, reaches both). With the proxy CA added to the venv's bundle: 75 passed, 5 skipped. Binance answers 451 (geo-block) from here |
| PRE-03 | preflight | README local install (pip install -r requirements-dev.txt; python app/main.py) on a fresh venv | Both install cleanly and python app/main.py starts the 'ReadyTrader-Crypto' stdio server (pyproject says requires-python >=3.12; the README states no version - see the docs section) |
| PRE-04 | preflight | MCP server registers its tools over stdio (python app/main.py) | A real stdio MCP session lists 29 tools (orders, account, streams, market data, news, insights, paper, risk, research, on-chain) |
| PRE-05 | preflight | Documented 10-minute demos run: paper_quick_demo.py and stress_test_demo.py | Both exit 0; quick demo passes its balance checks; stress lab writes its 5 artifacts (risk metrics oddity tracked as DATA-01) |
| PRE-06 | preflight | Dashboard's documented scripts run (npm ci, lint, typecheck, test, build) | On the final branch: npm ci, lint, typecheck exit 0; vitest 61/61 passed (incl. the new PortfolioSummary test); next build compiles and generates the static pages. |
| PRE-07 | preflight | Documented paper BTC harness (AGENTS.md Verification: python examples/paper_btc_uat.py) | 20 paper trades ok, the 50% bet is refused by the Risk Guardian (risk_blocks 1), live execution not allowed by default |
| REG-01 | preflight | Regression sweep on the final branch: every fixed finding's probe again + make check + make security | 18/18 finding probes PASS; make check exit 0 (685 passed, 5 skipped; ruff, format, bandit, pip-audit, verify_docs, mdformat); make security exit 0 |
| REG-03 | preflight | Regression sweep after the review round: every fixed finding's probe again, then the quality gate | 34/34 probe verdicts PASS on the final branch (BE-01..09, BE-12, DATA-01/02, CF-01/03, INT-01, CLI-01, DOC-01, DOCK-05, REV-01..07, 09..14, 17, FK-01); make check exit 0 (ruff, 700 passed / 5 skipped, bandit, pip-audit clean, verify_docs, mdformat - extract in REG-03-2.txt); make security exit 0 (bandit 0 issues, pip-audit and npm audit 0 vulnerabilities). |
| REG-05 | preflight | Final regression sweep after both review rounds: every fixed finding's probe, the dashboard scripts and e2e, then the quality gate | 44/44 verdicts PASS on the final branch (images rebuilt from it): BE-01..09, BE-12, DATA-01/02, CF-01/03, INT-01, CLI-01, DOC-01, DOCK-05, REV-01..07/09..14/17, FK-01, REV2-01..03/05..08/10, dashboard npm ci/lint/typecheck/61 vitest/build, Playwright 18 passed; make check exit 0 (708 passed, 5 skipped; bandit, pip-audit clean, verify_docs, mdformat - REG-05-2.txt); make security exit 0. |
| BE-10 | backend | Research journey and input validation over MCP (candles, regime, backtest, sandbox, Guardian, bad inputs) | numeric candles; regime VOLATILE_TRENDING/UP; RSI backtest pnl +360.45 on 10000; 'import os' refused (error_kind forbidden); a 3% buy allowed with the falling_knife block; bad side invalid_request; Fear & Greed 71; unknown symbol fetch_price_error; amount -1 invalid_amount; order_type stop invalid_order_type |
| BE-11 | backend | Approval/dashboard HTTP API: happy paths, auth, bad bodies, unknown id (real uvicorn server) | 200 mode=paper; 401; 401 without a traceback; 200 {pending}; 422 with no stack trace or file path; 404 EXEC_309; 200; 200; 401 - all nine http_capture expectations passed |
| DATA-03 | data | Paper account and orders survive a server restart; free text round-trips unchanged | process 2 reads BTC 0.004 / USDT 9663.79 (filled at the market 84051.4); the insight text '<b>ETF inflows</b> — ünïcode ✓' comes back byte-for-byte |
| MEM-01 | memory | Shared insight memory: write, recall across a restart, case-insensitive symbol, expiry | after the restart the 1-hour insight is recalled with a lower-case symbol; the 4-second one has expired and is not returned anywhere; another symbol returns [] |
| FE-02 | frontend | Dashboard e2e suite (18 journeys: auth, approvals, smoke, mobile, API-down resilience) against the real API harness | 18 passed (54.4s) with PW_PYTHON_PATH set to the clone's venv; closes UAT.md T6 'not run' |
| REG-02 | frontend | Dashboard e2e suite on the final branch (after the auth and Guardian changes), documented command, no overrides | 18 passed; lint clean afterwards |
| REG-04 | frontend | Dashboard e2e suite on the final branch (after the review-round API and dashboard changes) | The documented Playwright command: 18 passed (auth, approvals, smoke, mobile, API-down); ESLint afterwards exit 0. |
| INT-02 | integrations | Public data sources answer for real (exchange market data, Fear & Greed, RSS) | BTC/USDT 84237.6 from ccxt_rest; Fear & Greed 71 (Greed); Cointelegraph headlines; an unknown symbol is fetch_price_error, not a made-up price |
| CF-04 | config | No credentials in the tree or its history | 0 hits (the scanner's self-test matches a fake AWS key id); test fixtures use obvious dummies (PRIVATE_KEY=0x...01 in tests/conftest.py) |
| REG-06 | regression | The quality gate passes on the final tree | HEAD fdbdcd4: make check exit 0 (ruff, format, 710 passed, bandit, pip-audit, docs checks, mdformat); make security exit 0 (bandit no issues, pip-audit and npm audit clean). |
| REG-07 | regression | Regression sweep after the cross-check fixes: every fixed finding's probe again | 44 of 44 probes pass on fdbdcd4 (BE, REV, REV2, smithery, dashboard build, the 18-step e2e), then make check and make security exit 0. |

### Run notes

- 2026-09-24T20:33:18+00:00: Adversarial review round 1 (independent agent, cold start from the rendered log): 17 findings REV-01..17 (1 critical: live Guardian sized at the caller's price; 1 high: kill switch blocked cancels; the rest medium/low), all fixed with regression tests and fresh retests. Round 2 (second independent agent, focused on the round-1 fixes): 10 findings REV2-01..10 (1 high: contract symbols traded as spot dodged the position check), all fixed and retested. Weak retests strengthened: BE-01 (live path + allowed control), BE-02 (held BTC, invented sell price), BE-08 (real uvicorn API server), BE-12 (Docker wrong password/username), DOCK-02 (nested canaries). FK-01 records what the Falling Knife study's files can and cannot prove.

---
