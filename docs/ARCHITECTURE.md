# ReadyTrader-Crypto Architecture

This document describes the system architecture, component interactions, and data flows in ReadyTrader-Crypto.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT LAYER                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Claude     │  │   Gemini     │  │ Agent Zero   │  │   Custom     │    │
│  │   Desktop    │  │   Agent      │  │              │  │   Agent      │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │             │
│         └─────────────────┴────────┬────────┴─────────────────┘             │
│                                    │                                         │
│                           MCP Protocol (stdio/HTTP)                          │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────────┐
│                         READYTRADER-CRYPTO MCP SERVER                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                           FastMCP Server                             │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │   │
│  │  │Market Data  │ │  Trading    │ │  Research   │ │  Execution  │   │   │
│  │  │   Tools     │ │   Tools     │ │   Tools     │ │   Tools     │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────▼─────────────────────────────────────┐ │
│  │                        SAFETY & GOVERNANCE LAYER                       │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│  │  │    Risk     │  │   Policy    │  │  Execution  │  │    Rate     │  │ │
│  │  │  Guardian   │  │   Engine    │  │   Store     │  │  Limiter    │  │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│  ┌─────────────────────────────────▼─────────────────────────────────────┐ │
│  │                         EXECUTION LAYER                                │ │
│  │  ┌─────────────────────┐              ┌─────────────────────┐        │ │
│  │  │      CEX Executor    │              │     DEX Handler      │        │ │
│  │  │  ┌───────────────┐  │              │  ┌───────────────┐  │        │ │
│  │  │  │    Binance    │  │              │  │    1inch      │  │        │ │
│  │  │  │    Kraken     │  │              │  │   Uniswap V3  │  │        │ │
│  │  │  │   Coinbase    │  │              │  │    Aave V3    │  │        │ │
│  │  │  │   100+ more   │  │              │  └───────────────┘  │        │ │
│  │  │  └───────────────┘  │              │                      │        │ │
│  │  └─────────────────────┘              └─────────────────────┘        │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│  ┌─────────────────────────────────▼─────────────────────────────────────┐ │
│  │                        SIGNING & CUSTODY                               │ │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐         │ │
│  │  │ Env Key   │  │ Keystore  │  │  Remote   │  │ MPC 2PC   │         │ │
│  │  │ Signer    │  │  Signer   │  │  Signer   │  │  Signer   │         │ │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘         │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SERVICES                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Exchanges  │  │  Blockchains │  │ Data APIs  │  │  Webhooks   │        │
│  │  (CEX/DEX)  │  │  (EVM RPCs)  │  │  (News/Soc)│  │  (Discord)  │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### 1. AI Agent Layer

AI agents connect to ReadyTrader-Crypto via the Model Context Protocol (MCP). Supported agents:

- **Claude Desktop**: Anthropic's desktop app with MCP support
- **Agent Zero**: Open-source agent framework
- **Custom Agents**: Any MCP-compatible agent

### 2. MCP Server (FastMCP)

The core server exposes tools organized into categories:

| Category    | Tools                                              | Purpose                           |
| ----------- | -------------------------------------------------- | --------------------------------- |
| Market Data | `get_crypto_price`, `fetch_ohlcv`, `get_sentiment` | Price feeds, historical data      |
| Trading     | `deposit_paper_funds`, `validate_trade_risk`       | Paper trading, risk validation    |
| Research    | `run_backtest_simulation`, `get_market_regime`     | Strategy testing, market analysis |
| Execution   | `place_cex_order`, `swap_tokens`, `transfer_eth`   | Live/paper trade execution        |

### 3. Safety & Governance Layer

```
┌─────────────────────────────────────────────────────────────────┐
│                    Request Flow Through Safety Layer             │
│                                                                  │
│  Agent Request                                                   │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐                                                │
│  │Rate Limiter │──▶ Blocks if rate exceeded                     │
│  └──────┬──────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐                                                │
│  │Risk Guardian│──▶ Validates position size, sentiment, limits  │
│  └──────┬──────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐                                                │
│  │Policy Engine│──▶ Enforces allowlists (chains, tokens, etc.)  │
│  └──────┬──────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐                                                │
│  │Exec. Store  │──▶ Creates approval proposal if approve_each   │
│  └──────┬──────┘                                                │
│         │                                                        │
│         ▼                                                        │
│    Execution                                                     │
└─────────────────────────────────────────────────────────────────┘
```

