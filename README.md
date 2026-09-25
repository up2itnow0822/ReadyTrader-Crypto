# ReadyTrader-Crypto

[![CI](https://github.com/up2itnow0822/ReadyTrader-Crypto/actions/workflows/ci.yml/badge.svg)](https://github.com/up2itnow0822/ReadyTrader-Crypto/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Important Disclaimer (Read Before Use)

ReadyTrader-Crypto is provided for informational and educational purposes only and does not constitute financial, investment, legal, or tax advice. Trading digital assets involves substantial risk and may result in partial or total loss of funds. Past performance is not indicative of future results. You are solely responsible for any decisions, trades, configurations, supervision, and the security of your keys/credentials. ReadyTrader-Crypto is provided “AS IS”, without warranties of any kind, and we make no guarantees regarding profitability, performance, availability, or outcomes. By using ReadyTrader-Crypto, you acknowledge and accept these risks.

See also: `DISCLAIMER.md`.

## 📍 Status

**Paper-first.** The default configuration is zero-risk paper trading (`PAPER_MODE=true`,
`LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`). Live BTC spot trading is **targeting
production-minus-dust**: fail-closed hardening, a paper UAT pass, and the operator dashboard
have shipped, but the repo does not yet meet its own production-minus-dust gate — graduation
requires the gates in `UAT.md` to close first (PR #9 merged, the sentinel signer fix merged, a
fresh re-verification green on the release SHA, and separate owner authorization for Phase 4).

- Current gate status and test matrix: [`UAT.md`](UAT.md)
- What shipped and what's still open, by PR: [`CHANGELOG.md`](CHANGELOG.md)
- Security posture and known gaps: [`SECURITY.md`](SECURITY.md)
- Latest automated re-verification: [`docs/uat/2026-09-23-reverification.md`](docs/uat/2026-09-23-reverification.md)

______________________________________________________________________

______________________________________________________________________

## 🌎 The Big Picture

**ReadyTrader-Crypto** is a specialized bridge that turns your AI Agent (like Gemini or Claude) into a professional crypto trading operator.

Think of it this way: Your AI agent provides the **Intelligence** (analyzing charts, news, and sentiment), while ReadyTrader-Crypto provides the **Hands** (connecting to exchanges) and the **Safety Brakes** (enforcing your risk rules). It allows you to delegate complex trading tasks to an AI without giving it unchecked access to your funds.

## 🛡️ The Trust Model: Intelligence vs. Execution

The core philosophy of this project is a strict separation of powers:

- **The AI Agent (The Brain):** Decides *what* and *when* to trade. It can research historical data, scan social media, and simulate strategies, but it has no direct power to move money.
- **The MCP Server (The Guardrail):** Owns the API keys and enforces your safety policies. Every order (paper or live) goes through a "Risk Guardian" that rejects a trade that is too large for the account, adds exposure after a loss limit is hit, or buys into extreme bearish sentiment; live orders also pass your allowlists, limits and kill switch.

## 🔄 A Day in the Life of a Trade

1. **Research:** You ask your agent, "Find a good entry for BTC." The agent calls `fetch_ohlcv` and `get_sentiment`.
1. **Proposal:** The agent concludes, "BTC is oversold; I want to buy $100." It calls `place_cex_order` (paper mode by default; live mode requires `LIVE_TRADING_ENABLED=true`).
1. **Governance:** The Risk Guardian runs on the order itself (the same rules `validate_trade_risk` answers with), and live orders also pass the policy engine's allowlists and limits, before anything executes.
1. **Consent:** With `EXECUTION_APPROVAL_MODE=approve_each` in **live** mode, the server returns a proposal (`request_id` + `confirm_token`) instead of executing immediately. You approve or reject it on the dashboard or with `POST /api/approve-trade`; the Risk Guardian and the live gates run again when it executes. Start the MCP server and the API server with the same `EXECUTION_DB_PATH` and `EXECUTION_SESSION_ID` so the API can see the MCP server's proposals ([Approval gate](docs/ARCHITECTURE.md#approval-gate)).

______________________________________________________________________

### 🖥️ Premium Next.js Dashboard

`ReadyTrader-Crypto` includes a professional Next.js dashboard for real-time monitoring, multi-agent coordination, and trade approvals.

**How to Enable:**

1. Navigate to the directory: `cd frontend`
1. Install dependencies: `npm install`
1. Run the development server: `npm run dev`
1. Access it at `http://localhost:3000`.

**Features:**

- **Approvals**: approve or reject each pending proposal (`EXECUTION_APPROVAL_MODE=approve_each`), with the order spelled out; optional Discord or Telegram message when one is waiting (`DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`).
- **Live prices**: a price chart fed by the API's WebSocket ticker stream.
- **History and status**: executed trades, the trading mode (paper/live/unknown), the kill switch and market-data health.
- **Mobile layout**: the same pages at phone width. There are no push notifications.

______________________________________________________________________

## 🚀 Key Features

- **📉 Paper Trading Simulator**: Zero-risk practice with persistent balances. Orders fill at the market price (a limit order only when it is marketable), so paper results mean something.
- **🧠 Strategy Research**: `run_backtest_simulation` runs agent-written strategy code in an isolated sandbox against history; a synthetic stress lab (`examples/stress_test_demo.py`) runs it through hundreds of generated markets.
- **🏦 DEX swaps**: `swap_tokens` through 1inch (live) or at the market rate (paper). Aave V3 and Uniswap V3 helpers exist as a library in `defi/`; they are not exposed as tools.
- **🛡️ Risk Guardian**: Hard-coded safety layer on every order, paper and live: 5% position sizing at the market price and a sentiment Falling Knife rule ([why there is no price rule for crypto](docs/FALLING_KNIFE.md)); on the paper account also daily-loss and drawdown limits (live accounts have no loss history here, so those two do not run live).
- **🤝 Multi-Agent Orchestration**: Support for "Researcher" and "Executor" agent handoffs via a shared **Insight Store**.
- **📰 Intelligence**: X and Reddit sentiment scored locally, NewsAPI and CryptoPanic headlines, free RSS news and the Fear & Greed index. A source without its key answers `not_configured`, never an empty result.

______________________________________________________________________

## ⚡ 10-minute evaluation (Phase 6)

Run both demos locally (no exchange keys, no RPC needed):

```bash
python examples/paper_quick_demo.py
python examples/stress_test_demo.py
```

You’ll get exportable artifacts under `artifacts/demo_stress/` (gitignored).

Prompt pack (copy/paste): `prompts/READYTRADER_PROMPT_PACK.md`.

![ReadyTrader-Crypto demo flow](docs/assets/demo-flow.svg)

## 🛠️ Installation & Setup

### Prerequisites

- Python 3.12+ for the local install and the zero-key quickstart below, **or** Docker for the
  container (Docker Compose optional).

### 1. Build & Run (Standalone)

Run the MCP server in a container. It speaks MCP over stdio, so an MCP client starts it with
`docker run -i` (the configs below do exactly that). The image starts paper-only and halted. The
named volume keeps the paper account, audit log and proposals (`/app/data`) from one session to
the next; without it every session starts from an empty paper wallet.

```bash
cd ReadyTrader-Crypto
docker build -t readytrader-crypto .
# Run interactively (to test): an MCP client would now send it JSON-RPC on stdin
docker run --rm -i -v readytrader-crypto-data:/app/data -e PAPER_MODE=true readytrader-crypto
```

The approval/dashboard API server is a second image: `docker build --target api -t readytrader-crypto:api .`. `docker-compose.yml` runs both (the dashboard too with `--profile with-frontend`) with a shared data
volume and proposal session; it needs `API_JWT_SECRET` and `API_ADMIN_PASSWORD_HASH` in `.env`
(see the top of that file).

### Local development (no Docker)

If you want to run or test ReadyTrader-Crypto locally:

```bash
pip install -r requirements-dev.txt
python app/main.py
```

### 2. Configuration (`.env`)

Create a `.env` file or pass environment variables. Start from `env.example` (copy to `.env`).

<details>
<summary><b>🛡️ Live Trading Safety & Approval</b></summary>

| Variable                  | Default | Description                                                                                                          |
| :------------------------ | :------ | :------------------------------------------------------------------------------------------------------------------- |
| `PAPER_MODE`              | `true`  | Set to `false` for live trading.                                                                                     |
| `LIVE_TRADING_ENABLED`    | `false` | Must be `true` for any live execution.                                                                               |
| `TRADING_HALTED`          | `true`  | Kill switch: refuses new live orders, swaps and transfers (reads and cancels still work). Set `false` to trade live. |
| `EXECUTION_APPROVAL_MODE` | `auto`  | `auto` executes immediately; `approve_each` requires manual confirmation.                                            |
| `API_PORT`                | `8000`  | Port for the FastAPI/WebSocket server (`api_server.py`).                                                             |
| `DISCORD_WEBHOOK_URL`     | `""`    | Optional webhook for trade approval notifications.                                                                   |

</details>

<details>
<summary><b>🔑 Exchange & Signing Credentials</b></summary>

| Variable              | Description                                                     |
| :-------------------- | :-------------------------------------------------------------- |
| `PRIVATE_KEY`         | Hex private key for signing (if `SIGNER_TYPE=env_private_key`). |
| `CEX_API_KEY`         | API Key for your primary exchange.                              |
| `CEX_API_SECRET`      | API Secret for your primary exchange.                           |
| `SIGNER_TYPE`         | `env_private_key`, `keystore`, or `remote`.                     |
| `CEX_BINANCE_API_KEY` | Exchange-specific keys (e.g., `CEX_BINANCE_...`).               |

</details>

<details>
<summary><b>📈 Market Data & CCXT Tuning</b></summary>

| Variable               | Default      | Description                                        |
| :--------------------- | :----------- | :------------------------------------------------- |
| `MARKETDATA_EXCHANGES` | `binance...` | Comma-separated list of exchanges to use for data. |
| `TICKER_CACHE_TTL_SEC` | `5`          | How long to cache price data.                      |
| `DEX_SLIPPAGE_PCT`     | `1.0`        | Default slippage for DEX swaps.                    |
| `ALLOW_TOKENS`         | `*`          | Comma-separated allowlist of tradeable tokens.     |

</details>

<details>
<summary><b>🛠️ Ops, Observability & Limits</b></summary>

| Variable                     | Default        | Description                                                                                                                              |
| :--------------------------- | :------------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| `RATE_LIMIT_DEFAULT_PER_MIN` | `120`          | Default API rate limit.                                                                                                                  |
| `RISK_PROFILE`               | `conservative` | Reserved, not applied: the Risk Guardian's limits are fixed (5% position, 5% daily loss, 10% drawdown, -0.5 sentiment) whatever it says. |
| `ALLOW_CHAINS`               | `ethereum...`  | Allowlists for EVM networks.                                                                                                             |

</details>

______________________________________________________________________

#### CEX credentials (Phase 3)

To place CEX orders or fetch CEX balances, configure ccxt credentials via env.

Generic (applies to the default exchange you pass to the tool):

- `CEX_API_KEY=...`
- `CEX_API_SECRET=...`
- `CEX_API_PASSWORD=...` (optional; some exchanges)

Or per-exchange (preferred):

- `CEX_BINANCE_API_KEY=...`
- `CEX_BINANCE_API_SECRET=...`
- `CEX_BINANCE_API_PASSWORD=...` (optional)

Tools:

- `place_cex_order(symbol, side, amount, order_type='market', price=None, exchange='binance', market_type='spot', idempotency_key='')`
- `get_cex_balance(exchange='binance', market_type='spot')`
- `get_cex_order(order_id, symbol='', exchange='binance', market_type='spot')`
- `cancel_cex_order(order_id, symbol='', exchange='binance', market_type='spot')`
- `get_cex_capabilities(exchange='binance', symbol='', market_type='spot')`
- `list_cex_open_orders(exchange='binance', symbol='', market_type='spot', limit=100)`
- `list_cex_orders(exchange='binance', symbol='', market_type='spot', limit=100)`
- `get_cex_my_trades(exchange='binance', symbol='', market_type='spot', limit=100)`
- `cancel_all_cex_orders(exchange='binance', symbol='', market_type='spot')`
- `replace_cex_order(exchange, order_id, symbol, side, amount, order_type='limit', price=None, market_type='spot')`
- `wait_for_cex_order(exchange, order_id, symbol='', market_type='spot', timeout_sec=30, poll_interval_sec=2.0)`

Exchange/market introspection:

- `get_cex_capabilities(exchange='binance', symbol='', market_type='spot')` — the MCP tool agents
  call. (`ExchangeProvider.get_marketdata_capabilities()` is the internal Python method behind
  it; it is not itself an MCP tool.)

______________________________________________________________________

## ⚡ Zero-key quickstart (paper)

No exchange keys, no RPC endpoint. Clone, install into a venv, then add ONE of the config
blocks below to your MCP client.

```bash
git clone https://github.com/up2itnow0822/ReadyTrader-Crypto.git
cd ReadyTrader-Crypto
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Replace `/ABSOLUTE/PATH/TO/ReadyTrader-Crypto` below with the absolute path to that clone.
Every block pins the same safe paper profile: `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`,
`TRADING_HALTED=true`, `EXECUTION_MODE=cex`, `SIGNER_TYPE=null`. All four were launched over
stdio with exactly this command + args + env (see `discovery/m3/mcp_smoke_*.txt` in the
build's evidence) and returned the full 29-tool list.

<details>
<summary><b>Claude Desktop</b> (<code>claude_desktop_config.json</code>)</summary>

```json
{
  "mcpServers": {
    "readytrader-crypto": {
      "command": "/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/server.py"],
      "env": {
        "PAPER_MODE": "true",
        "LIVE_TRADING_ENABLED": "false",
        "TRADING_HALTED": "true",
        "EXECUTION_MODE": "cex",
        "SIGNER_TYPE": "null"
      }
    }
  }
}
```

</details>

<details>
<summary><b>Claude Code</b> (<code>claude mcp add</code>)</summary>

```bash
claude mcp add readytrader-crypto \
  -e PAPER_MODE=true \
  -e LIVE_TRADING_ENABLED=false \
  -e TRADING_HALTED=true \
  -e EXECUTION_MODE=cex \
  -e SIGNER_TYPE=null \
  -- /ABSOLUTE/PATH/TO/ReadyTrader-Crypto/.venv/bin/python /ABSOLUTE/PATH/TO/ReadyTrader-Crypto/server.py
```

</details>

<details>
<summary><b>Cursor</b> (<code>.cursor/mcp.json</code>)</summary>

```json
{
  "mcpServers": {
    "readytrader-crypto": {
      "command": "/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/server.py"],
      "env": {
        "PAPER_MODE": "true",
        "LIVE_TRADING_ENABLED": "false",
        "TRADING_HALTED": "true",
        "EXECUTION_MODE": "cex",
        "SIGNER_TYPE": "null"
      }
    }
  }
}
```

</details>

<details>
<summary><b>VS Code</b> (<code>.vscode/mcp.json</code>)</summary>

```json
{
  "servers": {
    "readytrader-crypto": {
      "type": "stdio",
      "command": "/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/ReadyTrader-Crypto/server.py"],
      "env": {
        "PAPER_MODE": "true",
        "LIVE_TRADING_ENABLED": "false",
        "TRADING_HALTED": "true",
        "EXECUTION_MODE": "cex",
        "SIGNER_TYPE": "null"
      }
    }
  }
}
```

</details>

### Startup scenarios

Three copy-paste env profiles. Pick one; do not mix them.

| Profile                     | Env                                                                                                                                                                                           | Use when                                                                                                                                                                                                                              |
| :-------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Market-data only**        | `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`, `SIGNER_TYPE=null` (no `deposit_paper_funds` needed)                                                                  | You only want price/news/sentiment/backtest tools — no wallet, no orders.                                                                                                                                                             |
| **Paper trading (default)** | `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`, `EXECUTION_MODE=cex`, `SIGNER_TYPE=null`                                                                              | Everyday development and the quickstart above — full paper order lifecycle, zero real risk.                                                                                                                                           |
| **Live-but-halted**         | `PAPER_MODE=false`, `LIVE_TRADING_ENABLED=true`, `TRADING_HALTED=true`, `EXECUTION_MODE=cex`, allowlists set, `SIGNER_TYPE` set to `remote`/`keystore`/`cb_mpc_2pc` (never `env_private_key`) | What you set up and validate **before ever** flipping `TRADING_HALTED=false`. Follow `docs/LIVE_TESTING_PROTOCOL.md` and `docs/OPS_BTC_PRODUCTION.md` — there is no one-step "go live" recipe, and this README does not give you one. |

### Try it: example prompts

Paste into your agent once connected (paper mode). Also see the full
`prompts/READYTRADER_PROMPT_PACK.md` for more.

1. "Deposit 10,000 USDC into my paper wallet, then get the current BTC/USDT price." →
   `deposit_paper_funds`, `fetch_ohlcv` or `get_crypto_price`.
1. "Check social sentiment for ETH, then tell me if the Risk Guardian would allow a $500
   ETH buy against a $10,000 portfolio." → `get_social_sentiment`, `validate_trade_risk`.
1. "Try to validate a BTC buy sized at 50% of a $10,000 portfolio — I want to see it get
   blocked." → `validate_trade_risk` refusing on position size (verified: this call returns
   `result.allowed: false`).
1. "Buy 0.05 ETH/USDT in paper at the market, then show me my paper balances." →
   `place_cex_order` (market order: it fills at the current price), `get_cex_balance`.
1. "Backtest a simple RSI mean-reversion strategy (buy under 30, sell over 70) on BTC/USDT and
   report PnL." → `run_backtest_simulation` (verified end-to-end through `BacktestEngine` with
   this exact strategy shape — see `docs/STRATEGY_SANDBOX.md` for the contract).

### Troubleshooting

| Symptom                                                                                       | Likely cause                                                                                                                                                     | Fix                                                                                                                                                                                                                                                              |
| :-------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Server doesn't appear in the client                                                           | Relative paths, or a `python` that lacks the deps                                                                                                                | Use absolute paths for both `command` and the `server.py` arg, and point at the venv's `python` (`.venv/bin/python`), not a bare `python`/`python3`.                                                                                                             |
| `paper_price_required`                                                                        | No market price for the symbol: paper orders and swaps fill at the market price                                                                                  | Call `get_crypto_price` to confirm data is flowing for that symbol (see "Exchange/network errors" below).                                                                                                                                                        |
| `limit_not_marketable`                                                                        | A paper limit BUY below the market (or SELL above it): it would rest on the book, and paper mode does not simulate resting orders                                | Use a market order, or a limit at or through the market.                                                                                                                                                                                                         |
| `risk_blocked`                                                                                | The Risk Guardian refused the order; the message says which rule (size over 5% of the account, a loss limit, bearish sentiment, or an account it could not read) | Reduce the size, or read `error.data.risk` for the numbers it used.                                                                                                                                                                                              |
| `insufficient_funds`                                                                          | No paper balance for the asset being spent                                                                                                                       | Call `deposit_paper_funds` first.                                                                                                                                                                                                                                |
| `execution_mode_blocked`                                                                      | `EXECUTION_MODE` doesn't allow the venue you're calling (`cex`/`dex`/`hybrid`)                                                                                   | Set `EXECUTION_MODE` to the venue you need.                                                                                                                                                                                                                      |
| Exchange/network errors (`cex_error`, `fetch_price_error`, `NET_501`) in a restricted network | Outbound access to the exchange is blocked (firewalled sandbox, corporate proxy)                                                                                 | Confirm outbound HTTPS to the exchange is allowed; this is environmental, not a bug — the server itself starts and lists tools fine (verified: all four quickstart configs above listed 29 tools while this exact network error occurred on `get_crypto_price`). |
| Strategy rejected (`error_kind: "forbidden"` or `"compile"`)                                  | Strategy code imports something other than `math`, uses an underscore-prefixed name, or has a syntax error                                                       | Read `docs/STRATEGY_SANDBOX.md`; no `pandas`/`ta`/`string`/`random`, no `_private` names.                                                                                                                                                                        |
| API refuses to start with `DEV_MODE=false`                                                    | `api_server.py` fails closed: needs `API_AUTH_REQUIRED=true` + `API_JWT_SECRET`, and non-wildcard CORS, once `DEV_MODE=false`                                    | Set those, or keep `DEV_MODE=true` for local HTTP API work (the MCP stdio path above doesn't need the API server at all).                                                                                                                                        |
| Approvals never show up in the dashboard                                                      | The MCP server and the API server are separate processes; each has its own proposal session unless both are given the same one                                   | Start both with the same `EXECUTION_DB_PATH` and `EXECUTION_SESSION_ID` (see `docs/ARCHITECTURE.md#approval-gate`).                                                                                                                                              |

