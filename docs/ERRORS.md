### 🚨 Quick Fix Troubleshooting

If you are just getting started and seeing errors, check these first:

| Issue             | Quick Fix                                                                 | Reference                                |
| :---------------- | :------------------------------------------------------------------------ | :--------------------------------------- |
| **Missing .env**  | Run `python tools/setup_wizard.py` to generate one.                       | [Setup Wizard](../tools/setup_wizard.py) |
| **Missing Keys**  | Check `docs/SENTIMENT.md` for links to get free API keys.                 | [Sentiment Guide](SENTIMENT.md)          |
| **Blocked Trade** | Read the error `code`; `risk_blocked` carries the Risk Guardian's reason. | [Risk](#risk-guardian)                   |
| **Python Errors** | Run `pip install -r requirements.txt` to ensure dependencies are met.     | [requirements.txt](../requirements.txt)  |

______________________________________________________________________

### ReadyTrader-Crypto Error Codes (Operator Guide)

Every MCP tool returns one JSON envelope shape (`app/core/jsonio.py`):

```json
{"ok": true, "data": {...}}
{"ok": false, "error": {"code": "...", "message": "...", "data": {...}}}
```

The codes below are the `error.code` values the tools actually return today (verified against
`app/tools/*.py` and `paper_engine.py`), plus the numbered HTTP error codes the approval API
(`api_server.py`) returns. If a code you are seeing is not listed here, treat the `message`
field as authoritative and check server logs (`event=tool_error` per `RUNBOOK.md`).

### Risk Guardian

- **`risk_blocked`**
  - Meaning: the Risk Guardian refused the order (`place_cex_order`, `swap_tokens`,
    `replace_cex_order`, or an approved proposal). The message is the rule: the part of the order
    that adds exposure, valued at the market price, is over 5% of the account's value; the paper
    account is 10% below its best result or lost 5% today (only orders that reduce exposure pass;
    deposits are not gains and do not end a halt; live orders list these two in `inactive_rules`);
    measured sentiment is below -0.5 (a BUY); or the order adds exposure and there is no market
    price, it could not be valued, or the account could not be read (fail closed). `error.data.risk`
    has the numbers it used (`reference_price`, `market_price`, `equity_usd`, `exposure_added_usd`,
    `acquired_quote_usd`, `position_units`, `sentiment`, `inactive_rules`).
  - Fix: reduce the size, wait for the loss limit to clear, or fix what could not be read (market
    data, exchange keys, RPC). On a spot account, selling what you hold into cash (a USD stablecoin
    or fiat quote) is never refused by the size, loss or sentiment rules; selling into a crypto quote
    (ETH/BTC) buys that asset and is sized (and checked against its sentiment). On a futures/swap
    account the position cannot be read, so a closing order is sized like any other: close in
    steps or on the exchange. There is no price-based Falling Knife rule for crypto:
    `docs/FALLING_KNIFE.md`.
- **`invalid_request`** (`validate_trade_risk`)
  - Meaning: `side` is not buy/sell, or `amount_usd` / `portfolio_value` is not a positive number.

### Execution tool errors (MCP)

- **Argument validation** (before any tool runs)
  - Meaning: an argument of the wrong type (text that is not a number, or `true`/`false` for an
    amount, price, limit, value or score) is refused by the MCP argument validation; the client
    gets a tool error naming the argument (`true` used to be taken as 1).
- **`paper_engine_missing`**
  - Meaning: `PAPER_MODE=true` but the paper engine failed to initialize.
  - Fix: check `data/paper.db` is writable; restart the process.
- **`paper_mode_not_supported`**
  - Meaning: the tool works on a live exchange account or chain: `transfer_eth`, the private-WS
    tools, and the exchange-order tools (`get_cex_order`, `cancel_cex_order`,
    `cancel_all_cex_orders`, `list_cex_open_orders`, `list_cex_orders`, `get_cex_my_trades`,
    `replace_cex_order`, `wait_for_cex_order`). Paper orders fill immediately and never rest on an
    exchange; paper mode never reaches an exchange account. `get_cex_balance` shows the paper wallet.
  - Fix: these only work when `PAPER_MODE=false` and live execution is allowed.