#### Risk Guardian Rules

The Risk Guardian runs on every order (`app/tools/trading.pre_trade_check` for CEX orders,
`swap_check` for swaps), paper and live, before a live order is proposed and again when an
approved proposal executes. It judges the exposure an order adds, valued at the market price:
selling what is held into cash is an exit; selling into a crypto quote (ETH/BTC) buys the quote
asset, which is sized.

| Rule          | Threshold                                     | Action                                                         |
| ------------- | --------------------------------------------- | -------------------------------------------------------------- |
| Position Size | Added exposure over 5% of the account's value | Block (valued at the market price)                             |
| Daily Loss    | 5% loss today (paper account)                 | Block orders that add exposure                                 |
| Max Drawdown  | 10% below the best result (paper account)     | Block orders that add exposure (deposits do not clear it)      |
| Falling Knife | Sentiment < -0.5                              | Block BUYs (no price rule for crypto: `docs/FALLING_KNIFE.md`) |
| Unreadable    | No market price, or account unreadable        | Block orders that add exposure                                 |

The account is the paper account in paper mode, the exchange account for live CEX orders and the
signer wallet on the chain for live swaps.

#### Policy Engine Allowlists

| Setting   | Environment Variable     | Effect                      |
| --------- | ------------------------ | --------------------------- |
| Chains    | `ALLOW_CHAINS`           | Restrict to specific chains |
| Tokens    | `ALLOW_TOKENS`           | Restrict tradeable tokens   |
| Exchanges | `ALLOW_EXCHANGES`        | Restrict to specific CEXs   |
| Signers   | `ALLOW_SIGNER_ADDRESSES` | Pin expected signer address |

### 4. Execution Layer