______________________________________________________________________

## 🔌 Integration Guide

### Option A: Agent Zero (Recommended)

To give Agent Zero these powers, add the following to your **Agent Zero Settings** (or `agent.yaml`).
The MCP server key/name is arbitrary; we use `readytrader_crypto` in examples.

Quick copy/paste file: `configs/agent_zero.mcp.yaml`.

**Via User Interface:**

1. Go to **Settings** -> **MCP Servers**.
1. Add a new server:
   - **Name**: `readytrader_crypto`
   - **Type**: `stdio`
   - **Command**: `docker`
   - **Args**: `run`, `-i`, `--rm`, `-e`, `PAPER_MODE=true`, `readytrader-crypto`

**Via `agent.yaml`:**

```yaml
mcp_servers:
  readytrader_crypto:
    command: "docker"
    args: 
      - "run"
      - "-i" 
      - "--rm"
      - "-e"
      - "PAPER_MODE=true"
      - "readytrader-crypto"
```

Prebuilt config: `configs/agent_zero.mcp.yaml`.
*Restart Agent Zero after saving.*

### Option B: Generic MCP Client (Claude Desktop, etc.)

Add this to your `mcp-server-config.json`:

Quick copy/paste file: `configs/claude_desktop.mcp-server-config.json`.

```json
{
  "mcpServers": {
    "readytrader_crypto": {
      "command": "docker",
      "args": [
        "run", 
        "-i", 
        "--rm", 
        "-e", "PAPER_MODE=true", 
        "readytrader-crypto"
      ]
    }
  }
}
```