- **`paper_price_required`**
  - Meaning: paper orders and swaps fill at the market price, and the market-data bus has no usable
    price for the symbol (for a swap: no FROM/TO, TO/FROM or USDT route).
  - Fix: call `get_crypto_price` to confirm data is flowing for that symbol; see the market data
    section below.
- **`limit_not_marketable`**
  - Meaning: a paper limit BUY below the market (or SELL above it). It would rest on the book, and
    paper mode does not simulate resting orders. `data` has `limit_price` and `market_price`.
  - Fix: use a market order, or a limit at or through the market (it fills at the market price).
- **`invalid_side`**, **`invalid_order_type`**, **`invalid_amount`**
  - Meaning: `place_cex_order` / `swap_tokens` got a side other than buy/sell, an order type other
    than market/limit, or a non-positive amount.
- **`approval_required`**
  - Meaning: `replace_cex_order` with `EXECUTION_APPROVAL_MODE=approve_each`. A replacement is a new
    order, and it cannot be proposed.
  - Fix: `cancel_cex_order`, then `place_cex_order` (which returns a proposal).
- **`live_trading_disabled`**, **`trading_halted`**
  - Meaning: live execution refused by `LIVE_TRADING_ENABLED` (not `true`) or the kill switch
    `TRADING_HALTED`.
- **`execution_mode_blocked`**
  - Meaning: The requested tool is blocked by `EXECUTION_MODE` (`dex`/`cex`/`hybrid`) for that venue.
  - Fix: set `EXECUTION_MODE` to allow the venue you want, or use the corresponding venue tool.
- **`invalid_price`**
  - Meaning: `place_cex_order` was given a non-positive or non-numeric `price`, or a limit order
    without one.
  - Fix: pass a positive price for a limit order; a market order needs none.
- **`timeout`**
  - Meaning: `wait_for_cex_order` did not see a terminal order state within `timeout_sec`.
  - Fix: poll again with `get_cex_order`, or raise `timeout_sec`.