#### CEX Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     CEX Order Execution Flow                     │
│                                                                  │
│  place_cex_order(symbol, side, amount)                          │
│       │                                                          │
│       ├──▶ Paper Mode? ──▶ Paper Engine ──▶ Return result       │
│       │                                                          │
│       ▼                                                          │
│  Policy Validation                                               │
│       │                                                          │
│       ├──▶ Approval Required? ──▶ Create Proposal ──▶ Wait      │
│       │                                                          │
│       ▼                                                          │
│  CexExecutor (CCXT)                                             │
│       │                                                          │
│       ├──▶ Symbol Resolution (spot/swap/future)                 │
│       ├──▶ Retry with Exponential Backoff                       │
│       │                                                          │
│       ▼                                                          │
│  Exchange API ──▶ Order Response ──▶ Audit Log                  │
└─────────────────────────────────────────────────────────────────┘
```

#### DEX Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEX Swap Execution Flow                      │
│                                                                  │
│  swap_tokens(from_token, to_token, amount, chain)               │
│       │                                                          │
│       ├──▶ Paper Mode? ──▶ Paper Engine ──▶ Return result       │
│       │                                                          │
│       ▼                                                          │
│  Policy Validation (chain, tokens, amounts)                     │
│       │                                                          │
│       ├──▶ Approval Required? ──▶ Create Proposal ──▶ Wait      │
│       │                                                          │
│       ▼                                                          │
│  DexHandler.build_swap_tx() ──▶ 1inch API                       │
│       │                                                          │
│       ▼                                                          │
│  Signer.sign_transaction() ──▶ Sign with configured signer      │
│       │                                                          │
│       ▼                                                          │
│  send_raw_transaction() ──▶ Broadcast to RPC                    │
│       │                                                          │
│       ▼                                                          │
│  Audit Log ──▶ Return tx_hash                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 5. Market Data Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Market Data Bus Architecture                   │
│                                                                  │
│  ┌─────────────────┐   Priority 0 (Highest)                     │
│  │ WebSocket Store │◀── exchange_ws (real-time from WS)         │
│  └────────┬────────┘                                            │
│           │                                                      │
│  ┌────────▼────────┐   Priority 1                               │
│  │  Ingest Store   │◀── User-supplied feeds / other MCPs        │
│  └────────┬────────┘                                            │
│           │                                                      │
│  ┌────────▼────────┐   Priority 2 (Fallback)                    │
│  │  CCXT REST      │◀── ccxt_rest (REST API polling)            │
│  └────────┬────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐                                            │
│  │ MarketDataBus   │── Freshness Scoring + Outlier Detection    │
│  │                 │── MARKETDATA_FAIL_CLOSED mode              │
│  └─────────────────┘                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 6. Signing Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Signer Abstraction Layer                     │
│                                                                  │
│  SIGNER_TYPE=env_private_key                                    │
│  ┌─────────────────┐                                            │
│  │ EnvPrivateKey   │── Uses PRIVATE_KEY env var                 │
│  │ Signer          │── Simple, for development/testing          │
│  └─────────────────┘                                            │
│                                                                  │
│  SIGNER_TYPE=keystore                                           │
│  ┌─────────────────┐                                            │
│  │ Keystore        │── Uses KEYSTORE_PATH + KEYSTORE_PASSWORD   │
│  │ Signer          │── Encrypted key file                       │
│  └─────────────────┘                                            │
│                                                                  │
│  SIGNER_TYPE=remote                                             │
│  ┌─────────────────┐                                            │
│  │ Remote          │── Uses SIGNER_REMOTE_URL                   │
│  │ Signer          │── HTTP signer sidecar                      │
│  └─────────────────┘                                            │
│                                                                  │
│  SIGNER_TYPE=cb_mpc_2pc                                         │
│  ┌─────────────────┐                                            │
│  │ Coinbase MPC    │── Uses MPC_SIGNER_URL                      │
│  │ 2PC Signer      │── Institutional-grade custody              │
│  └─────────────────┘                                            │
│                                                                  │
│  Optional: PolicySigner Wrapper                                  │
│  ┌─────────────────┐                                            │
│  │ Validates:      │── Chain IDs, To addresses                  │
│  │                 │── Value limits, Gas limits                 │
│  │                 │── Data size, Contract creation             │
│  └─────────────────┘                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 7. Observability Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                     Observability Components                     │
│                                                                  │
│  ┌─────────────┐                                                │
│  │ Audit Log   │── SQLite with tamper-evident hash chain        │
│  │             │── Tax report export (CSV)                      │
│  └─────────────┘                                                │
│                                                                  │
│  ┌─────────────┐                                                │
│  │ Metrics     │── In-memory counters, timers, gauges           │
│  │             │── Prometheus exposition format                 │
│  └─────────────┘                                                │
│                                                                  │
│  ┌─────────────┐                                                │
│  │ Tracing     │── OpenTelemetry integration (optional)         │
│  │             │── OTLP exporter support                        │
│  └─────────────┘                                                │
│                                                                  │
│  ┌─────────────┐                                                │
│  │ Webhooks    │── Discord notifications                        │
│  │             │── Approval required alerts                     │
│  └─────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow: Complete Trade Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│              Complete Trade Lifecycle (approve_each mode)        │
│                                                                  │
│  1. Agent: "Buy 0.01 BTC at market"                             │
│       │                                                          │
│       ▼                                                          │
│  2. MCP Server: place_cex_order(BTC/USDT, buy, 0.01)           │
│       │                                                          │
│       ▼                                                          │
│  3. Rate Limiter: Check API rate                                │
│       │                                                          │
│       ▼                                                          │
│  4. Risk Guardian: pre_trade_check() (exchange account read)    │
│       │  - Position size OK (< 5%)                              │
│       │  - Daily loss OK (< 5%)                                 │
│       │  - Sentiment OK (not falling knife)                     │
│       │                                                          │
│       ▼                                                          │
│  5. Policy Engine: validate_cex_order()                         │
│       │  - Exchange allowed                                      │
│       │  - Symbol allowed                                        │
│       │  - Amount within limits                                  │
│       │                                                          │
│       ▼                                                          │
│  6. Execution Store: Create proposal                            │
│       │  - Generate request_id                                   │
│       │  - Generate confirm_token (single-use)                   │
│       │  - Set TTL (120s)                                        │
│       │                                                          │
│       ▼                                                          │
│  7. Webhook: Notify operator (Discord)                          │
│       │                                                          │
│       ▼                                                          │
│  8. Return to Agent: { approval_required: true, request_id }    │
│       │                                                          │
│       ▼                                                          │
│  9. Operator: Reviews and approves on the dashboard (the MCP    │
│       │   and API servers share EXECUTION_DB_PATH and           │
│       │   EXECUTION_SESSION_ID; see "Approval gate" below)      │
│       ▼                                                          │
│  10. API Server: POST /api/approve-trade                        │
│       │   - Verify confirm_token OR admin session                │
│       │   - Check not expired / not already used                 │
│       │   - Execute order (refusals are not recorded as executed)│
│       │                                                          │
│       ▼                                                          │
│  11. CexExecutor: Place order via CCXT                          │
│       │                                                          │
│       ▼                                                          │
│  12. Audit Log: Record execution                                │
│       │                                                          │
│       ▼                                                          │
│  13. Return: { ok: true, order: {...} }                         │
└─────────────────────────────────────────────────────────────────┘
```