Prebuilt config: `configs/claude_desktop.mcp-server-config.json`.

______________________________________________________________________

## 📚 Feature Guide

### 1. The Strategy Builder (Backtesting)

Your agent can "research" before it trades. Ask it to **develop and test** a strategy.

**Example Prompt:**

> "Create a mean-reversion strategy for BTC/USDT. Write a Python function `on_candle` that uses RSI. Run a backtest simulation on the last 500 hours and tell me the Win Rate and PnL."

**What happens:**

1. Agent calls `fetch_ohlcv("BTC/USDT")` to see data structure.
1. Agent writes code for `on_candle(close, rsi, state)`.
1. Agent calls `run_backtest_simulation(code, "BTC/USDT")`.
1. Server runs the code in a sandbox and returns `{ "pnl": 15.5%, "win_rate": 60% }`.

### 2. Paper Trading Laboratory

Perfect for "interning" your agent. The real paper workflow, tool by tool:

- **Deposit Funds**: `deposit_paper_funds("USDC", 10000)`
- **Get a price**: `fetch_ohlcv("ETH/USDT", "1h", 1)` (numeric `close`) or `get_crypto_price("ETH/USDT")`
- **Place an order**: `place_cex_order("ETH/USDT", "buy", 1.0)` — paper mode routes to the paper
  engine and needs no exchange credentials. It fills at the market price from the market-data bus
  (`paper_price_required` when there is none). A limit order fills, at the market, only when it is
  marketable (`limit_not_marketable` otherwise). The Risk Guardian checks it first against the
  paper account (`risk_blocked` with the reason).
