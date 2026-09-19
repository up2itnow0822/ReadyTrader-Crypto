## ReadyTrader-Crypto — Exchange Capabilities (Phase 2A)

This is a **truthful capability matrix** intended to reduce surprises. “Supported” means we have a clear tool path, tests, and documented behavior. “Experimental” means it may work, but behavior varies by exchange/market type.

### Legend

- **Supported**: expected to work reliably; covered by unit tests where possible.
- **Experimental**: best-effort; exchange-specific quirks likely.
- **N/A**: not implemented.

### Public market data

ReadyTrader-Crypto can fetch public data via:

- **CCXT REST** (broad exchange coverage; configured via `MARKETDATA_EXCHANGES`)
- **Public websocket tickers (opt-in)**: Binance / Coinbase / Kraken, wired as the `exchange_ws`
  `MarketDataBus` provider (`marketdata/ws_streams.py`); there is no MCP tool to start/stop this
  feed. Check what is actually feeding a symbol with `GET /api/marketdata/status` (HTTP,
  `api_server.py`) or by inspecting `get_crypto_price`'s `source` field.

### Private account/order updates

ReadyTrader-Crypto supports:

- **Binance user stream (websocket)**: best-effort private updates for spot + swap
- **Polling fallback (Phase 2)** for other exchanges: periodically fetch open orders and emit changes (not realtime)

______________________________________________________________________

## Capability matrix (high level)

| Exchange     | Spot (CEX tools) |                 Swap/Futures (CEX tools) | Public WS ticker |     Private updates | Notes                              |
| ------------ | ---------------- | ---------------------------------------: | ---------------: | ------------------: | ---------------------------------- |
| **Binance**  | Supported        | Supported (swap) / Experimental (future) |        Supported |      Supported (WS) | Private WS uses listenKey; opt-in. |
| **Coinbase** | Supported        |                                      N/A |        Supported | Experimental (poll) | Private updates via poll fallback. |
| **Kraken**   | Supported        |                             Experimental |        Supported | Experimental (poll) | Private updates via poll fallback. |
| **Bybit**    | Experimental     |                             Experimental |  N/A (REST only) | Experimental (poll) | CCXT REST only in this repo.       |
| **OKX**      | Experimental     |                             Experimental |  N/A (REST only) | Experimental (poll) | CCXT REST only in this repo.       |
| **KuCoin**   | Experimental     |                             Experimental |  N/A (REST only) | Experimental (poll) | CCXT REST only in this repo.       |

______________________________________________________________________

## Tool coverage (CEX)

### Core execution

- `place_cex_order(...)`: Supported (spot widely; derivatives depend on exchange + `market_type`)
- `cancel_cex_order(...)`: Supported
- `get_cex_order(...)`: Supported
- `wait_for_cex_order(...)`: Supported (polling helper; useful even without private WS)

### Account and lifecycle

- `get_cex_balance(...)`: Supported (auth required)
- `list_cex_open_orders(...)`: Supported (auth required)
- `list_cex_orders(...)`: Supported (auth required)
- `get_cex_my_trades(...)`: Supported (auth required)
- `cancel_all_cex_orders(...)`: Capability-gated (`cancelAllOrders`)
- `replace_cex_order(...)`: Capability-gated (`editOrder`)

______________________________________________________________________

## Operator notes

### Market type (spot/swap/future)

ReadyTrader-Crypto uses `market_type` to configure CCXT defaultType. Exchanges vary; if you see symbol mismatches, use `get_cex_capabilities(exchange, symbol, market_type)` to inspect the resolved symbol/market metadata.

### Private updates (poll fallback)

For exchanges without private websocket support in this repo:

- `start_cex_private_ws(exchange=..., market_type=...)` starts a **poller** (not realtime).
- Tune with: `CEX_PRIVATE_POLL_INTERVAL_SEC` (default 2.0 seconds).
- Polling is subject to exchange rate limits; use sparingly and prefer `wait_for_cex_order(...)` for one-off waits.