## Approval gate

`EXECUTION_APPROVAL_MODE=approve_each` makes `place_cex_order`/`swap_tokens`/`transfer_eth`
return a proposal (`request_id`, `confirm_token`, `expires_at`) instead of executing
immediately, **only when `PAPER_MODE=false`** — paper orders never propose. The proposal is
held in `ExecutionStore` (`execution_store.py`).

### Confirming a proposal

`POST /api/approve-trade` (`api_server.py`) confirms or rejects one:

- `{"request_id", "confirm_token", "approve": true}` — the normal agent-relayed path. The
  agent gets `confirm_token` back with the proposal and hands it to whoever is approving.
- `{"request_id", "approve": true}` with no `confirm_token` — token-less approval. This is an
  HTTP-admin-only path: it requires an authenticated admin session when
  `API_AUTH_REQUIRED=true`, or `PAPER_MODE=true` when auth is off (live trading without auth is
  already refused by settings validation, so this is a second lock on the same door). No MCP
  tool may call the underlying `ExecutionStore.confirm_as_operator()` — only `api_server.py`
  does.
- Rejecting (`"approve": false`) needs the same authority as approving (a valid
  `confirm_token`, or admin/paper-mode as above) — it permanently consumes the proposal.

While an approved order actually executes, `app.tools.execution.approved_execution()` marks
*only that one call* as approved (a `ContextVar`, not a process-wide flag) — the approval gate
is never switched off for the rest of the process during that window.

### Sharing proposals between the MCP server and the API server

`ExecutionStore` stamps every proposal with a session id and only loads proposals from its own
session. By default the id is random per process, so a restart invalidates every earlier proposal.

The MCP server (`server.py`) and the API server (`api_server.py`) are **separate processes** in
every documented deployment. Start both with the **same** `EXECUTION_DB_PATH` and the **same**
`EXECUTION_SESSION_ID` and they share one session: a proposal the agent creates through the MCP
server appears at `GET /api/pending-approvals` and on the dashboard, and `POST /api/approve-trade`
confirms or rejects it. Change the id (and restart both) to invalidate every open proposal.

With persistence on, the database is the source of truth: confirming or cancelling is one
conditional `UPDATE`, so two processes (or two API workers) cannot both approve one proposal, or
approve one that was cancelled.

Every proposal records the mode it was made in (`paper_mode`). The approval endpoint executes it
only in that mode: an API server in the other mode answers `409` (`EXEC_313`, `mode_mismatch`) and
the proposal stays pending. Executing re-runs the tool, so the live gates, the policy engine and
the Risk Guardian all run again with the account read fresh; a refusal answers `422` with the
tool's error (for example `risk_blocked`) and nothing is recorded as executed.

There is no MCP tool that can confirm a proposal (by design: approval is a human action).

## Deployment Architectures

### Single-Process (Default)