- **Check balances**: `get_cex_balance()` — in paper mode this returns the paper wallet, no
  credentials required.

### 3. Market Regime & Risk

The agent can query the "weather" before flying.

- **Tool**: `get_market_regime("BTC/USDT")`
- **Output**: `{"regime": "TRENDING", "direction": "UP", "adx": 45.2}`
- **Agent Logic**: "The market is Trending Up (ADX > 25). I will switch to my Trend-Following Strategy and disable Mean-Reversion."

**The Guardian (Passive Safety):**
You don't need to do anything. If the agent tries to bet 50% of the portfolio on a whim, the order
itself is refused (`risk_blocked`); `validate_trade_risk` lets the agent ask first.

______________________________________________________________________

## 🧰 Tool Reference

ReadyTrader-Crypto registers **29 MCP tools** (`server.py` + `app/tools/*.py`). The complete
catalog, with parameters, examples and error codes, is `docs/TOOLS.md` (curated; a test,
`tests/test_docs_tool_roster.py`, fails the build if this README or `docs/TOOLS.md` names a tool
the server does not register, or misses one it does). `python tools/generate_tool_docs.py` prints
the live registry (names, signatures and the descriptions agents see). A representative slice:

| Category         | Tool                      | Description                                                    |
| :---------------- | :------------------------ | :------------------------------------------------------------ |
| **Market Data**  | `get_crypto_price`        | Live price from the market-data bus.                          |
|                  | `fetch_ohlcv`             | Historical candles (numeric OHLCV) for research.              |
|                  | `get_market_regime`       | Trend/chop detection (ADX-based).                             |
| **Intelligence** | `get_sentiment`           | Crypto Fear & Greed Index.                                    |
|                  | `get_social_sentiment`    | X/Reddit text scored -1..+1; feeds the Falling Knife check.   |
|                  | `get_financial_news`      | NewsAPI headlines for a symbol (needs a NewsAPI key).         |
| **Trading**      | `swap_tokens`             | DEX swap (paper or live).                                     |
|                  | `place_cex_order`         | CEX order — paper mode by default, no credentials required.   |
|                  | `get_cex_balance`         | Account balance (paper wallet, or the real exchange balance). |
| **Risk & Paper** | `deposit_paper_funds`     | Seed the paper wallet.                                        |
|                  | `validate_trade_risk`     | Ask the Risk Guardian first (the same rules run on orders).   |
| **Research**     | `run_backtest_simulation` | Run a strategy through the isolated sandbox against history.  |

