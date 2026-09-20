# Market Intelligence & Sentiment Guide

ReadyTrader-Crypto empowers AI agents with both "Hands" (execution) and "Eyes" (intelligence). This document explains how to configure and use the various sentiment and news feeds available.

## 🌟 Overview of Sentiment Sources

| Source                 | Level     | Cost           | Required Credentials | Feature                                               |
| :--------------------- | :-------- | :------------- | :------------------- | :---------------------------------------------------- |
| **RSS Market News**    | Basic     | Free           | None                 | General market awareness from CoinDesk/Cointelegraph. |
| **Fear & Greed Index** | Basic     | Free           | None                 | Overall market sentiment (Alternative.me).            |
| **CryptoPanic**        | Pro       | Free/Paid      | API Key              | Aggregated hot news across the industry.              |
| **X (Twitter)**        | Social    | Free (Limited) | Bearer Token         | Real-time social buzz for specific tokens.            |
| **Reddit**             | Community | Free           | Client ID + Secret   | Deep-dives into subreddit discussions.                |
| **NewsAPI**            | Financial | Free (Trial)   | API Key              | High-tier financial reporting (Bloomberg, Reuters).   |

______________________________________________________________________

## 🛠️ Configuration Instructions

### 1. Free RSS News & Fear/Greed

These work **out-of-the-box** with zero configuration. AI agents will automatically fallback to these if no paid keys are found.

### 2. CryptoPanic (Highly Recommended)

CryptoPanic is the gold standard for aggregated crypto news.