- **`cex_error`**, **`execution_error`**, **`transfer_error`**
  - Meaning: an unexpected exchange/RPC/signing failure. The message is a fixed string ("Exchange
    operation failed."); the exception is in the server's process log. The operator's own switches
    and policy never answer with these: they have their own codes (above and below).
  - Fix: check the server log for the underlying exception and the exchange's or RPC's status.
- **`rate_limited`**
  - Meaning: the HTTP API's rate limit (`RATE_LIMIT_DEFAULT_PER_MIN`, per client) was exceeded for
    the current 60 s window. MCP tools are not rate-limited.
  - Fix: slow down, or raise `RATE_LIMIT_DEFAULT_PER_MIN`.

### Policy engine (allowlists / limits, live orders only)

`ALLOW_CHAINS`, `ALLOW_TOKENS`, `ALLOW_EXCHANGES`, `ALLOW_CEX_SYMBOLS`, `ALLOW_CEX_MARKET_TYPES`,
`ALLOW_ROUTERS` and the `MAX_*` limits are enforced by `policy_engine.py` on the **live** order
path only (`place_cex_order`, `replace_cex_order`, `swap_tokens` and `transfer_eth`); paper orders
are not filtered by them. A violation answers with the rule's own code and its limit in `data`:
`exchange_not_allowed`, `symbol_not_allowed`, `market_type_not_allowed`, `chain_not_allowed`,
`token_not_allowed`, `order_amount_too_large`, `trade_amount_too_large`, and the other codes in
`policy_engine.py`.

### Paper ledger errors (`paper_engine.py`)

`deposit_paper_funds`, and the paper branches of `place_cex_order`/`swap_tokens`, share one
order/deposit validator. On success, `place_cex_order`/`swap_tokens` return a numeric `fill`
block (`side`, `symbol`, `amount`, `price`, `total_value`, `quote`); on refusal, the code is one
of:

- **`invalid_symbol`** — symbol is not `BASE/QUOTE`, or names the same asset twice.
- **`invalid_side`** — side is not `buy` or `sell`.
- **`invalid_amount`** — amount/price/order value is not a positive finite number, exceeds the
  ledger's per-call cap (1e12), would push a balance past the ledger's cap (1e15), or is too
  small relative to the balance to be recorded exactly in a float64.
- **`invalid_price`** — price is not a positive finite number, or exceeds the per-call cap (1e12).
- **`insufficient_funds`** — the account does not hold enough of the asset being spent.
  - Fix: call `deposit_paper_funds` first, or reduce the order size.

### Approval API errors (HTTP — `POST /api/approve-trade`)

These are the numbered `ReadyTraderError` codes (`errors.py`) the approval endpoint returns.
No MCP tool raises these; they only appear in HTTP responses. See
`docs/ARCHITECTURE.md#approval-gate` for the full approval flow.

| Code       | HTTP status | Meaning                                                                                                                                                                                     | Fix                                                                                         |
| :--------- | :---------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------ |
| `AUTH_604` | 403         | Caller may not approve/reject this proposal (no admin session and no/wrong `confirm_token`).                                                                                                | Sign in as an admin, or supply the proposal's `confirm_token`.                              |
| `EXEC_308` | 409         | Proposal was already executed.                                                                                                                                                              | Nothing further happens; propose a new trade if needed.                                     |
| `EXEC_309` | 404         | Proposal does not exist **in this server's proposal session**.                                                                                                                              | Start the MCP and API servers with the same `EXECUTION_DB_PATH` and `EXECUTION_SESSION_ID`. |
| `EXEC_310` | 410         | Proposal expired (proposals have a short TTL by design).                                                                                                                                    | Ask the agent to propose again.                                                             |
| `EXEC_311` | 409         | Proposal was cancelled/rejected earlier, or already confirmed (approvals are single-use).                                                                                                   | Propose again if a new trade is wanted.                                                     |
| `EXEC_312` | 422         | Proposal payload is malformed/incomplete. (When the order itself is refused at execution — e.g. `risk_blocked` — the 422 carries that tool error instead; nothing is recorded as executed.) | Ask the agent to propose again with a valid payload.                                        |
| `EXEC_313` | 409         | The proposal was made in the other mode (paper/live) than this API server runs in; nothing executed and the proposal stays pending.                                                         | Approve it from an API server running in the proposal's mode.                               |

### Market data guardrails

- **`fetch_price_error`** (from `get_crypto_price`), **`fetch_ohlcv_error`** (from `fetch_ohlcv`)
  - Meaning: the underlying fetch failed. If `MARKETDATA_FAIL_CLOSED=true`, this also fires when
    the best available ticker is stale or flagged as an outlier — the message text starts with
    `marketdata_not_acceptable` in that case (`marketdata/bus.py`).
  - Fix:
    - check `GET /api/marketdata/status` (HTTP) for per-provider candidates/health
    - tune thresholds: `MARKETDATA_MAX_AGE_MS*`, `MARKETDATA_OUTLIER_MAX_PCT`, `MARKETDATA_OUTLIER_WINDOW_MS`
    - disable fail-closed: `MARKETDATA_FAIL_CLOSED=false`
- **`market_regime_error`** (from `get_market_regime`)
  - Meaning: regime detection failed (usually the same underlying OHLCV fetch problem above).

### News and sentiment sources

- **`not_configured`** (`get_financial_news`, `get_news`, `get_social_sentiment`)
  - Meaning: the source's key is missing: `NEWSAPI_KEY`, `CRYPTOPANIC_API_KEY`, or
    `TWITTER_BEARER_TOKEN` / `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET`. The Risk Guardian then
    treats sentiment as neutral and says so (`sentiment.status` in `validate_trade_risk`).
  - Fix: set the key (`docs/SENTIMENT.md`), or use `get_free_news` (no key).
- **`source_unavailable`** (`get_financial_news`, `get_news`, `get_free_news`, `get_sentiment`, `get_social_sentiment`)
  - Meaning: the source did not answer. A failure is never reported as "no news".