______________________________________________________________________

*Built for the Agentic Future.*

## 🧪 Synthetic Stress Testing (Phase 5)

This repo includes a **100% randomized (but deterministic-by-seed)** synthetic market simulator. It can generate trending, ranging, and volatile regimes and inject **black swan crashes** and **parabolic blow-off tops**.

`stress_test_engine.run_synthetic_stress_test(strategy_code, config)` is a **Python function**,
not an MCP tool — there is no agent-callable stress-test tool today. Run it locally:

```bash
python examples/stress_test_demo.py
```

That script imports `run_synthetic_stress_test` directly and writes its artifacts under
`artifacts/demo_stress/`. To validate a strategy through the MCP surface instead, use the
`run_backtest_simulation` tool (single historical run, not the stress lab's many synthetic
scenarios).

Returns JSON containing:

- **metrics summary** across scenarios
- **replay seeds** (master + per-scenario)
- **artifacts**: CSV scenario metrics, plus worst-case equity curve CSV + trades JSON
- **recommendations**: suggested parameter changes (and applies to `PARAMS` keys if present)

Example `config_json`:

```json
{
  "master_seed": 123,
  "scenarios": 200,
  "length": 500,
  "timeframe": "1h",
  "initial_capital": 10000,
  "start_price": 100,
  "base_vol": 0.01,
  "black_swan_prob": 0.02,
  "parabolic_prob": 0.02
}
```

