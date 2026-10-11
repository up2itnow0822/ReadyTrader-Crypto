# ReadyTrader-Crypto MCP Tool Catalog

This file is a curated catalog (parameters, examples, error codes) of the 29 MCP tools
`server.py` registers. It is hand-maintained, not generated: `tests/test_docs_tool_roster.py`
keeps its list of tool names identical to what `server.py` actually registers, and
`python tools/generate_tool_docs.py` prints the live registry — every tool's signature and the
short description agents see — so this page can be checked against it.

> [!TIP]
> AI agents can use these tools to gather intelligence, assess risk, and execute trades.

______________________________________________________________________

## Tool Categories Overview

| Category                    | Tools | Purpose                                            |
| :-------------------------- | :---- | :------------------------------------------------- |
| **Trading & Risk**          | 2     | Paper trading deposits and trade risk validation   |
| **Execution (DEX/CEX)**     | 16    | Order placement, management, and WebSocket streams |
| **Market Data**             | 4     | Price feeds, historical data, sentiment, news      |
| **Research & Intelligence** | 7     | Social sentiment, market regime, backtesting       |

______________________________________________________________________

## Trading & Risk

| Tool Name                                     | Description                                                    |
| :-------------------------------------------- | :------------------------------------------------------------- |
| [`deposit_paper_funds`](#deposit_paper_funds) | [PAPER MODE] Deposit fake funds into the paper trading wallet. |
| [`validate_trade_risk`](#validate_trade_risk) | [GUARDIAN] Validate if a trade is safe to execute.             |

### `deposit_paper_funds`

**Signature:** `deposit_paper_funds(asset: str, amount: float) -> str`

```text
[PAPER MODE] Deposit fake funds into the paper trading wallet.

Use this tool to initialize or top-up your paper trading balance for testing
strategies without risking real funds. Only works when PAPER_MODE=true.

Parameters:
- asset: The asset symbol to deposit (e.g., "USDC", "ETH", "BTC"). Upper-cased before it is
  credited, so "usdt" and "USDT" are the same paper balance.
- amount: The amount to deposit (e.g., 10000.0 for $10,000 USDC)

Returns:
- JSON response with deposit confirmation and updated balance

Example:
  deposit_paper_funds("USDC", 10000.0)
  → Deposits 10,000 USDC into the paper wallet

Error Codes:
- paper_mode_required: Paper mode is not enabled
- invalid_asset: Asset must be a ticker (e.g. "USDC"), at most 32 characters, no "/"
- invalid_amount: Amount must be a positive number no larger than 1e12
```

### `validate_trade_risk`

**Signature:** `validate_trade_risk(side: str, symbol: str, amount_usd: float, portfolio_value: float) -> str`

```text
[GUARDIAN] Ask the Risk Guardian about a trade before placing it. The same rules also run on
every order (`place_cex_order` and `swap_tokens` refuse a trade they would refuse), in both
paper and live mode — this tool is the advisory, no-side-effect way to ask first.

Rules:
- Position size: the part of a trade that adds exposure may be at most 5% of the portfolio
  passed in.
- Daily loss / max drawdown: after a 5% daily loss or a 10% drawdown of the paper account
  (trading results; deposits are not gains and do not end a halt), only trades that reduce
  exposure pass. "Today" starts from the account's last recorded value of the previous UTC day (a
  trade, a deposit or the first check of a day records one), else its first value today: a move
  after a day's last record counts toward the next day's loss too, which errs toward halting. Live accounts have no loss history here, so these two rules do not run on live
  orders; the order's `risk.inactive_rules` says so.
- Falling Knife (sentiment only — there is no price-based Falling Knife rule for crypto;
  `falling_knife` in the response says why, and see `docs/FALLING_KNIFE.md`): a measured
  sentiment below -0.5 blocks BUYs.

Unlike the order tools, this call takes `amount_usd` and `portfolio_value` as given — it does
not read a real account, and (without knowing whether the trade reduces an existing position)
treats every BUY as adding exposure and every SELL as not.

Parameters:
- side: "buy" or "sell"
- symbol: Trading pair (e.g., "BTC/USDT")
- amount_usd: Trade value in USD (must be a positive number)
- portfolio_value: Total portfolio value in USD (must be a positive number)

Returns:
- `result`: { allowed: bool, reason: string }
- `sentiment`: the data the Falling Knife rule used — { score, status, texts, bullish, bearish,
  age_seconds, hint? }. `status` is `"ok"` for a measured score, or `"no_data"` /
  `"not_configured"` / `"insufficient_data"` for a neutral `0.0` the rule cannot act on (in
  which case `hint` explains why). This tool never fetches sentiment itself — call
  `get_social_sentiment(symbol)` first to get a measured, non-neutral reading.
- `falling_knife`: the same `{sentiment, price}` block every order response carries
  (`docs/FALLING_KNIFE.md`).

Example:
  validate_trade_risk("buy", "BTC/USDT", 500, 10000)
  → Validates a $500 BTC buy against a $10,000 portfolio

Risk Rules Applied:
1. Position Size: Max 5% of portfolio per trade
2. Daily Loss: Halts buys if daily loss exceeds 5%
3. Max Drawdown: Halts buys if drawdown exceeds 10%
4. Falling Knife: Blocks buys when sentiment < -0.5

Error Codes:
- invalid_request: side is not "buy"/"sell", or amount_usd/portfolio_value is not a positive number
- risk_validation_error: Unexpected failure while checking the trade
```

______________________________________________________________________

## Execution (DEX/CEX)

| Tool Name                                               | Description                                                    |
| :------------------------------------------------------ | :------------------------------------------------------------- |
| [`swap_tokens`](#swap_tokens)                           | Swap tokens on a DEX (paper mode or live).                     |
| [`transfer_eth`](#transfer_eth)                         | Transfer native currency (ETH/BASE/ARB/OP native token).       |
| [`place_cex_order`](#place_cex_order)                   | Place an order on a CEX using CCXT authenticated credentials.  |
| [`get_cex_balance`](#get_cex_balance)                   | Fetch account balance from a centralized exchange.             |
| [`get_cex_order`](#get_cex_order)                       | Fetch details of a specific order from a centralized exchange. |
| [`cancel_cex_order`](#cancel_cex_order)                 | Cancel an open order on a centralized exchange.                |
| [`get_cex_capabilities`](#get_cex_capabilities)         | Query exchange capabilities and market information.            |
| [`list_cex_open_orders`](#list_cex_open_orders)         | List all currently open (unfilled) orders on an exchange.      |
| [`list_cex_orders`](#list_cex_orders)                   | List recent orders (open, filled, cancelled) from an exchange. |
| [`get_cex_my_trades`](#get_cex_my_trades)               | Fetch executed trades (fills) from a centralized exchange.     |
| [`cancel_all_cex_orders`](#cancel_all_cex_orders)       | Cancel all open orders on a centralized exchange.              |
| [`replace_cex_order`](#replace_cex_order)               | Replace (edit) an existing order on a centralized exchange.    |
| [`wait_for_cex_order`](#wait_for_cex_order)             | Wait for an order to reach a terminal state.                   |
| [`start_cex_private_ws`](#start_cex_private_ws)         | Start a private WebSocket stream for order updates.            |
| [`stop_cex_private_ws`](#stop_cex_private_ws)           | Stop a private WebSocket stream for order updates.             |
| [`list_cex_private_updates`](#list_cex_private_updates) | List recent private updates from exchange streams.             |

### `swap_tokens`

**Signature:** `swap_tokens(from_token: str, to_token: str, amount: float, chain: str = "ethereum", rationale: str = "", idempotency_key: str = "") -> str`

```text
Swap tokens on a DEX (paper mode or live). The Risk Guardian runs before every swap, in both
modes (`docs/FALLING_KNIFE.md`): the part of a swap that adds exposure may be at most 5% of the
account's value, and it fails closed if that account or the swap's USD value cannot be read.

In paper mode:
  - Trades at the market rate for FROM/TO — found directly, inverted (TO/FROM), or through USDT
    (FROM/USDT over TO/USDT) — from the market-data bus. `paper_price_required` if none of
    those resolve.
  - Checked against the paper account's value.
In live mode:
  - Checked against the signer wallet's value on `chain` (native coin + known tokens).
  - Builds a swap transaction using 1inch aggregator
  - Signs with configured signer (supports env_key, keystore, remote, MPC)
  - Broadcasts via JSON-RPC to the blockchain
  - If `EXECUTION_APPROVAL_MODE=approve_each`, the check above runs before a proposal is made
    and again when the approval API executes it.

Parameters:
- from_token: Source token symbol or contract address (e.g., "ETH", "USDC", "0x...")
- to_token: Destination token symbol or contract address
- amount: Amount to swap (in human-readable units, e.g., 1.5 ETH); must be a positive number
- chain: Blockchain network ("ethereum", "base", "arbitrum", "optimism")
- rationale: Optional reason for the trade (for audit trail)
- idempotency_key: Optional unique key to prevent duplicate executions

Returns:
- JSON with transaction hash (live) or fill result (paper), plus `risk`: the Risk Guardian's
  check ({allowed, reason, ...}, from `swap_check`)

Supported Chains:
- ethereum (chainId: 1)
- base (chainId: 8453)
- arbitrum (chainId: 42161)
- optimism (chainId: 10)

Safety Features:
- Risk Guardian (position size, daily loss / drawdown, Falling Knife sentiment)
- Policy validation (chain, token, amount limits)
- Router address allowlist verification
- Signer policy constraints
- Idempotency protection against replay

Error Codes:
- invalid_amount: amount must be a positive number
- paper_engine_missing: Paper mode but the paper engine is not initialized
- paper_price_required: Paper mode, and no market rate for the pair (direct, inverted, or via USDT)
- risk_blocked: The Risk Guardian refused the swap (`error.data.risk` has the numbers)
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- trading_halted: TRADING_HALTED=true
- execution_mode_blocked: Blocked by EXECUTION_MODE for the dex venue
- chain_not_allowed: Chain not in ALLOW_CHAINS
- token_not_allowed: Token not in ALLOW_TOKENS
- trade_amount_too_large: Exceeds MAX_TRADE_AMOUNT (or a per-token MAX_TRADE_AMOUNT_<TOKEN>)
- router_not_allowed / signer_address_not_allowed / sign_*: other policy allowlists, when configured
- execution_error: Unexpected failure (anything not covered by a code above)
```

### `transfer_eth`

**Signature:** `transfer_eth(to_address: str, amount: float, chain: str = "ethereum", idempotency_key: str = "") -> str`

```text
Transfer native currency (ETH/BASE/ARB/OP native token).

Live mode signs and broadcasts via JSON-RPC.
Not supported in paper mode.

Parameters:
- to_address: Recipient wallet address (0x...)
- amount: Amount to transfer in native units (e.g., 0.1 for 0.1 ETH)
- chain: Blockchain network ("ethereum", "base", "arbitrum", "optimism")
- idempotency_key: Optional unique key to prevent duplicate transfers

Returns:
- JSON with transaction hash and confirmation

Safety Features:
- Recipient allowlist (ALLOW_TO_ADDRESSES)
- Transfer amount limit (MAX_TRANSFER_NATIVE)
- Signer policy validation

Note: this tool is not risk-checked (no Risk Guardian call) — it moves the native coin, it does
not trade.

Error Codes:
- paper_mode_not_supported: Native transfers not available in paper mode
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- trading_halted: TRADING_HALTED=true
- execution_mode_blocked: Blocked by EXECUTION_MODE for the dex venue
- chain_not_allowed: Chain not in ALLOW_CHAINS
- recipient_not_allowed: Address not in allowlist
- transfer_amount_too_large: Exceeds MAX_TRANSFER_NATIVE
- transfer_error: Unexpected failure (anything not covered by a code above)
```

### `place_cex_order`

**Signature:** `place_cex_order(symbol: str, side: str, amount: float, order_type: str = "market", price: float | None = None, exchange: str = "binance", market_type: str = "spot", idempotency_key: str = "") -> str`

```text
Place an order on a CEX using CCXT authenticated credentials.

In paper mode, this routes to the paper engine and does NOT require CEX credentials. Paper
orders fill at the market price from the market-data bus, the way an exchange would:
a **market** order ignores any `price` it is given, and a **limit** order fills — at the market
price, not the limit price — only when it is marketable (a BUY at or above the market, a SELL at
or below it); an unmarketable limit is refused with `limit_not_marketable` rather than resting on
a book paper mode does not simulate. No usable market price for the symbol fails with
`paper_price_required`.
In live mode, executes against the real exchange.

The Risk Guardian (`docs/FALLING_KNIFE.md`) checks every order, in both modes, before it fills,
is proposed, or is sent: the part of an order that adds exposure may be at most 5% of the
account's value (the paper account, or the exchange account in live mode); a measured sentiment
below -0.5 blocks BUYs; in paper mode, after a 5% daily loss or a 10% drawdown only orders that
reduce exposure pass (live orders report those two in `risk.inactive_rules`: the exchange account
has no loss history here). The order is valued at the market-data price, never at a price the
caller supplies alone: a market order at the market, a limit order at the higher of its limit and
the market; with no market price, an order that adds exposure is refused. On a spot account,
selling what is held into cash (a USD stablecoin or fiat quote) is an exit and is not
size-limited; selling into a crypto quote (ETH/BTC) buys that quote asset, whose proceeds are sized
as new exposure and checked against its sentiment. On a futures/swap account (`market_type` other
than `spot`) the position cannot be read here, so every order, a closing one included, is sized as
new exposure: close a large derivatives position in steps or on the exchange. A contract symbol
(`BTC/USDT:USDT`) needs `market_type="swap"` or `"future"` (it is refused as `spot`, where the
exchange would still route it to the derivatives account); paper mode trades spot pairs only.

Parameters:
- symbol: Trading pair (e.g., "BTC/USDT", "ETH/USDC")
- side: "buy" or "sell"
- amount: Order quantity in base currency units; must be a positive number
- order_type: "market" (immediate) or "limit" (price-specified)
- price: Limit price (required and must be positive for limit orders; ignored for market orders)
- exchange: Exchange ID (e.g., "binance", "kraken", "coinbase")
- market_type: "spot", "swap", or "future"
- idempotency_key: Optional unique key to prevent duplicate orders

Returns:
- JSON with order details (paper: `fill`; live: the exchange's order), plus `risk`: the Risk
  Guardian's check ({allowed, reason, ...}, from `pre_trade_check`)

Supported Exchanges (100+ via CCXT):
- Tier 1: binance, kraken, coinbase, bybit, okx
- See docs/EXCHANGES.md for full compatibility matrix

Safety Features:
- Risk Guardian (position size, daily loss / drawdown, Falling Knife sentiment)
- Policy validation (exchange, symbol, market type, amount limits — live mode)
- Approval gate in approve_each mode
- Idempotency protection

Error Codes:
- invalid_side: side is not "buy" or "sell"
- invalid_order_type: order_type is not "market" or "limit"
- invalid_amount: amount must be a positive number
- invalid_price: price must be a positive number, and a limit order needs one
- paper_engine_missing: Paper mode but the paper engine is not initialized
- paper_price_required: Paper mode and no market-data bus price is available for the symbol
- limit_not_marketable: Paper mode; the limit price would rest on the book instead of filling now
- risk_blocked: The Risk Guardian refused the order (`error.data.risk` has the numbers)
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- trading_halted: TRADING_HALTED=true
- execution_mode_blocked: CEX disabled by EXECUTION_MODE=dex, or blocked for this venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- symbol_not_allowed: Symbol not in ALLOW_CEX_SYMBOLS
- market_type_not_allowed: market_type not in ALLOW_CEX_MARKET_TYPES
- order_amount_too_large: Exceeds MAX_CEX_ORDER_AMOUNT
- cex_error: Unexpected exchange API error (anything not covered by a code above)
```

### `get_cex_balance`

**Signature:** `get_cex_balance(exchange: str = "binance", market_type: str = "spot") -> str`

```text
Fetch account balance from a centralized exchange.

In paper mode, returns the paper wallet's balances and does not require CEX
credentials. In live mode, returns the balance of all assets in the real account
and requires CEX credentials configured via environment variables (CEX_API_KEY,
CEX_API_SECRET).

Parameters:
- exchange: Exchange ID (e.g., "binance", "kraken", "coinbase")
- market_type: "spot", "swap", or "future"

Returns:
- Paper mode: JSON with the paper wallet's balances (`mode: "paper"`)
- Live mode: JSON with all asset balances (free, used, total)

Required Environment Variables (live mode only):
- CEX_API_KEY or CEX_{EXCHANGE}_API_KEY
- CEX_API_SECRET or CEX_{EXCHANGE}_API_SECRET
- CEX_API_PASSWORD (optional, for some exchanges)

Error Codes:
- paper_engine_missing: Paper mode but the paper engine is not initialized
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Unexpected exchange API error or authentication failure
```

### `get_cex_order`

**Signature:** `get_cex_order(order_id: str, symbol: str = "", exchange: str = "binance", market_type: str = "spot") -> str`

```text
Fetch details of a specific order from a centralized exchange. Live exchange accounts only —
paper orders fill immediately and never rest on an exchange, so there is nothing to look up.

Retrieves the current state of an order including fill status, executed
quantity, and average price. Useful for tracking order execution.

Parameters:
- order_id: Exchange order ID
- symbol: Trading pair (may be required by some exchanges)
- exchange: Exchange ID
- market_type: "spot", "swap", or "future"

Returns:
- JSON with normalized order details:
  - exchange, id, client_order_id, symbol, market_type
  - side, order_type, status
  - amount, filled, remaining
  - price, average, cost
  - timestamp (ms), raw (the unmodified CCXT order)

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and never rest on an exchange
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Order not found, or an unexpected exchange API error
```

### `cancel_cex_order`

**Signature:** `cancel_cex_order(order_id: str, symbol: str = "", exchange: str = "binance", market_type: str = "spot") -> str`

```text
Cancel an open order on a centralized exchange. Live exchange accounts only — paper orders fill
immediately and never rest on an exchange, so there is nothing to cancel.

Attempts to cancel an unfilled or partially filled order. Returns the
cancellation result. Note: orders may fill before cancellation completes.

Parameters:
- order_id: Exchange order ID to cancel
- symbol: Trading pair (may be required by some exchanges)
- exchange: Exchange ID
- market_type: "spot", "swap", or "future"

Returns:
- JSON with cancellation confirmation

Important Notes:
- Race condition: Order may fill before cancel reaches exchange
- Partial fills: Only unfilled portion is cancelled
- Some exchanges have cancel cooldowns

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and never rest on an exchange
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Order not found, already filled, or an unexpected API error
```

### `get_cex_capabilities`

**Signature:** `get_cex_capabilities(exchange: str = "binance", symbol: str = "", market_type: str = "spot") -> str`

```text
Query exchange capabilities and market information.

Returns supported features, order types, timeframes, and market metadata
for the specified exchange. Useful for determining available functionality
before placing orders. Does not require authentication.

Parameters:
- exchange: Exchange ID
- symbol: Optional specific symbol for market info
- market_type: "spot", "swap", or "future"

Returns:
- JSON with capabilities:
  - has: Feature flags (createOrder, fetchBalance, etc.)
  - timeframes: Supported OHLCV intervals
  - market: Symbol-specific limits and precision

Use Cases:
- Check if exchange supports cancelAllOrders
- Get minimum order size for a symbol
- Verify supported order types

Error Codes:
- cex_error: Exchange initialization failed
- execution_mode_blocked: CEX disabled by EXECUTION_MODE=dex
```

### `list_cex_open_orders`

**Signature:** `list_cex_open_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str`

```text
List all currently open (unfilled) orders on a centralized exchange. Live exchange accounts
only — paper orders fill immediately and never rest on an exchange, so none are ever open.

Returns orders that are pending execution. Can be filtered by symbol.
Useful for monitoring active positions and managing order book exposure.

Parameters:
- exchange: Exchange ID
- symbol: Optional filter by trading pair
- market_type: "spot", "swap", or "future"
- limit: Maximum orders to return (default: 100)

Returns:
- JSON with array of normalized open orders (see `get_cex_order`'s field list)

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and never rest on an exchange
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Unexpected API error or authentication failure
```

### `list_cex_orders`

**Signature:** `list_cex_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str`

```text
List recent orders (open, filled, and cancelled) from a centralized exchange. Live exchange
accounts only — paper orders fill immediately and are not tracked as exchange order history.

Returns order history including both active and completed orders. Useful
for reviewing trading activity and reconciling execution history.

Parameters:
- exchange: Exchange ID
- symbol: Optional filter by trading pair
- market_type: "spot", "swap", or "future"
- limit: Maximum orders to return (default: 100)

Returns:
- JSON with array of normalized orders, all statuses (see `get_cex_order`'s field list)

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and are not tracked as exchange order history
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Unexpected API error or authentication failure
```

### `get_cex_my_trades`

**Signature:** `get_cex_my_trades(exchange: str = "binance", symbol: str = "", market_type: str = "spot", limit: int = 100) -> str`

```text
Fetch executed trades (fills) from a centralized exchange. Live exchange accounts only — paper
fills are returned by `place_cex_order`/`swap_tokens` themselves, not tracked here.

Returns actual trade executions with price, quantity, and fee information.
Useful for P&L calculation, tax reporting, and execution analysis.

Parameters:
- exchange: Exchange ID
- symbol: Optional filter by trading pair
- market_type: "spot", "swap", or "future"
- limit: Maximum trades to return (default: 100)

Returns:
- JSON with the raw CCXT trade records (unmodified, not normalized); a trade typically has
  id, order, symbol, side, price, amount, cost, fee (currency, cost, rate), and timestamp, but
  the exact fields depend on the exchange.

Use Cases:
- Calculate realized P&L
- Export for tax reporting
- Analyze execution quality (slippage)

Error Codes:
- paper_mode_not_supported: Paper fills are not tracked as exchange trade history
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Unexpected API error or authentication failure
```

### `cancel_all_cex_orders`

**Signature:** `cancel_all_cex_orders(exchange: str = "binance", symbol: str = "", market_type: str = "spot") -> str`

```text
Cancel all open orders on a centralized exchange. Live exchange accounts only — paper orders
fill immediately and never rest on an exchange, so there is nothing to cancel.

Emergency function to cancel all pending orders. Can be filtered by symbol.
Useful for risk management and rapid position unwinding.
Note: not all exchanges support this operation.

Parameters:
- exchange: Exchange ID
- symbol: Optional filter by trading pair (cancel all if empty)
- market_type: "spot", "swap", or "future"

Returns:
- JSON with cancellation results

⚠️ Warning:
- This is a high-impact operation
- Use get_cex_capabilities to verify support first
- Some exchanges may have rate limits on mass cancellation

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and never rest on an exchange
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Exchange doesn't support cancelAllOrders, or an unexpected API error
```

### `replace_cex_order`

**Signature:** `replace_cex_order(exchange: str, order_id: str, symbol: str, side: str, amount: float, order_type: str = "limit", price: float | None = None, market_type: str = "spot") -> str`

```text
Replace (edit) an existing order on a centralized exchange. Live exchange accounts only —
paper orders fill immediately and never rest on an exchange, so there is nothing to replace.

Atomically cancels the existing order and places a new one with updated
parameters. Useful for adjusting limit prices without losing queue position.
Note: not all exchanges support this operation.

If `EXECUTION_APPROVAL_MODE=approve_each`, this tool is refused outright with
`approval_required` (a replacement is a new order and cannot go through the proposal flow the
way `place_cex_order` does): cancel the order, then call `place_cex_order`, which will return a
proposal. Otherwise the replacement passes the same policy checks as `place_cex_order`
(exchange/symbol/market-type allowlists, MAX_CEX_ORDER_AMOUNT) and the Risk Guardian
(`docs/FALLING_KNIFE.md`) before it is sent.

Parameters:
- exchange: Exchange ID
- order_id: Existing order ID to replace
- symbol: Trading pair
- side: "buy" or "sell"
- amount: New order quantity
- order_type: "market" or "limit"
- price: New limit price
- market_type: "spot", "swap", or "future"

Returns:
- JSON with the new order's normalized details (see `get_cex_order`'s field list)

Advantages over Cancel+Create:
- Atomic operation (no gap between cancel and new order)
- May preserve queue position on some exchanges

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately and never rest on an exchange
- approval_required: EXECUTION_APPROVAL_MODE=approve_each; cancel and re-place instead
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- trading_halted: TRADING_HALTED=true
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed / symbol_not_allowed / market_type_not_allowed: not in the matching allowlist
- invalid_side / invalid_order_type / invalid_amount / invalid_price: same validation as place_cex_order
- order_amount_too_large: Exceeds MAX_CEX_ORDER_AMOUNT
- risk_blocked: The Risk Guardian refused the replacement (`error.data.risk` has the numbers)
- cex_error: Exchange doesn't support editOrder, or an unexpected API error
```

### `wait_for_cex_order`

**Signature:** `wait_for_cex_order(exchange: str, order_id: str, symbol: str = "", market_type: str = "spot", timeout_sec: int = 30, poll_interval_sec: float = 2.0) -> str`

```text
Wait for an order to reach a terminal state (filled, cancelled, rejected). Live exchange
accounts only — paper orders fill immediately, so there is nothing to wait for.

Polls the exchange at regular intervals (by calling `get_cex_order` internally) until the
order completes or the timeout is reached. Useful for synchronous execution flows.
Returns the final order state.

Parameters:
- exchange: Exchange ID
- order_id: Order ID to monitor
- symbol: Trading pair
- market_type: "spot", "swap", or "future"
- timeout_sec: Maximum wait time (default: 30 seconds)
- poll_interval_sec: Time between polls (default: 2.0 seconds)

Returns:
- JSON with final order state (see `get_cex_order`'s field list)

Terminal States:
- closed (filled)
- canceled / cancelled
- rejected
- expired

Error Codes:
- paper_mode_not_supported: Paper orders fill immediately; there is nothing to wait for
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- (not refused by TRADING_HALTED=true: the kill switch stops new orders, not reads or cancels)
- timeout: Order did not reach terminal state within timeout
- Any error `get_cex_order` can return (e.g. exchange_not_allowed, cex_error) is passed through unchanged
```

### `start_cex_private_ws`

**Signature:** `start_cex_private_ws(exchange: str = "binance", market_type: str = "spot") -> str`

```text
Start a private WebSocket stream for real-time order/execution updates.

Supports native WebSocket for: Binance, Kraken, Coinbase.
For other exchanges, falls back to REST polling.
Provides real-time notifications of order fills and status changes.

Parameters:
- exchange: Exchange ID
- market_type: "spot", "swap", or "future"

Returns:
- JSON with stream status { mode: "ws"|"poll", status: "started" }

WebSocket Support:
- binance: Native WebSocket (user data stream)
- kraken: Native WebSocket (private channel)
- coinbase: Native WebSocket (user channel)
- others: REST polling fallback

Error Codes:
- paper_mode_not_supported: Private updates not available in paper mode
- live_trading_disabled: LIVE_TRADING_ENABLED=false
- trading_halted: TRADING_HALTED=true
- execution_mode_blocked: Blocked for the cex venue by EXECUTION_MODE
- exchange_not_allowed: Exchange not in ALLOW_EXCHANGES
- cex_error: Stream initialization failed
```

### `stop_cex_private_ws`

**Signature:** `stop_cex_private_ws(exchange: str = "binance", market_type: str = "spot") -> str`

```text
Stop a private WebSocket stream for order/execution updates.

Cleanly disconnects from the exchange's private update channel.
Should be called when monitoring is no longer needed.

Parameters:
- exchange: Exchange ID
- market_type: "spot", "swap", or "future"

Returns:
- JSON with stream status { status: "stopped" }

Note: unlike `start_cex_private_ws`, this does not check LIVE_TRADING_ENABLED/TRADING_HALTED or
the exchange allowlist — only whether the server is in paper mode.

Error Codes:
- paper_mode_not_supported: Private updates not available in paper mode
- cex_error: Unexpected failure while stopping the stream
```

### `list_cex_private_updates`

**Signature:** `list_cex_private_updates(exchange: str = "binance", market_type: str = "spot", limit: int = 100) -> str`

```text
List recent private updates (order fills, status changes) from exchange.

Returns buffered events from the active private update stream.
Events include order executions, status changes, and account updates.
Requires start_cex_private_ws to be called first.

Parameters:
- exchange: Exchange ID
- market_type: "spot", "swap", or "future"
- limit: Maximum events to return (default: 100)

Returns:
- JSON with array of update events

Event Types:
- ORDER_UPDATE: Order status change
- TRADE: Fill/execution event
- BALANCE_UPDATE: Account balance change

Note: like `stop_cex_private_ws`, this only checks whether the server is in paper mode; it does
not check LIVE_TRADING_ENABLED/TRADING_HALTED or the exchange allowlist.

Error Codes:
- paper_mode_not_supported: Private updates not available in paper mode
- cex_error: Unexpected failure while reading buffered events
```

______________________________________________________________________

## Market Data

| Tool Name                               | Description                                                          |
| :-------------------------------------- | :------------------------------------------------------------------- |
| [`get_crypto_price`](#get_crypto_price) | Get the current price of a cryptocurrency.                           |
| [`fetch_ohlcv`](#fetch_ohlcv)           | Fetch historical OHLCV (candlestick) data.                           |
| [`get_sentiment`](#get_sentiment)       | Get the current Crypto Fear & Greed Index.                           |
| [`get_news`](#get_news)                 | Hot crypto market news from CryptoPanic (needs CRYPTOPANIC_API_KEY). |

### `get_crypto_price`

**Signature:** `get_crypto_price(symbol: str, exchange: str = "binance") -> str`

```text
Get the current price of a cryptocurrency.

Fetches real-time price data from the MarketDataBus which aggregates
data from multiple sources with freshness scoring.

Parameters:
- symbol: Trading pair (e.g., "BTC/USDT", "ETH/USDC")
- exchange: Preferred exchange source (default: "binance")

Returns:
- JSON with:
  - result: prose sentence, e.g. "The current price of BTC/USDT is 65000.0 (Source: binance)"
  - price: the same price as a number (float, or null if unavailable)
  - source: the provider id that served the price (e.g. "exchange_ws", "ingest", "ccxt_rest")
  - timestamp: ISO 8601 UTC timestamp of the ticker (or null if unavailable)

Data Priority (MarketDataBus):
1. WebSocket store (real-time, highest priority)
2. Ingest store (user-supplied feeds)
3. CCXT REST (fallback)

Error Codes:
- fetch_price_error: Unable to fetch price data
```

### `fetch_ohlcv`

**Signature:** `fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 24) -> str`

```text
Fetch historical OHLCV (candlestick) data.

Retrieves Open, High, Low, Close, Volume data for technical analysis
and strategy development.

Parameters:
- symbol: Trading pair (e.g., "BTC/USDT")
- timeframe: Candle interval ("1m", "5m", "15m", "1h", "4h", "1d", etc.)
- limit: Number of candles to fetch (default: 24)

Returns:
- JSON with array of OHLCV records, each with:
  - timestamp: ISO 8601 UTC timestamp (string)
  - timestamp_ms: the same instant as an integer Unix timestamp in milliseconds
  - open, high, low, close: Price values (float)
  - volume: Trading volume (float)

Supported Timeframes:
- Minutes: 1m, 3m, 5m, 15m, 30m
- Hours: 1h, 2h, 4h, 6h, 12h
- Days: 1d, 3d, 1w, 1M

Error Codes:
- fetch_ohlcv_error: Unable to fetch historical data
```

### `get_sentiment`

**Signature:** `get_sentiment() -> str`

```text
Get the current Crypto Fear & Greed Index (alternative.me; no key needed).

Fetches the index from alternative.me (0 Extreme Fear .. 100 Extreme Greed). Useful for
contrarian trading and risk assessment.

Parameters: None

Returns:
- JSON with one field, `sentiment`: a prose string, e.g.
  `"Fear & Greed Index: 42 (Fear)"`. The 0-100 value and its classification are alternative.me's
  own text, embedded in this string — there are no separate `value`/`classification`/`timestamp`
  fields.

Error Codes:
- source_unavailable: alternative.me could not be read (never reported as a reading)

Interpretation (alternative.me's own bands, as they appear in the string):
- 0-24: Extreme Fear (potential buying opportunity)
- 25-49: Fear
- 50-74: Greed
- 75-100: Extreme Greed (potential selling signal)
```

### `get_news`

**Signature:** `get_news() -> str`

```text
Hot crypto market news from CryptoPanic (needs CRYPTOPANIC_API_KEY).

Fetches CryptoPanic's "hot" news feed. Useful for fundamental analysis and event-driven
trading.

Parameters: None

Returns:
- JSON with one field, `news`: a text block with up to 5 numbered headlines, e.g.
  `"CryptoPanic News:\n1. ...\n2. ..."`, or `"CryptoPanic: no hot news right now."` when the
  feed is empty. Not an array, and no url/published_at/source fields — CryptoPanic is the only
  source.

Error Codes:
- not_configured: CRYPTOPANIC_API_KEY is not set (see https://cryptopanic.com/developers/api/)
- source_unavailable: CryptoPanic did not answer, or answered without the expected data
```

______________________________________________________________________

## Research & Intelligence

| Tool Name                                             | Description                                                                 |
| :---------------------------------------------------- | :-------------------------------------------------------------------------- |
| [`get_social_sentiment`](#get_social_sentiment)       | Score recent X/Reddit text for a symbol and cache it for the Risk Guardian. |
| [`get_financial_news`](#get_financial_news)           | Get NewsAPI headlines for a symbol (needs NEWSAPI_KEY).                     |
| [`get_free_news`](#get_free_news)                     | Get free market news from RSS feeds (CoinDesk, Cointelegraph).              |
| [`get_market_regime`](#get_market_regime)             | Detect market regime (TRENDING, RANGING, VOLATILE).                         |
| [`run_backtest_simulation`](#run_backtest_simulation) | Run a strategy simulation against historical data.                          |
| [`post_market_insight`](#post_market_insight)         | Share a market insight with other agents.                                   |
| [`get_latest_insights`](#get_latest_insights)         | Get the most recent high-signal insights.                                   |

### `get_social_sentiment`

**Signature:** `get_social_sentiment(symbol: str) -> str`

```text
Score recent X/Reddit text for the symbol (-1 bearish .. +1 bullish) and cache it for the Risk
Guardian. Answers not_configured when neither TWITTER_BEARER_TOKEN nor
REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET is set, and source_unavailable when every configured source
failed.

Fetches up to 10 recent X posts and 5 recent r/CryptoCurrency post titles mentioning the asset,
scores the bull/bear word balance locally (`docs/SENTIMENT.md`), and caches the score for one
hour for the Falling Knife rule (`validate_trade_risk`, `place_cex_order`, `swap_tokens`).

Parameters:
- symbol: Cryptocurrency symbol or pair (e.g., "BTC", "ETH", "BTC/USDT" — only the base asset is
  used)

Returns (when at least one source is configured):
- JSON with `social_sentiment`: a prose string describing what each configured source found and
  the resulting score, e.g. `"...\nSentiment score: +0.30 on [-1, +1] (2 bearish / 5 bullish / 1
  neutral of 8 texts)"`, and `sources`: each source's state this refresh (`{"twitter": "ok",
  "reddit": "not_configured"}`; a state is `ok`, `not_configured` or `error`). There is no
  numeric `overall_score`, `volume` or `trending_topics` field — the score lives inside the text
  (the cached numeric score is what `validate_trade_risk`'s `sentiment.score` reports).
  A refresh with too little new text to trust may instead report an earlier, more bearish
  reading still in force.

Error Codes:
- not_configured: Neither TWITTER_BEARER_TOKEN nor REDDIT_CLIENT_ID+REDDIT_CLIENT_SECRET is
  set. The Falling Knife check still records this (as a neutral 0.0 it cannot act on); this
  tool answers it as an error, not a result.
- source_unavailable: Every configured source failed this refresh (e.g. a rejected X token);
  `error.data.sources` says which. A failed refresh never relaxes the Falling Knife check
  (`docs/SENTIMENT.md`).
```

### `get_financial_news`

**Signature:** `get_financial_news(symbol: str) -> str`

```text
Headlines about the symbol from NewsAPI (needs NEWSAPI_KEY).

Queries NewsAPI's `/v2/everything` for `"{symbol} crypto"` (up to 3 articles, sorted by
relevancy). Useful for fundamental analysis, but these are ordinary NewsAPI headlines, not
institutional analyst commentary or price targets.

Parameters:
- symbol: Asset symbol (e.g., "BTC", "ETH")

Returns:
- JSON with one field, `financial_news`: a text block, e.g.
  `"Financial Headlines (NewsAPI):\n1. Title (Source)\n..."`, or `"NewsAPI: No articles
  found."` when nothing matched. Not an array, and no `analyst_commentary` or `price_targets`
  fields.

Error Codes:
- not_configured: NEWSAPI_KEY is not set (see https://newsapi.org/)
- source_unavailable: NewsAPI did not answer, or answered with a non-"ok" status
```

### `get_free_news`

**Signature:** `get_free_news(symbol: str = "") -> str`

```text
Get free market news from RSS feeds (CoinDesk, Cointelegraph); no key needed.

Reads exactly two RSS feeds — CoinDesk and Cointelegraph — and takes up to 3 entries from
each; no other outlets are read.

Parameters:
- symbol: Optional filter by asset (empty for all news). When given, an entry is kept only if
  the symbol text appears in its title or summary.

Returns:
- JSON with one field, `news`: a text block, e.g. `"Market News (Free RSS):\n1. Headline
  (CoinDesk)\n..."` (up to 6 headlines total), or a "no news found" sentence when nothing
  matched. Not an array of item objects.

Error Codes:
- source_unavailable: Neither feed could be read (a symbol filter that matches nothing is not
  an error — it returns a "no news found" message instead)
```

### `get_market_regime`

**Signature:** `get_market_regime(symbol: str, timeframe: str = "1d") -> str`

```text
Detect the current market regime (TRENDING, RANGING, VOLATILE).

Fetches 100 candles and uses ADX (Average Directional Index, 14-period) and ATR (Average True
Range, 14-period, as a percentage of price) to classify the current market state.

Parameters:
- symbol: Trading pair (e.g., "BTC/USDT")
- timeframe: Analysis timeframe (default: "1d")

Returns:
- JSON with `result`:
  - regime: `"TRENDING"` or `"RANGING"` (ADX > 25 is TRENDING, else RANGING), with a
    `"VOLATILE_"` prefix added to whichever it is when ATR exceeds 2% of price — so the actual
    values are `"TRENDING"`, `"RANGING"`, `"VOLATILE_TRENDING"`, or `"VOLATILE_RANGING"`, never
    a bare `"VOLATILE"`.
  - direction: `"UP"`, `"DOWN"`, or `"SIDEWAYS"` (not `"NEUTRAL"`; only set when TRENDING)
  - adx: ADX indicator value (0-100)
  - atr_pct: ATR as a percentage of the latest close (not a percentile)
  - summary: a one-line prose summary of the above
  - With fewer than 50 candles available, `result` is instead `{"error": "Not enough data for
    regime detection (need 50+ candles)"}` — still returned as `ok: true`, not as this tool's
    error code.

Strategy Implications:
- TRENDING (ADX > 25): Use trend-following strategies
- RANGING (ADX <= 25): Use mean-reversion strategies
- VOLATILE_* (atr_pct > 2%): Reduce position sizes

Error Codes:
- market_regime_error: Unable to fetch OHLCV data or compute the regime
```

### `run_backtest_simulation`

**Signature:** `run_backtest_simulation(strategy_code: str, symbol: str, timeframe: str = "1h") -> str`

````text
Run a strategy simulation against historical data.

Fetches 500 candles, pre-computes RSI(14)/SMA(20)/SMA(50), and runs your strategy in an
isolated child process (`strategy_sandbox.py`) against the closes and RSI values. The
strategy sees plain floats only — no pandas/ta, no file or network access.

Parameters:
- strategy_code: Python code defining 'def on_candle(price, rsi, state)'
- symbol: Trading pair (e.g., "BTC/USDT")
- timeframe: Candle interval (default: "1h")

Returns:
- JSON with `result`. On success:
  - initial_capital: Starting balance (fixed at 10,000.0; not a parameter of this tool)
  - final_value: Ending portfolio value
  - pnl: Absolute profit/loss
  - pnl_percent: Percentage return
  - total_trades: Number of trades executed
  - trades_log: Last 5 trades
  On failure, `result` is instead `{"error": "..."}` (with `"error_kind"` too, for every
  failure except a runtime error) — this tool always answers `ok: true`; it has no error
  code of its own. See Error Kinds below.

Strategy Code Requirements:
- Must define: def on_candle(price, rsi, state) -> str
- Return values: "buy", "sell", or "hold"
- 'state' dict persists across candles

Example Strategy:
```python
def on_candle(price, rsi, state):
    if rsi < 30:
        return "buy"
    elif rsi > 70:
        return "sell"
    return "hold"
````

Security:

- Code runs in an isolated child process (empty environment, RestrictedPython, POSIX rlimits
  where available)
- Limited imports (only 'math' allowed)
- No file/network access

Error Kinds (in `result.error_kind`, except `runtime` which only sets `result.error`):

- too_large: strategy_code exceeds the size cap
- forbidden: static check rejected the code (banned names/imports)
- compile: Invalid Python syntax
- runtime: Error during execution (message names the failing candle row)
- timeout: Strategy took too long
- resource: Sandbox resource limit hit
- protocol: Internal sandbox communication failure

````

### `post_market_insight`

**Signature:** `post_market_insight(symbol: str, agent_id: str, signal: str, confidence: float, reasoning: str, ttl_seconds: int = 3600) -> str`

```text
[PHASE 3] Share a market insight with other agents.

Multi-agent collaboration tool allowing research agents to share
high-signal insights with execution agents.

Parameters:
- symbol: Asset symbol (e.g., "BTC/USDT"); stored upper-case
- agent_id: Unique identifier for the posting agent
- signal: not validated against a fixed set — stored lower-cased exactly as given; the
  convention is "bullish" | "bearish" | "neutral"
- confidence: Confidence score, conventionally 0.0-1.0 (not enforced)
- reasoning: Explanation for the signal
- ttl_seconds: Time-to-live in seconds (default: 3600)

Returns:
- JSON with one field, `insight`: {insight_id, symbol, agent_id, signal, confidence,
  reasoning, timestamp_ms, expires_at_ms, meta}. `timestamp_ms`/`expires_at_ms` are Unix
  milliseconds, not ISO timestamps; `meta` is currently always `{}` (this tool does not accept
  a way to set it).

Use Case:
1. Researcher agent analyzes market → posts insight
2. Executor agent queries insights → makes trade decision
3. Trades can reference insight_id for audit trail
````

### `get_latest_insights`

**Signature:** `get_latest_insights(symbol: str = "") -> str`

```text
[PHASE 3] Get the most recent high-signal insights.

Retrieves insights posted by research agents for multi-agent
coordination and decision support.

Parameters:
- symbol: Optional filter by asset (empty for all insights; matched upper-case)

Returns:
- JSON with `insights`: an array of unexpired insights (newest first, limited to the 5 most
  recent), each {insight_id, symbol, agent_id, signal, confidence, reasoning, timestamp_ms,
  expires_at_ms, meta}. `timestamp_ms`/`expires_at_ms` are Unix milliseconds (not
  `created_at`/`expires_at` timestamps), and `signal`/`confidence` are whatever
  `post_market_insight` was given — not validated or restricted to BULLISH/BEARISH/NEUTRAL.
```

______________________________________________________________________

## Error Response Format

All tools return JSON with a consistent structure:

**Success Response:**

```json
{
  "ok": true,
  "data": {
    // Tool-specific response data
  }
}
```

**Error Response:**

```json
{
  "ok": false,
  "error": {
    "code": "error_code",
    "message": "Human-readable error message",
    "data": {
      // Additional error context
    }
  }
}
```

**Common Error Codes:**

This is not a complete list — each tool's own section above has the exact codes it can return.
A few codes are shared by many tools:

| Code                       | Description                                                                                                       |
| :------------------------- | :---------------------------------------------------------------------------------------------------------------- |
| `paper_mode_required`      | Operation requires PAPER_MODE=true                                                                                |
| `paper_mode_not_supported` | Operation not available in paper mode (all the live-account CEX order/history tools)                              |
| `risk_blocked`             | The Risk Guardian refused the order/swap; `error.data.risk` has the numbers (`docs/FALLING_KNIFE.md`)             |
| `live_trading_disabled`    | Live execution refused: LIVE_TRADING_ENABLED=false                                                                |
| `trading_halted`           | Live order, swap or transfer refused: TRADING_HALTED=true (reads and cancels still work)                          |
| `execution_mode_blocked`   | Operation blocked by EXECUTION_MODE for this venue                                                                |
| `exchange_not_allowed`     | Exchange not in ALLOW_EXCHANGES                                                                                   |
| `chain_not_allowed`        | Chain not in ALLOW_CHAINS                                                                                         |
| `token_not_allowed`        | Token not in ALLOW_TOKENS                                                                                         |
| `not_configured`           | The tool needs an API key that is not set (news/sentiment tools)                                                  |
| `source_unavailable`       | The configured news/sentiment source did not answer                                                               |
| `cex_error`                | Unexpected CEX API error or authentication failure                                                                |
| `execution_error`          | Unexpected DEX execution failure                                                                                  |
| `timeout`                  | Operation timed out                                                                                               |
| `rate_limited`             | Rate limit exceeded — enforced by the HTTP admin API (`api_server.py`); no MCP tool currently applies this itself |

______________________________________________________________________

## See Also

- `docs/ERRORS.md` - Detailed error catalog and troubleshooting
- `docs/EXCHANGES.md` - Exchange compatibility matrix
- `docs/MARKETDATA.md` - Market data architecture
- `docs/FALLING_KNIFE.md` - The Risk Guardian's Falling Knife rule (sentiment-only for crypto) and why there is no price-based version
- `docs/THREAT_MODEL.md` - Security considerations
