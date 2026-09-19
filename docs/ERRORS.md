### 🚨 Quick Fix Troubleshooting

If you are just getting started and seeing errors, check these first:

| Issue             | Quick Fix                                                                   | Reference                                |
| :---------------- | :-------------------------------------------------------------------------- | :--------------------------------------- |
| **Missing .env**  | Run `python tools/setup_wizard.py` to generate one.                         | [Setup Wizard](../tools/setup_wizard.py) |
| **Missing Keys**  | Check `docs/SENTIMENT.md` for links to get free API keys.                   | [Sentiment Guide](SENTIMENT.md)          |
| **Blocked Trade** | Your trade might violate the `RISK_PROFILE`. Use `conservative` for safety. | [README.md](../README.md)                |
| **Python Errors** | Run `pip install -r requirements.txt` to ensure dependencies are met.       | [requirements.txt](../requirements.txt)  |

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

### Execution tool errors (MCP)

- **`paper_engine_missing`**
  - Meaning: `PAPER_MODE=true` but the paper engine failed to initialize.
  - Fix: check `data/paper.db` is writable; restart the process.
- **`paper_mode_not_supported`**
  - Meaning: The tool has no paper-mode branch (`transfer_eth`, the private-WS tools).
  - Fix: these only work when `PAPER_MODE=false` and live execution is allowed.
- **`paper_price_required`**
  - Meaning: `place_cex_order` in paper mode with no `price` given, and the market-data bus has
    no usable price for the symbol.
  - Fix: pass `price` explicitly, or call `get_crypto_price`/`fetch_ohlcv` first to confirm data
    is flowing for that symbol.
- **`execution_mode_blocked`**
  - Meaning: The requested tool is blocked by `EXECUTION_MODE` (`dex`/`cex`/`hybrid`) for that venue.
  - Fix: set `EXECUTION_MODE` to allow the venue you want, or use the corresponding venue tool.
- **`invalid_price`**
  - Meaning: `place_cex_order` was given a non-positive or non-numeric `price`.
  - Fix: pass a positive numeric price, or omit it for a paper market order.
- **`timeout`**
  - Meaning: `wait_for_cex_order` did not see a terminal order state within `timeout_sec`.
  - Fix: poll again with `get_cex_order`, or raise `timeout_sec`.
- **`cex_error`**, **`execution_error`**, **`transfer_error`**
  - Meaning: a generic, venue-specific failure — a real exchange/RPC error, OR live execution
    was refused by `PAPER_MODE`/`LIVE_TRADING_ENABLED`/`TRADING_HALTED`/`EXECUTION_MODE`
    (`_require_live_allowed` in `app/tools/execution.py`). **The specific reason is not included
    in the JSON response** (the message is a fixed string, e.g. "Exchange operation failed.");
    it is only visible in the server's process log (the exception is logged there).
  - Fix: in paper mode this should never fire for a live-gating reason — if it does, check
    `PAPER_MODE`. In live mode, check the server log for the underlying exception, then verify
    `LIVE_TRADING_ENABLED`, `TRADING_HALTED`, `EXECUTION_MODE`, and policy allowlists.
- **`rate_limited`**
  - Meaning: the per-tool (or default) rate limit was exceeded for the current 60s window.
  - Fix: slow down or batch calls; raise `RATE_LIMIT_DEFAULT_PER_MIN`, `RATE_LIMIT_EXECUTION_PER_MIN`,
    or `RATE_LIMIT_<TOOL>_PER_MIN`.

### Policy engine (allowlists / limits, live orders only)

`ALLOW_CHAINS`, `ALLOW_TOKENS`, `ALLOW_EXCHANGES`, `ALLOW_CEX_SYMBOLS`, `ALLOW_CEX_MARKET_TYPES`,
`ALLOW_ROUTERS` and the `MAX_*` limits are enforced by `policy_engine.py` on the **live** order
path only (`place_cex_order`'s and `swap_tokens`' live branches); paper orders are not filtered
by them. A violation raises inside the tool and is currently folded into the tool's generic
`cex_error`/`execution_error` code above (see that entry) rather than a distinct
`chain_not_allowed`/`token_not_allowed`-style code — check the server log for the specific
policy rule that fired.

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
`docs/ARCHITECTURE.md#approval-gate` for the full approval flow and its current cross-process
limitation.

| Code       | HTTP status | Meaning                                                                                                                            | Fix                                                                                                         |
| :--------- | :---------- | :--------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------- |
| `AUTH_604` | 403         | Caller may not approve/reject this proposal (no admin session and no/wrong `confirm_token`).                                       | Sign in as an admin, or supply the proposal's `confirm_token`.                                              |
| `EXEC_308` | 409         | Proposal was already executed.                                                                                                     | Nothing further happens; propose a new trade if needed.                                                     |
| `EXEC_309` | 404         | Proposal does not exist **in this server process** (see the approval-gate limitation).                                             | Confirm you are calling the same process that created the proposal; otherwise the agent must propose again. |
| `EXEC_310` | 410         | Proposal expired (proposals have a short TTL by design).                                                                           | Ask the agent to propose again.                                                                             |
| `EXEC_311` | 409         | Proposal was cancelled/rejected earlier, or already confirmed (approvals are single-use).                                          | Propose again if a new trade is wanted.                                                                     |
| `EXEC_312` | 422         | Proposal payload is malformed/incomplete, or the engine refused the resulting order (order refusals are not recorded as executed). | Ask the agent to propose again with a valid payload.                                                        |

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