______________________________________________________________________

## ✅ Production Readiness & Quality Assurance

ReadyTrader-Crypto maintains rigorous quality standards through comprehensive automated testing, security scanning, and operational safeguard verification.

### Test Suites

`pytest` collects about 680 tests: unit tests for every tool, the paper ledger, the Risk Guardian
and the policy engine; integration flows under `tests/integration/` (the exchange-sandbox tests
there call public Kraken/Coinbase endpoints); and one regression test per UAT finding. The
dashboard has its own unit tests (`cd frontend && npm test`) and an 18-journey Playwright suite
against the real API server (`cd frontend && npm run e2e`).

### Quality Gates

`.github/workflows/ci.yml` runs on every push and PR to `main`. It installs the exact pinned
set (`pip install --no-deps -r requirements.lock.txt` followed by `pip check`), installs the
frontend with `npm ci`, then runs `make check`, `make security`, and
`pip-audit -r requirements.lock.txt`. So the first six rows below are enforced on every PR, not
only locally; the remaining scans run on a schedule or on release:

| Check                | Command                                 | Purpose                                                          | Where it runs today                                                    |
| :------------------- | :-------------------------------------- | :----------------------------------------------------------------| :--------------------------------------------------------------------- |
| **Lint**             | `ruff check`                            | Code quality, unused imports, style                              | CI on every push/PR + local (`make check`)                             |
| **Format**           | `ruff format`                           | Consistent code formatting                                       | CI on every push/PR + local (`make check`)                             |
| **Tests**            | `pytest`                                | Unit + integration suite                                         | CI on every push/PR + local (`make check`)                             |
| **Docs truth**       | `pytest tests/test_docs_tool_roster.py` | No phantom tool references; `docs/TOOLS.md` matches the registry | CI on every push/PR + local (`make check`)                             |
| **Security Scan**    | `bandit`                                | Python security vulnerabilities                                  | CI on every push/PR (`make security`) + daily (`security-audit.yml`)   |
| **Dependency Audit** | `pip-audit` + `npm audit`               | Known CVEs in Python and frontend (including `devDependencies`)  | CI on every push/PR (`make security`) + daily (`security-audit.yml`)   |
| **Secret Scan**      | `trufflehog`                            | Prevent credential leaks                                         | CI daily/manual (`security-audit.yml`)                                 |
| **Container Scan**   | `trivy`                                 | Docker image vulnerabilities                                     | CI daily/manual (`security-audit.yml`); CI on tag push (`release.yml`) |
| **CodeQL**           | GitHub                                  | SAST for Python & JavaScript                                     | CI daily/manual (`security-audit.yml`)                                 |
| **Frontend Lint**    | `eslint`                                | TypeScript/React best practices                                  | CI on every push/PR (`make check`) + local                             |
| **Docs Format**      | `mdformat`                              | Consistent documentation                                         | CI on every push/PR + local (`make check`)                             |

