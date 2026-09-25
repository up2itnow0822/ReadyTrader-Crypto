# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Purpose

ReadyTrader-Crypto is an MCP + FastAPI crypto trading stack (CEX via ccxt, optional DEX) with paper/live gates, policy/risk controls, and agent-facing tools. Primary production path for Agent Economy BTC work: spot BTC/USDT via Hermes stdio MCP.

## Ownership

- Owner: Agent Economy, LLC / Bill Wilson (@up2itnow0822)
- Runtime surfaces: MCP (`server.py` / `app/main.py`), FastAPI (`api_server.py`), optional Next.js frontend

## Read Before Editing

1. Read the root AGENTS.md
1. Identify every file or folder you expect to touch
1. Walk from the repository root to each target path
1. Read every AGENTS.md found along each route
1. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
1. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
1. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:

- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## User Preferences

- Fail closed for production: when `DEV_MODE=false`, API auth required (including WebSocket `/ws` JWT), CORS must not be `*`, `TRADING_HALTED` defaults true; keep `.env.live` / `.env.*.local` gitignored
- `TRADING_HALTED` refuses new live orders, swaps and transfers and private streams; account reads and cancels (`get_cex_*`, `list_cex_*`, `cancel_*`, `wait_for_cex_order`) pass `allowed_while_halted=True` so an operator can always see and cancel resting orders
- Never use `SIGNER_TYPE=env_private_key` when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`
- Hermes integration is stdio MCP + skill — do not grow core Hermes tools for ReadyTrader
- Live dust trades are out of scope until a dedicated Phase 4 UAT

## Work Guidance

- Paper-first: `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false` for local/dev
- BTC production profile: `EXECUTION_MODE=cex`, allowlist BTC pairs only, `EXECUTION_APPROVAL_MODE=approve_each`
- Secrets stay in `.env` / operator vault — never commit
- Quality gate: `make check` and `make security`
- `requirements.txt` owns pinned runtime dependencies; regenerate `requirements.lock.txt` from a clean `requirements-dev.txt` environment after dependency changes and verify it with `pip check` and `pip-audit`
- `sentiment_score` fed to the Risk Guardian is the bull-bear spread in [-1, 1] from `intelligence/sentiment.py` (scored locally and deterministically - no model or network call); missing, unconfigured or thin data is neutral `0.0` and `validate_trade_risk` must report it in `sentiment.status`; only sources with usable nonblank text count as contributors, and a degraded refresh may tighten a fresh bearish reading but must not relax it; when tightening on degraded data, retain prior contributors as recovery guards until they return, while keeping actual current contributors separate; an intentionally single-source clean refresh may replace it; a printed 8%+ drop is directional bearish and may lower the consensus floor to 3; change the vocabulary or that cue only with fresh feeds added to `tests/fixtures/sentiment_feeds.json`
- Numeric MCP tool parameters use `app/tools/params.py` (`Number`, `Integer`), which refuse `true`/`false` before pydantic's lax conversion to 1/0; new numeric tool parameters use them too
- `api_server.py` adds `CORSMiddleware` after its `@app.middleware("http")` functions, so CORS is outermost and the answers those write (429, the JSON 500) carry CORS headers
- All MCP tool modules serialize their return value through `app/core/jsonio` (`{"ok": true, "data": ...}` / `{"ok": false, "error": {...}}`) — do not hand-roll a different envelope shape
- User strategy code is executed only via `strategy_sandbox.run_strategy` (child process, rlimits, RestrictedPython, static AST pre-check); no other path may `exec`/`eval` agent-supplied code
- Token-less trade confirmation is an HTTP-admin-only path (`_operator_may_confirm_without_token` in `api_server.py`); no MCP tool may call `ExecutionStore.confirm_as_operator` or `app.tools.execution.approved_execution` — those are internal to the FastAPI process
- Paper orders are recorded only through `PaperTradingEngine.execute_trade_result`; do not add a second paper-fill code path
- Every MCP tool name referenced in docs must be a real, registered tool or an explicit, justified `ALLOWLIST` entry — this is enforced by `tests/test_docs_tool_roster.py`, which fails CI on drift. `docs/TOOLS.md` is curated (update it with any tool change); `tools/generate_tool_docs.py` only prints the live registry
- The Risk Guardian runs on every order: `place_cex_order`, `swap_tokens` and `replace_cex_order` call `app/tools/trading.pre_trade_check` / `swap_check` before a paper fill, a live proposal or a live send, and approvals re-run the tool. Size is the USD value of the exposure an order adds (paper account; exchange account for live CEX; signer wallet for live swaps), valued at the market-data price (a limit at the higher of limit and market) and never at a caller-supplied price alone; selling what is held into cash (`CASH_QUOTES`) is an exit, selling into a crypto quote sizes the acquired quote; an order that adds exposure and has no market price, cannot be valued, or whose account cannot be read, is refused (`risk_blocked`). The Falling Knife rule judges the asset an order buys (the quote on a crypto-quoted SELL). A contract symbol (`BASE/QUOTE:SETTLE`) is never sized from a spot balance, is refused with `market_type=spot`, and is refused by the paper ledger (spot only). Paper drawdown/daily-loss read a time-weighted performance index (deposits valued when made are neither gains nor losses; the account's current marked value ends the series; the daily baseline is the last snapshot of the previous UTC day, else the day-open mark written by `mark_day_open`); `deposit_paper_funds` refuses an asset it cannot price; `paper_engine.USD_STABLES` is the one stablecoin list; the live order path sends the normalised side/order_type
- No price-based Falling Knife rule for crypto (`docs/FALLING_KNIFE.md`): add one only through the pre-registered protocol in `research/falling_knife/` (nothing imports that folder)
- Paper orders fill at the market-data bus price (a limit only when marketable; swaps at the market rate), never at a caller's price; paper mode never reaches an exchange account (the exchange-order tools answer `paper_mode_not_supported`)
- Live refusals answer with their own code (`LiveGateRefused`: `live_trading_disabled`, `trading_halted`, `execution_mode_blocked`; `PolicyError` codes); `cex_error` / `execution_error` / `transfer_error` are for unexpected failures only
- Proposals record `paper_mode` and `/api/approve-trade` executes one only in that mode (`EXEC_313`); `EXECUTION_SESSION_ID` + `EXECUTION_DB_PATH`, shared by the MCP and API servers, put them in one proposal session; confirm and cancel are conditional database updates (single use across processes)
- Default data files come from `storage_paths.data_path` (`<repo>/data/` or `READYTRADER_DATA_DIR`), never the working directory; each `*_PATH` variable still wins
- A news or sentiment source that cannot answer raises `intelligence.SourceError`; tools return it as `not_configured` / `source_unavailable`, never as an `ok: true` payload
- Unit tests never reach an exchange for a price: `tests/conftest.py` (`offline_market_prices`) serves fixed prices through the market-data bus
- Docker: the Dockerfile's last stage is the MCP server (what every MCP-client config runs); the API server is `--target api`; the image defaults to `TRADING_HALTED=true`; `.dockerignore` excludes every `.env*`, key file and local database in any folder (`**/` patterns), the virtualenv, `.git`, `uat/` and `frontend/`. Both compose files give the api and mcp services one `EXECUTION_DB_PATH` and `EXECUTION_SESSION_ID`; `docker-compose.sentinel.yml` runs the API stage; the Docker MCP configs mount a named volume on `/app/data` so the paper account persists. `smithery.yaml` lists only optional source keys under `startCommand.configSchema`, and its `commandFunction` always starts the paper profile
- API authentication libraries (PyJWT, bcrypt) are runtime requirements in `requirements.txt`; admin passwords are verified with `bcrypt` directly (no passlib)

## Verification

- `make check` (ruff + pytest)
- `make security` (bandit + pip-audit + `npm audit --prefix frontend`)
- Paper BTC harness: `python examples/paper_btc_uat.py`
- UAT evidence: `UAT.md` (current graduation-gate status, test matrix, sign-off table) +
  `uat/UAT-LOG.md` (the 2026-09-24 public-release UAT: every check with its captured evidence) +
  `docs/uat/2026-09-23-reverification.md` (the previous dated re-verification pass). `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md` is the 2026-09-14
  pass, now superseded and kept for history — do not treat it as current.
- Hermes skill (public MIT package): https://github.com/up2itnow0822/readytrader-crypto-hermes →
  install into `~/.hermes/skills/` with
  `hermes skills install up2itnow0822/readytrader-crypto-hermes/skills/finance/readytrader-crypto --category finance`
  (see `docs/HERMES_INTEGRATION.md`). `optional-skills/` is that package's own Nous
  contribution tree and is never loaded at runtime — do not install there.
- `tests/test_strategy_sandbox.py` — sandbox isolation, rejected constructs, resource limits
- `tests/test_approval_api.py` — approval-gate HTTP flow (`AUTH_604`, `EXEC_308`–`EXEC_313`)
- `tests/test_uat_2026_09_24.py` — one regression test per finding of the 2026-09-24 public-release UAT (Risk Guardian in the order path, paper fills, paper isolation, live refusal codes, shared proposal sessions, data paths, source errors) and of its adversarial review (market-price sizing, kill switch vs cancels, deposit-neutral drawdown, crypto-quote sells, NaN amounts, stablecoins, nested .dockerignore, Docker volume, sentinel stack, failing sentiment source, login timing, per-request log ids) and its second round (contract symbols, daily baseline, time-weighted loss limits, unpriced deposits, Falling Knife on the bought asset, normalised orders, 500s with request ids, smithery config)
- Dashboard e2e: `cd frontend && npm ci && env -u NODE_ENV npm run e2e` (18 journeys against the real API server)
- `tests/test_paper_order_integrity.py` — paper ledger validation and atomicity
- `tests/test_tool_json_contract.py` — every MCP tool's response matches the `jsonio` envelope
- `tests/test_docs_tool_roster.py` — no phantom tool names in docs; `docs/TOOLS.md` matches the registered roster exactly

## Closeout

1. Re-check changed paths against the DOX chain
1. Update nearest owning docs and any affected parents or children
1. Refresh every affected Child DOX Index
1. Remove stale or contradictory text
1. Run existing verification when relevant
1. Report any docs intentionally left unchanged and why

## Child DOX Index

| Path                                             | Owns                                                                                         |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| [uat/AGENTS.md](uat/AGENTS.md)                   | The UAT reporting log, ledger and evidence                                                   |
| [signing/AGENTS.md](signing/AGENTS.md)           | Signer backends, policy wrapper, live-key custody rules                                      |
| [sentinel/AGENTS.md](sentinel/AGENTS.md)         | Dev/demo remote-signer reference service: Bearer-token auth, fail-closed posture             |
| [docs/AGENTS.md](docs/AGENTS.md)                 | Operator docs, Hermes integration, UAT/runbooks                                              |
| [frontend/AGENTS.md](frontend/AGENTS.md)         | Next.js operator dashboard: auth, approvals, status                                          |
| [app/](app/)                                     | Core settings, container, MCP/API tool wiring (parent-owned until split)                     |
| [execution/](execution/)                         | CEX/DEX executors (parent-owned)                                                             |
| [intelligence/](intelligence/)                   | News/social fetchers and the sentiment scorer behind Falling Knife protection (parent-owned) |
| [tests/](tests/)                                 | Unit/integration tests (parent-owned)                                                        |
| [.autoimprove/AGENTS.md](.autoimprove/AGENTS.md) | Paper/CI auto-improve loop evidence (Phase 0 baseline, Phase 1 Falling Knife rounds)         |
| [research/falling_knife/](research/falling_knife/) | The price Falling Knife study behind `docs/FALLING_KNIFE.md` (parent-owned; see its README)  |