1. Sign up at [CryptoPanic Developers](https://cryptopanic.com/developers/api/).
1. Copy your **API Token**.
1. Add it to your `.env`:
   ```bash
   CRYPTOPANIC_API_KEY=your_token_here
   ```

### 3. X / Twitter (Social Volume)

To see what people are saying about a specific token ($BTC, $SOL):

1. Sign up for a Developer Account at [X Developer Portal](https://developer.x.com/).
1. Create a **Project** and an **App**.
1. Generate an **App-only Bearer Token**.
1. Add it to your `.env`:
   ```bash
   TWITTER_BEARER_TOKEN=your_bearer_token_here
   ```

### 4. Reddit Sentiment

Great for detecting "FOMO" or "FUD" in `/r/cryptocurrency`.

1. Go to [Reddit App Preferences](https://www.reddit.com/prefs/apps).
1. Click "Create another app..." at the bottom.
1. Select **script**. Name it "ReadyTraderAgent".
1. Redirect URI can be `http://localhost:8080`.
1. Save and copy your **Client ID** (under the name) and **Client Secret**.
1. Add them to your `.env`:
   ```bash
   REDDIT_CLIENT_ID=your_client_id
   REDDIT_CLIENT_SECRET=your_client_secret
   ```

### 5. NewsAPI (Institutional News)

For high-signal news from major financial outlets.

1. Get a key at [NewsAPI.org](https://newsapi.org/).
1. Add it to your `.env`:
   ```bash
   NEWSAPI_KEY=your_newsapi_key_here
   ```

______________________________________________________________________

## 🤖 Agent Tool Reference

AI Agents can query these feeds using the following tools:

- `get_free_news(symbol="")`: Aggregates RSS feeds. Best for overall context.
- `get_sentiment()`: Returns the Fear & Greed Index.
- `get_social_sentiment(symbol)`: Queries X and Reddit.
- `get_financial_news(symbol)`: Queries NewsAPI.
- `get_news()`: Queries CryptoPanic.

______________________________________________________________________

## 🛡️ How the Social Sentiment Score Works

`get_social_sentiment(symbol)` is the only feed that produces a number, and that number is what the Risk Guardian's **Falling Knife** rule reads.

1. Up to 10 recent tweets and 5 `/r/cryptocurrency` post titles are fetched for the symbol's base asset (`BTC/USDT`, `btc-usd`, `BTCUSDT`, `XBT/USD` and `BTC` all mean `BTC`).
1. Each distinct text is classified bullish, bearish or neutral locally (`intelligence/sentiment.py`). No model, API key or network call is involved in scoring, so the same texts always give the same score.
1. The score is the bull-bear spread over the texts that take a direction: `(bullish - bearish) / (bullish + bearish)`, from `-1.0` to `+1.0`. With fewer than 4 directional texts (or less than a quarter of the sample) there is no consensus and the score is `0.0`, except when at least one text prints an 8%+ drop (`-10%`, `down 11%`): that text is bearish even without a lexicon panic word, and three directional texts are then enough. Promo copy such as ` - 92% WIN RATE` does not count (the minus must sit on the number). Ordinary red-day prints (~3–6%) stay below the line.
1. The reading is cached per base asset for one hour. `validate_trade_risk` reads the cache; it never fetches.

`validate_trade_risk` blocks a **BUY** when the score is below `-0.5`: enough texts take a direction (4, or 3 when an 8%+ drop is present) and bearish ones outnumber bullish ones by more than three to one. Sells are never blocked by sentiment.

### Why a market-only vocabulary

Classification uses VADER's rule engine (negation, intensifiers, capitals) over a market-only vocabulary rather than general-English sentiment. On a ticker search, general sentiment misfires in both directions: "stop loss", "risk", "Fear & Greed Index", "hard fork" and "max pain" read as negative, while giveaway spam and sarcasm ("Great, another 20% dump. Love it.") read as positive. Here only words that state a violent move or market distress count (crash, plunge, dump, capitulation, insolvent, bearish / rally, surge, breakout, bullish). Everything else is neutral and is ignored by the score, so data bots and promo posts neither trip the rule nor mask a panic.

Deliberately left out: topic words with no direction (liquidation, delisting, lawsuit, exploit, hack, scam, fraud, bankruptcy), words that are mostly history or jokes ("bitcoin is dead (again)", "dead cat bounce", "the 2022 collapse"), and the phrase "pump and dump". Texts about the past (anniversary, documentary, "years ago") are scored neutral. Scam warnings, security write-ups and anniversaries run every day on a flat market.

### How well it works

Measured on 86 simulated `BTC` searches (15 texts each) written by models that had not seen the vocabulary. They are simulations, not market data.

- The last 40 feeds were scored once, with the configuration frozen beforehand: **6 of 12 crashes blocked; 2 of 28 other feeds blocked**, both written to be alarming without a crash (a crash anniversary, an altcoin imploding while BTC sat flat).
- Across all 86 feeds with the code as merged: **12 of 22 crashes blocked, 0 of 50 calm, red, green or contested days blocked**, and 1 of 14 alarming-but-fine feeds (the altcoin one).

So the rule is precise and only moderately sensitive: about half of crashes are described in words it does not know ("risk off", "withdrawals frozen", "sell everything") unless they also print an 8%+ drop. `tests/fixtures/sentiment_feeds.json` pins the in-repo sample. After the Phase 1 large-drop cue, the frozen train/held-out crash misses (`crash-05`, `crash-02`) block; the altcoin implosion while BTC sits flat remains a `known_limit`.

### When there is no measurement

`validate_trade_risk` reports what the rule worked from in its `sentiment.status` field:

| status              | meaning                                                                     | score    |
| :------------------ | :-------------------------------------------------------------------------- | :------- |
| `ok`                | At least 5 texts were scored within the last hour (the score may be `0.0`). | measured |
| `no_data`           | `get_social_sentiment` has not been called for this asset in the last hour. | `0.0`    |
| `not_configured`    | No X or Reddit credentials are set.                                         | `0.0`    |
| `insufficient_data` | Fewer than 5 distinct texts came back.                                      | `0.0`    |

Only `ok` is a measurement; in the other three cases the Falling Knife rule cannot fire, and a `hint` says why.

A degraded refresh never relaxes the rule. Only providers that supplied usable nonblank text count as contributors, and only loss or failure of those contributors degrades a later refresh. A degraded refresh may replace the held reading when it has a sufficient, more bearish score; the cache records its actual current contributors separately while retaining earlier contributors as recovery guards. Those guards keep later degraded refreshes from relaxing the tighter reading until the missing contributors recover. Otherwise replacement requires a clean measurement built on at least half as much text, or expiry one hour after the reading was taken. The reverse does not hold: a neutral or bullish reading is always replaced, so a stale upbeat score never passes as a live measurement.

### Limits worth knowing

- The Risk Guardian is advisory: the rule only acts when the agent calls `get_social_sentiment(symbol)` and then `validate_trade_risk(...)` before trading.
- Fifteen texts is a small sample, and anyone can post. Treat the rule as a circuit breaker for broad, plain-spoken panic, not a forecast. Repeated identical texts count once.
- Negation more than a few words from its target is missed, and bad news about another asset counts if it uses this vocabulary.
- `MIN_DIRECTIONAL` and `LARGE_DROP_PCT` are the sensitivity knobs and live with the vocabulary in one file. Every `validate_trade_risk` response carries the score and counts it used, so paper-trading logs can calibrate it. Add fresh feeds to the fixture before tuning against it.
- Tweet and post previews returned to the agent are untrusted text.