There is no `mypy` gate anywhere in this repo (`pyproject.toml` carries an unused `[tool.mypy]`
config block, but no Makefile target or workflow invokes it).

### Operational Safeguards (Verified by Tests)

These safety mechanisms are continuously verified:

| Safeguard              | Threshold        | Behavior                                                        |
| :---------------------- | :---------------- | :---------------------------------------------------------------|
| **Kill Switch**        | `TRADING_HALTED` | Refuses every new live order; reads and cancels still work      |
| **Max Drawdown**       | 10% from peak    | Blocks new exposure (paper account; deposits do not clear it)   |
| **Daily Loss Limit**   | 5% daily loss    | Blocks new exposure today (paper account)                       |
| **Position Sizing**    | 5% per trade     | Rejects oversized orders                                         |
| **Falling Knife**      | -0.5 sentiment   | Blocks BUYs (no price rule for crypto: `docs/FALLING_KNIFE.md`) |
| **Chain Allowlist**    | Configurable     | Only approved networks                                           |
| **Token Allowlist**    | Configurable     | Only approved assets                                              |
| **Exchange Allowlist** | Configurable     | Only approved venues                                              |
| **Signing Limits**     | Configurable     | Max value, gas, data size                                        |

### GitHub Actions Workflows

| Workflow            | File                                    | Trigger          | Purpose                                                                           |
| :-------------------- | :----------------------------------------| :------------------| :----------------------------------------------------------------------------------|
| **CI**              | `.github/workflows/ci.yml`              | Push/PR          | Locked-deps check, `make check`, `make security` (bandit, pip-audit, `npm audit`) |
| **Live-Path Tests** | `.github/workflows/live-path-tests.yml` | Manual dispatch  | Exchange sandbox testing                                                          |
| **Security Audit**  | `.github/workflows/security-audit.yml`  | Daily + manual   | pip-audit, bandit, trufflehog, trivy, CodeQL, SBOM                                |
| **Release**         | `.github/workflows/release.yml`         | Tag push, manual | Version validation, trivy container scan on release                               |