```
┌─────────────────────────────────────────┐
│              Single Container            │
│  ┌─────────────────────────────────┐   │
│  │      ReadyTrader-Crypto         │   │
│  │  ┌───────────┐ ┌───────────┐   │   │
│  │  │ MCP Server│ │ API Server│   │   │
│  │  └───────────┘ └───────────┘   │   │
│  │  ┌───────────────────────────┐ │   │
│  │  │    SQLite (data/*.db)     │ │   │
│  │  └───────────────────────────┘ │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### Horizontally Scaled (with Redis/PostgreSQL)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kubernetes Deployment                         │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  MCP Pod 1   │  │  MCP Pod 2   │  │  MCP Pod 3   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                    │
│         └─────────────────┴────────┬────────┘                    │
│                                    │                             │
│  ┌─────────────────────────────────▼─────────────────────────┐  │
│  │                   Shared Services                          │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐             │  │
│  │  │   Redis   │  │ PostgreSQL│  │  Remote   │             │  │
│  │  │  (Store)  │  │  (Audit)  │  │  Signer   │             │  │
│  │  └───────────┘  └───────────┘  └───────────┘             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Security Model

### Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                        Trust Model                               │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ UNTRUSTED: AI Agent                                      │   │
│  │  - Can request any action                                │   │
│  │  - All requests validated by server                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ TRUSTED: ReadyTrader-Crypto Server                       │   │
│  │  - Owns API keys and signing authority                   │   │
│  │  - Enforces all safety policies                          │   │
│  │  - Controls execution rate and approval                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ SEMI-TRUSTED: External Services                          │   │
│  │  - Exchanges (assume secure, but verify responses)       │   │
│  │  - Blockchains (trustless verification possible)         │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Defense in Depth

| Layer | Protection         | Implementation                            |
| ----- | ------------------ | ----------------------------------------- |
| 1     | Rate Limiting      | Fixed window limiter per key              |
| 2     | Risk Validation    | Position size, loss limits, sentiment     |
| 3     | Policy Enforcement | Allowlists for chains, tokens, exchanges  |
| 4     | Approval Gate      | Two-step execution with single-use tokens |
| 5     | Signer Policy      | Transaction parameter limits              |
| 6     | Audit Trail        | Tamper-evident log with hash chain        |

## API Server Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Server Structure                      │
│                                                                  │
│  Middleware Stack:                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. CORS Middleware                                       │   │
│  │ 2. Rate Limit Middleware                                 │   │
│  │ 3. Authentication (JWT, optional)                        │   │
│  │ 4. Request Tracing (OpenTelemetry, optional)            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Endpoints:                                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Public:                                                  │   │
│  │   GET  /api/health                                       │   │
│  │                                                          │   │
│  │ Authenticated:                                           │   │
│  │   POST /api/auth/login                                   │   │
│  │   GET  /api/auth/me                                      │   │
│  │   GET  /api/portfolio                                    │   │
│  │   GET  /api/pending-approvals                            │   │
│  │   POST /api/approve-trade                                │   │
│  │   GET  /api/metrics                                      │   │
│  │   GET  /api/strategies                                   │   │
│  │   GET  /api/insights                                     │   │
│  │   GET  /api/trades/history                               │   │
│  │                                                          │   │
│  │ Admin:                                                   │   │
│  │   GET  /api/audit/export                                 │   │
│  │                                                          │   │
│  │ WebSocket:                                               │   │
│  │   WS   /ws (real-time ticker updates)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration Reference

See `env.example` for full configuration reference. Key environment variables:

| Category | Variable                  | Default           | Description                     |
| -------- | ------------------------- | ----------------- | ------------------------------- |
| Mode     | `PAPER_MODE`              | `true`            | Paper vs live trading           |
| Safety   | `LIVE_TRADING_ENABLED`    | `false`           | Enable live execution           |
| Safety   | `TRADING_HALTED`          | `true`            | Emergency kill switch           |
| Safety   | `EXECUTION_APPROVAL_MODE` | `auto`            | `auto` or `approve_each`        |
| Signing  | `SIGNER_TYPE`             | `env_private_key` | Signer backend                  |
| Store    | `STORE_BACKEND`           | `memory`          | `memory`, `redis`, `postgresql` |
| Tracing  | `OTEL_ENABLED`            | `false`           | Enable OpenTelemetry            |
