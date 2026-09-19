## ReadyTrader-Crypto Prompt Pack

Copy/paste prompts for Agent Zero, Claude, or any MCP-capable agent connected to
ReadyTrader-Crypto. All three assume `PAPER_MODE=true` (the default) and the real, current
29-tool roster (`docs/TOOLS.md`) — there is no `get_health`, `place_limit_order`,
`check_orders`, `get_address_balance`, or risk-disclosure-consent tool. Health/metrics/approvals
are HTTP endpoints on `api_server.py` (`GET /api/health`, `GET /api/metrics`,
`GET /api/pending-approvals`, `POST /api/approve-trade`), not MCP tools.

______________________________________________________________________

## Prompt 1 — 10-minute paper-mode evaluation

You have access to the ReadyTrader-Crypto MCP server. We are in PAPER_MODE=true.

Goals:

- Validate you can use the tools safely
- Produce a short "operator report" that proves the system works

Steps:

1. Call `deposit_paper_funds("USDC", 10000)` to seed the paper wallet.
1. Call `fetch_ohlcv("ETH/USDT", "1h", 1)` (or `get_crypto_price("ETH/USDT")`) to get a current
   price for ETH/USDT.
1. Call `get_social_sentiment("ETH")` so the Risk Guardian has a fresh, measured reading
   instead of a neutral default.
1. Call `validate_trade_risk("buy", "ETH/USDT", 100, 10000)` and report the verdict.
1. If allowed, call `place_cex_order("ETH/USDT", "buy", 0.05, order_type="limit", price=<step 2 price>)`
   — pass `price` explicitly; paper orders need no exchange credentials.
1. Call `get_cex_balance()` to confirm the updated paper wallet balances.
1. Produce a final summary with:
   - final balances
   - the Risk Guardian verdict
   - any errors encountered (name the error `code`, not just the message)

Constraints:

- Do not attempt live trading.
- If a tool call fails, report the JSON error `code` and `message` verbatim; do not guess at a
  tool that does not exist.

______________________________________________________________________

## Prompt 2 — Risk Guardian refusal (Falling Knife)

We are in PAPER_MODE=true. I want to see the Risk Guardian actually say no.

Steps:

1. Call `get_social_sentiment("BTC")` and note the `overall_score`.
1. Call `validate_trade_risk("buy", "BTC/USDT", 5000, 10000)` — a buy sized at 50% of the
   portfolio, well over the 5%-of-portfolio limit.
1. Report the verdict. It should be blocked on position size alone; if `overall_score` from
   step 1 is below -0.5, note that the Falling Knife rule would also block it.
1. Do **not** attempt to bypass the refusal or increase any limit — the goal is to see the
   guard work, not to get the trade through.

______________________________________________________________________

## Prompt 3 — Backtest a strategy in the sandbox (current contract)

We are in PAPER_MODE=true. Write and test a strategy using `run_backtest_simulation`.

The strategy sandbox (`strategy_sandbox.py`) runs your code in an isolated child process. Your
code may only import `math` — no `pandas`, `ta`, `string`, or `random`, no underscore-prefixed
names, and no `.format`/`.format_map`. It must define:

```python
def on_candle(price, rsi, state) -> str:
    # return "buy", "sell", or "hold"
    ...
```

and may optionally define a top-level `PARAMS` dict. See `docs/STRATEGY_SANDBOX.md` for the
full contract and limits.

Steps:

1. Write a mean-reversion `on_candle` that buys when `rsi < 30` and sells when `rsi > 70`.
1. Call `run_backtest_simulation(<your code>, "BTC/USDT", "1h")`.
1. Report `pnl`, `pnl_percent`, and `total_trades` from the result.
1. The tool call itself returns `ok: true` either way; a rejected strategy shows up as
   `data.result.error` / `data.result.error_kind` (e.g. `"forbidden"` or `"compile"`) instead of
   the PnL fields. If you see one, fix the specific line named in the error and retry — do not
   simplify by removing the sandbox constraints from your ask.

______________________________________________________________________

## Prompt 4 — Live-mode preflight (DO NOT EXECUTE TRADES)

We are preparing for live mode, but you must not place any live orders or sign transactions,
and you must not change `TRADING_HALTED`, `LIVE_TRADING_ENABLED`, or `PAPER_MODE`.

Tasks:

1. Summarize, from `env.example` and `docs/OPS_BTC_PRODUCTION.md`, what an operator must set
   before ever unhalting: `SIGNER_TYPE` (never `env_private_key` live), `ALLOW_EXCHANGES`,
   `ALLOW_CEX_SYMBOLS`, `ALLOW_CEX_MARKET_TYPES`, `EXECUTION_APPROVAL_MODE`.
1. Read `docs/ARCHITECTURE.md#approval-gate` and explain, in your own words, why an
   `approve_each` proposal created by this MCP process cannot currently be approved from the
   Next.js dashboard (they run as separate processes; `ExecutionStore` only loads proposals
   created by its own process).
1. Output a "go/no-go" checklist for the operator. Do not call any execution tool in this
   prompt.

______________________________________________________________________

## Prompt 5 — Market data sanity check across tools

We are in PAPER_MODE=true. Cross-check two market-data tools against each other.

1. Call `get_crypto_price("BTC/USDT")` and read its `price` field (numeric) and `source`.
1. Call `fetch_ohlcv("BTC/USDT", "1m", 1)` and read the single candle's `close`.
1. Compare the two numbers — they should be close (both come from the same
   `MarketDataBus`, but the ticker and the last closed candle can differ slightly).
1. If either call fails, report the error `code` (`fetch_price_error` / `fetch_ohlcv_error`) and
   check `GET /api/marketdata/status` for provider health before retrying.