### Running Tests Locally

```bash
# Full test suite
pytest

# With coverage
pytest --cov=. --cov-report=term-missing

# Integration tests only
pytest tests/integration/ -v

# Operational safeguards
pytest tests/integration/test_operational_safeguards.py -v

# Quality gates
ruff check . && ruff format --check . && bandit -q -r . -c bandit.yaml
```

### Security Documentation

| Document                  | Purpose                        |
| :------------------------ | :----------------------------- |
| `SECURITY.md`             | Vulnerability reporting policy |
| `docs/THREAT_MODEL.md`    | Live trading threat analysis   |
| `docs/CUSTODY.md`         | Key management & rotation      |
| `docs/SECURITY_REVIEW.md` | Pre-production checklist       |

______________________________________________________________________

## 📌 Project docs

- `docs/README.md`: docs index / navigation
- `docs/TOOLS.md`: complete tool catalog (curated; the roster is checked against the server)
- `docs/FALLING_KNIFE.md`: the Risk Guardian's Falling Knife rule, and why crypto has no price rule
- `docs/STRATEGY_SANDBOX.md`: strategy contract, isolation layers, and limits for `run_backtest_simulation`
- `docs/ERRORS.md`: common error codes and operator troubleshooting
- `docs/EXCHANGES.md`: exchange capability matrix (Supported vs Experimental)
- `docs/MARKETDATA.md`: market data routing, freshness scoring, plugins, and guardrails
- `docs/THREAT_MODEL.md`: operator-focused threat model (live trading)
- `docs/CUSTODY.md`: key custody + rotation guidance
- `docs/SECURITY_REVIEW.md`: pre-production security checklist
- `docs/POSITIONING.md`: credibility-safe marketing + messaging
- `RELEASE_READINESS_CHECKLIST.md`: what must be green before distribution
- `CHANGELOG.md`: version-to-version change summary
