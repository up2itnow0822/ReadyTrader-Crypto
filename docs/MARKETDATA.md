## ReadyTrader-Crypto Market Data (Phase 3)

ReadyTrader-Crypto routes market data via `MarketDataBus` and exposes it to agents through the
MCP tools `get_crypto_price()` and `fetch_ohlcv()`. `MarketDataBus.fetch_ticker()` is the
internal Python method those tools call; it is not itself an MCP tool.

### Goals

- Prefer **fresh** realtime data (websocket-first) when available
- Fall back safely to **ingested feeds** or **CCXT REST** when needed
- Provide clear introspection: **what source was used and why**
- Optional operator guardrails: **stale/outlier detection** and **fail-closed** mode

______________________________________________________________________

## Provider IDs (defaults)

ReadyTrader-Crypto typically wires providers in this order:

- `exchange_ws` (public websocket tickers; opt-in)
- `ingest` (user-provided snapshots via the internal `ingest_ticker` / `ingest_ohlcv` store APIs — not MCP tools)
- `ccxt_rest` (CCXT REST fallback)

Plugins (Phase 3C) can add additional providers.

______________________________________________________________________

## Freshness + priority selection (Phase 3A)

The router scores sources using:

- **priority** (lower is better)
- **freshness** (ticker age in ms)
- **sanity checks** (non-negative, bid/ask ordering, etc.)

`MarketDataBus.fetch_ticker()` (the internal method `get_crypto_price` calls) returns:

- `source`: chosen provider id
- `ticker`: normalized ticker payload
- `meta`: decision info (`age_ms`, `stale`, `candidates`, etc.)

### Env tuning

- `MARKETDATA_PROVIDER_PRIORITY_JSON`
  - JSON map of provider priorities (lower = higher priority)
  - Example:
    - `{\"exchange_ws\":0,\"ingest\":1,\"ccxt_rest\":2}`
- `MARKETDATA_MAX_AGE_MS`
  - default staleness threshold in ms (default 30000)
- `MARKETDATA_MAX_AGE_MS_<PROVIDERID>`
  - per-provider override (example: `MARKETDATA_MAX_AGE_MS_EXCHANGE_WS=15000`)

______________________________________________________________________

## Outlier/stale guardrails (Phase 3D)

Ticker outliers are detected using a cheap comparison vs the last good value:

- `MARKETDATA_OUTLIER_MAX_PCT` (default 20.0)
- `MARKETDATA_OUTLIER_WINDOW_MS` (default 10000)

Optional fail-closed mode:

- `MARKETDATA_FAIL_CLOSED=true`
  - If enabled, `MarketDataBus.fetch_ticker()` raises when the best available data is stale or an outlier.
  - This is intended for operator-controlled deployments.

______________________________________________________________________

## Bring your own feed (Phase 3C)

You can add external providers at startup:

- `MARKETDATA_PLUGINS_JSON`

Example (offline JSON file feed):

```json
[
  {
    "class": "marketdata.plugin_examples:StaticJsonFileProvider",
    "provider_id": "file_feed",
    "kwargs": { "path": "/data/feed.json" }
  }
]
```
