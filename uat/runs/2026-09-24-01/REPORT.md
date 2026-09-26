# UAT run 2026-09-24-01 — ReadyTrader-Crypto: CLEAN with BLOCKED items

83 checks · 21 pass · 60 fail (60 fixed & verified, 0 open, 0 fixed-unverified, 0 regressed) · 2 blocked

Scope: In: MCP server (stdio), FastAPI approval API, Next.js dashboard, CLI/examples, config, docs, registry manifest, the Falling Knife decision for crypto. Money paths paper only; no live orders, no dust trades (Phase 4 needs Bill's authorization); signer paths with test keys only.

## What was broken and is now fixed

- **critical** BE-01 — Risk Guardian runs in the order path (README: every request is filtered; a 50% bet is blocked automatically) → Every order path (place_cex_order, swap_tokens, replace_cex_order; paper and live; before a proposal and again at approval) runs app/tools/trading.pre_trade_check / swap_check: the Risk Guardian sizes the exposure an order adds against the account (paper / exchange / signer wallet) and fails closed when it cannot value the order or read the account (or the account is worth nothing) (`9e25268,9c65746`) · **VERIFIED**
- **critical** BE-04 — Paper mode never touches a real exchange account (cancel/replace/read tools) → In paper mode the exchange-order tools answer paper_mode_not_supported before any exchange client is built (`9e25268`) · **VERIFIED**
- **critical** BE-05 — Live replace_cex_order passes the approval gate, allowlists and size limit → replace_cex_order is refused (approval_required) under approve_each and otherwise runs validate_cex_order and the Risk Guardian on the replacement order (`9e25268`) · **VERIFIED**
- **critical** BE-12 — An operator can sign in to the dashboard API in production mode (DEV_MODE=false, bcrypt admin hash) → api_server uses bcrypt.checkpw/hashpw (72-byte limit handled; constant-time username and dev plaintext compares); PyJWT and bcrypt are runtime requirements; passlib removed; hash command updated in env.example, env.live.btc.example, docker-compose.yml (`d760186`) · **VERIFIED**
- **critical** DOCK-01 — README Docker path: docker build -t readytrader-crypto . ; docker run -i --rm readytrader-crypto serves MCP over stdio → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`) · **VERIFIED**
- **critical** REV-01 — Live Risk Guardian sizes an order at the market price, not the caller's → Orders are valued at the market-data price (a limit at max(limit, market)); no market price refuses an order that adds exposure; order_type passed from every path (`011fa78`) · **VERIFIED**
- **high** BE-02 — Paper fills use the market price (a limit fills only when marketable; a market order ignores an invented price) → Paper place_cex_order fills at the market-data price: market orders ignore a passed price; a limit fills (at market) only when marketable, else limit_not_marketable (`9e25268`) · **VERIFIED**
- **high** BE-03 — Paper swap_tokens trades at the market rate → Paper swap_tokens trades at the market rate (FROM/TO, inverse, or through USDT) and is risk-checked; paper_price_required when no rate (`9e25268`) · **VERIFIED**
- **high** BE-08 — An approve_each proposal made by the MCP server can be approved from the API server / dashboard (UAT.md T5) → ExecutionStore takes EXECUTION_SESSION_ID; with persistence the database is the source of truth (list/confirm/cancel read it; confirm and cancel are conditional UPDATEs); proposals record paper_mode and /api/approve-trade answers 409 EXEC_313 in the other mode (`9e25268`) · **VERIFIED**
- **high** CF-01 — Server started by an MCP client (README configs: absolute python + server.py, client's working directory) keeps its data in the repo → storage_paths.data_path anchors every default data file to <repo>/data (READYTRADER_DATA_DIR overrides; *_PATH still wins) (`9e25268`) · **VERIFIED**
- **high** DATA-01 — Paper risk metrics: drawdown is the current fall from the peak; resting orders keep their reserved value → get_risk_metrics reports the current drawdown (max_drawdown_pct keeps the record); portfolio value counts funds reserved by resting orders (`9e25268`) · **VERIFIED**
- **high** DOCK-02 — The image carries no local secrets or local data → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`) · **VERIFIED**
- **high** DOCK-04 — docker-compose up -d (compose header) starts the API and MCP services with the shipped defaults → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`) · **VERIFIED**
- **high** DOCK-05 — The BTC-live compose stack (docs/OPS_BTC_PRODUCTION.md) lets the dashboard approve the MCP server's proposals → Both live services get EXECUTION_DB_PATH=/app/data/execution.db and a required EXECUTION_SESSION_ID; env.live.btc.example sets EXECUTION_SESSION_ID=btc-live-desk-1 (`ccaa6c4`) · **VERIFIED**
- **high** REV-02 — With the kill switch on, open orders can still be listed and cancelled → Reads and cancels pass allowed_while_halted=True; the emergency procedure is restart halted, cancel_all_cex_orders, revert to paper (`011fa78,6ef8957`) · **VERIFIED**
- **high** REV2-01 — A contract symbol cannot be traded as spot to dodge the position check → Contract symbols never read a spot position; _order_args refuses a contract symbol with market_type=spot (`839bcb4`) · **VERIFIED**
- **medium** BE-06 — A refused live order says why (kill switch, allowlist, size limit) → Live gates raise LiveGateRefused(code) and policy refusals keep their PolicyError code/message/data; only unexpected exceptions become cex_error (`9e25268`) · **VERIFIED**
- **medium** BE-09 — approve_each proposes only an order the live policy allows → Policy (validate_cex_order / validate_swap / validate_transfer_native), then the Risk Guardian, run before _maybe_propose and again when the approved call executes (`84507d2`) · **VERIFIED**
- **medium** CLI-01 — tools/setup_wizard.py (docs/ERRORS.md: 'Run python tools/setup_wizard.py') guides a new paper user correctly → ask() treats a closed stdin as no; the key report shows SIGNER_TYPE (env_private_key called out as dev-only), needs no exchange key in paper mode, lists feed keys as optional; a 451 from Binance explains MARKETDATA_EXCHANGES (`46b42fb`) · **VERIFIED**
- **medium** DATA-02 — Asset codes are case-insensitive in the paper ledger → The paper ledger upper-cases asset codes (orders, deposits, lookups) (`9e25268`) · **VERIFIED**
- **medium** DOC-03 — README configuration defaults match the code → README corrected (see commit) (`e152134`) · **VERIFIED**
- **medium** DOC-04 — README feature list describes what ships → README corrected (see commit) (`e152134`) · **VERIFIED**
- **medium** DOC-06 — The README's Agent Zero integration works in current Agent Zero → README Option A points to the Agent Zero plugin first; the hand-made entry is the {"mcpServers": ...} JSON for Settings -> MCP/A2A -> External MCP Servers (configs/agent_zero.mcp.json, data volume included); the YAML moved to _deprecated/configs/ (`b37d32f`) · **VERIFIED**
- **medium** DOCK-03 — Containers keep the fail-closed kill-switch default → See commit cd6076b: MCP is the default image stage; .dockerignore excludes .env*, keys, data, envs, history, frontend; TRADING_HALTED=true in image and compose; compose defaults to SIGNER_TYPE=null, API auth on with API_JWT_SECRET required, explicit targets and a shared EXECUTION_SESSION_ID (`cd6076b`) · **VERIFIED**
- **medium** FE-01 — Documented dashboard e2e command (UAT.md T6) runs on a fresh clone → e2e/constants.ts HARNESS_PYTHON (repo .venv, else python3, PW_PYTHON_PATH overrides) is used by playwright.config.ts and apiControl.ts; report in frontend/playwright-report; ESLint ignores playwright-report/ and test-results/ (`ce047ec`) · **VERIFIED**
- **medium** INT-01 — A news/sentiment source that cannot answer is an error, not a result → News and sentiment sources raise intelligence.SourceError; get_financial_news, get_news, get_social_sentiment, get_free_news and get_sentiment return not_configured / source_unavailable (`9e25268`) · **VERIFIED**
- **medium** REV-03 — The paper drawdown halt reads current equity and a deposit does not clear it → Snapshots record net deposits (valued when made); drawdown/daily loss read results net of deposits against the equity at the peak, with the current marked value appended; the Guardian marks prices before reading metrics (`011fa78`) · **VERIFIED**
- **medium** REV-04 — A SELL on a crypto-quoted pair sizes the asset it acquires → A SELL into a non-cash quote sizes the acquired quote (CASH_QUOTES = USD stables + major fiat) (`011fa78`) · **VERIFIED**
- **medium** REV-05 — The Docker build context excludes secrets in subfolders → Secret, key and database patterns are **/-prefixed (`e858eb3`) · **VERIFIED**
- **medium** REV-06 — Docs say which Risk Guardian rules apply to live orders → Docs say the daily-loss and drawdown limits run on the paper account and are reported as inactive_rules live (`6ef8957`) · **VERIFIED**
- **medium** REV-07 — The documented Docker MCP config keeps the paper account between sessions → Configs and README mount readytrader-crypto-data on /app/data (`e858eb3`) · **VERIFIED**
- **medium** REV-17 — docker-compose.sentinel.yml keeps the readytrader service running → readytrader builds target api with the API's required settings (`e858eb3`) · **VERIFIED**
- **medium** REV2-02 — The daily-loss rule measures today's loss → Baseline = previous UTC day's last snapshot, else the day-open mark (mark_day_open at the first risk check) (`839bcb4`) · **VERIFIED**
- **medium** REV2-03 — Loss limits measure losses against the capital now in the account → Time-weighted performance index: each period's return excludes deposits; drawdown and daily loss read the index (`839bcb4`) · **VERIFIED**
- **low** AR-01 — Every numeric tool parameter refuses true → Every numeric tool parameter is typed Number or Integer (a validator refuses booleans first). (`fdbdcd4`) · **VERIFIED**
- **low** AR-02 — The API's own 429 and 500 answers carry CORS headers → CORS is added after them and wraps every answer. (`fdbdcd4`) · **VERIFIED**
- **low** AR-03 — The docs say how the daily-loss baseline is taken → TOOLS.md gives the baseline and that it errs toward halting. (`fdbdcd4`) · **VERIFIED**
- **low** BE-07 — API server log lines carry the time of the event → log_event stamps ts_ms at emit time (`9e25268`) · **VERIFIED**
- **low** CF-02 — Every variable the code reads is in env.example → env.example lists ONEINCH_API_KEY, LOG_LEVEL, CEX_* tuning, signing, OTEL, stores, EXECUTION_SESSION_ID, READYTRADER_DATA_DIR (`9e25268`) · **VERIFIED**
- **low** CF-03 — env.example's signer is safe to start from → env.example: SIGNER_TYPE=null with the live signers listed and env_private_key described as development-only (`d9a23b2`) · **VERIFIED**
- **low** DOC-01 — docs/TOOLS.md is what the README says: generated from the live registry → docs/TOOLS.md corrected tool by tool against the code (curated, roster-tested); generate_tool_docs.py prints the registry and refuses to overwrite TOOLS.md (`9e25268,e152134`) · **VERIFIED**
- **low** DOC-02 — README prerequisites name what the install needs → README corrected (see commit) (`e152134`) · **VERIFIED**
- **low** DOC-05 — README Agent Zero UI instructions run the image the README builds → README corrected (see commit) (`e152134`) · **VERIFIED**
- **low** FK-01 — The crypto no-price-rule decision is reproducible as described → README says only the v2 scoring scripts check the hash and that git history cannot show freeze-before-score; FALLING_KNIFE.md says the same (`5506954`) · **VERIFIED**
- **low** REV-08 — The dashboard labels the current drawdown correctly → Drawdown from peak + Max drawdown; stablecoin set matches the server (`2d8f827`) · **VERIFIED**
- **low** REV-09 — A NaN amount is refused on every order path → Shared _order_args validation for place and replace; pre_trade_check refuses a non-positive or non-finite amount (`011fa78`) · **VERIFIED**
- **low** REV-10 — transfer_eth refuses a NaN or negative amount before proposing → transfer_eth refuses a non-finite or non-positive amount with invalid_amount before policy or proposal (`011fa78`) · **VERIFIED**
- **low** REV-11 — The paper account values every USD stablecoin the Guardian knows at 1 USD → paper_engine.USD_STABLES is the one list; trading imports it (`011fa78`) · **VERIFIED**
- **low** REV-12 — get_social_sentiment says when a configured source fails → social_sentiment_report returns each source's state; all configured sources erroring answers source_unavailable (`e8290a8`) · **VERIFIED**
- **low** REV-13 — Login takes the same time for an unknown username as for a wrong password → The password check runs for every username; both must pass (`e8290a8`) · **VERIFIED**
- **low** REV-14 — API log lines carry a per-request request_id → request_id_middleware sets a per-request id (per connection on /ws); logs use _ctx(); X-Request-ID header (`e8290a8`) · **VERIFIED**
- **low** REV-15 — RISK_PROFILE does what the docs say → Documented as reserved and not applied; removed from the smithery config schema and both Hermes samples (`e858eb3,3b58fa4`) · **VERIFIED**
- **low** REV-16 — Hermes guide, smithery manifest and README match the server → Hermes guide, smithery description and README compose line match the server (`e858eb3`) · **VERIFIED**
- **low** REV2-04 — Docs say which exits the Guardian treats as exits → Docs say derivatives positions are unknown and closing orders are sized; contract symbols need market_type swap/future (`2f4795e`) · **VERIFIED**
- **low** REV2-05 — A paper deposit cannot end a drawdown halt → deposit_paper_funds refuses a non-stable asset it cannot price (paper_price_required); the engine comment says what direct callers get (`839bcb4`) · **VERIFIED**
- **low** REV2-06 — The Falling Knife rule applies to what an order buys → On a crypto-quoted SELL the quote's sentiment is checked as a BUY of the quote; risk.sentiment_asset names it (`839bcb4`) · **VERIFIED**
- **low** REV2-07 — Paper orders refuse contract symbols; the exchange gets the normalised order → Paper ledger refuses contract symbols; policy, proposal, exchange and summary get the normalised side/order_type (`839bcb4`) · **VERIFIED**
- **low** REV2-08 — An unhandled API error still carries the request id and security headers → request_id_middleware catches, logs with the request id, answers JSON SYS_803 with security headers and X-Request-ID (`839bcb4`) · **VERIFIED**
- **low** REV2-09 — Docs give the kill switch's default and how to use it → Default true; halting is a restart with TRADING_HALTED=true; README says reads and cancels still work (`2f4795e`) · **VERIFIED**
- **low** REV2-10 — smithery.yaml passes its settings to the server → startCommand.configSchema lists the optional keys; commandFunction always sets the paper profile and passes the keys (`2f4795e`) · **VERIFIED**

## Still blocked (needs the user)

- INT-03 — Keyed news and social sources (NewsAPI, CryptoPanic, X, Reddit) with real keys: blocked on Bill supplies NEWSAPI_KEY, CRYPTOPANIC_API_KEY, TWITTER_BEARER_TOKEN, REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET (optional feeds)
- INT-04 — Live exchange account, 1inch swaps and an EVM signer (read-only / sandbox): blocked on Bill supplies exchange sandbox/testnet keys (trade+read, no withdraw) and, for DEX, ONEINCH_API_KEY + a testnet RPC and signer; then run tests/integration/test_exchange_sandbox.py and a read-only get_cex_balance

## Coverage

| Section | Checks | Status |
|---|---|---|
| preflight | 10 | covered |
| backend | 24 | covered |
| data | 8 | covered |
| memory | 1 | covered |
| frontend | 6 | covered |
| integrations | 5 | covered |
| cli | 1 | covered |
| config | 12 | covered |
| docs | 14 | covered |
| journeys | 6 | recorded |

## Delivery

- Branch `uat/2026-09-24-crypto` has a remote (`origin`) but no upstream — it has not been pushed.
- Base: `main@67fd39c`
- DOX: root AGENTS.md indexes `uat/AGENTS.md`
- Log: `uat/UAT-LOG.md` · evidence: `uat/evidence/2026-09-24-01/` (0.23 MB)
