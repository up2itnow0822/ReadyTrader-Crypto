import os
import re
import threading
import time
from collections.abc import Collection
from typing import Any, Dict, List, Optional, Tuple

import requests

from .sentiment import MIN_DIRECTIONAL, MIN_TEXTS, SentimentReading, score_texts

# Optional imports for Real APIs
try:
    import tweepy
except ImportError:
    tweepy = None

try:
    import praw
except ImportError:
    praw = None

try:
    from newsapi import NewsApiClient
except ImportError:
    NewsApiClient = None

try:
    import feedparser
except ImportError:
    feedparser = None


def get_fear_greed_index() -> str:
    """
    Fetch the Crypto Fear & Greed Index from alternative.me.
    """
    try:
        url = "https://api.alternative.me/fng/"
        response = requests.get(url, timeout=10)
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            item = data["data"][0]
            value = item["value"]
            classification = item["value_classification"]
            return f"Fear & Greed Index: {value} ({classification})"
        return "Error: Could not retrieve Fear & Greed Index."
    except Exception as e:
        return f"Error fetching Fear & Greed Index: {str(e)}"


def get_market_news() -> str:
    """
    Fetch aggregated crypto market news using CryptoPanic API if available.
    """
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        return "Market News Unavailable: CRYPTOPANIC_API_KEY not configured. Set this environment variable to enable real-time crypto news."

    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&kind=news&filter=hot"
        response = requests.get(url, timeout=10)
        data = response.json()

        if "results" in data:
            headlines = [f"{i + 1}. {p['title']}" for i, p in enumerate(data["results"][:5])]
            return "CryptoPanic News:\n" + "\n".join(headlines)
        return "Error: No news found via CryptoPanic."
    except Exception as e:
        return f"Error fetching CryptoPanic news: {str(e)}"


def fetch_rss_news(symbol: str = "") -> str:
    """
    Fetch free market news from RSS feeds (CoinDesk, Cointelegraph).
    This provides 'Free' news without requiring API keys.
    """
    if not feedparser:
        return "Error: feedparser library not installed. Cannot fetch RSS news."

    feeds = [("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("Cointelegraph", "https://cointelegraph.com/rss")]

    all_headlines = []

    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            # Take top 3 from each
            count = 0
            for entry in feed.entries:
                if count >= 3:
                    break
                # If symbol is provided, check if it's in the title/summary (case-insensitive)
                if symbol and symbol.lower() not in entry.title.lower() and symbol.lower() not in entry.summary.lower():
                    continue

                all_headlines.append(f"{entry.title} ({name})")
                count += 1
        except Exception as e:
            all_headlines.append(f"Error fetching {name} feed: {str(e)}")

    if not all_headlines:
        if symbol:
            return f"No RSS news found matching '{symbol}' in recent feeds."
        return "No RSS news found."

    return "Market News (Free RSS):\n" + "\n".join([f"{i + 1}. {h}" for i, h in enumerate(all_headlines[:6])])


# Same asset under another ticker (mirrors exchange_provider's aliases).
ASSET_ALIASES = {"XBT": "BTC"}


def base_asset(symbol: str) -> str:
    """
    'BTC/USDT', 'btc-usd', 'BTC/USDT:USDT', 'BTCUSDT', 'XBT/USD' -> 'BTC'. Sentiment is tracked per asset, not per pair.

    Without a separator only a USDT/USDC suffix is stripped; other concatenated quotes
    ('BTCUSD', 'ETHBTC') are ambiguous with real tickers ('CRVUSD', 'WBTC') and are left as given.
    """
    asset = re.split(r"[/\-_:\s]", str(symbol or "").strip().upper(), maxsplit=1)[0]
    if len(asset) > 4 and asset.endswith(("USDT", "USDC")):
        asset = asset[:-4]
    return ASSET_ALIASES.get(asset, asset)


class SentimentCache:
    """Readings per base asset. Ages use the monotonic clock so a wall-clock step cannot pin or expire an entry."""

    def __init__(self, ttl: int = 3600):
        self.cache = {}
        self.ttl = ttl
        self._lock = threading.RLock()

    def _fresh(self, entry: Dict[str, Any]) -> bool:
        return time.monotonic() - entry["time"] < self.ttl

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            key = base_asset(symbol)
            entry = self.cache.get(key)
            if entry and self._fresh(entry):
                return entry
            self.cache.pop(key, None)
            return None

    def set(self, symbol: str, reading: SentimentReading, configured: bool = True, sources: Collection[str] = ()):
        with self._lock:
            self.cache = {key: entry for key, entry in self.cache.items() if self._fresh(entry)}
            self.cache[base_asset(symbol)] = {
                "time": time.monotonic(),
                "reading": reading,
                "configured": configured,
                "sources": frozenset(sources),
            }

    def set_preserving_bearish(
        self,
        symbol: str,
        reading: SentimentReading,
        configured: bool,
        sources: Collection[str],
        source_error: bool,
    ) -> Optional[Dict[str, Any]]:
        """Atomically store a refresh, or return the bearish reading a degraded refresh must hold."""
        with self._lock:
            key = base_asset(symbol)
            previous = self.cache.get(key)
            if previous and not self._fresh(previous):
                self.cache.pop(key, None)
                previous = None
            if previous and previous["reading"].score < 0:
                held = previous["reading"]
                lost_source = not previous.get("sources", frozenset()).issubset(sources)
                degraded = source_error or lost_source or not reading.sufficient or reading.texts * 2 < held.texts
                if degraded:
                    return previous
            self.cache = {cached_key: entry for cached_key, entry in self.cache.items() if self._fresh(entry)}
            self.cache[key] = {
                "time": time.monotonic(),
                "reading": reading,
                "configured": configured,
                "sources": frozenset(sources),
            }
            return None

    def age_seconds(self, entry: Dict[str, Any]) -> int:
        return int(time.monotonic() - entry["time"])


_sentiment_cache = SentimentCache()


def get_cached_sentiment(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the fresh cached entry ({reading, configured, age_seconds}) for the symbol's base asset, or None."""
    entry = _sentiment_cache.get(symbol)
    if entry is None:
        return None
    return {"reading": entry["reading"], "configured": entry["configured"], "age_seconds": _sentiment_cache.age_seconds(entry)}


def get_cached_sentiment_score(symbol: str) -> float:
    """Return the cached sentiment score in [-1, 1], or 0.0 (neutral) if missing or stale."""
    entry = _sentiment_cache.get(symbol)
    return entry["reading"].score if entry else 0.0


# A source is "ok" (it answered, possibly with nothing), "not_configured", or "error".
SourceResult = Tuple[List[str], str, str]


def _recent_tweets(asset: str) -> SourceResult:
    bearer = os.getenv("TWITTER_BEARER_TOKEN")
    if not (bearer and tweepy):
        return [], "Twitter: API Key missing.", "not_configured"
    try:
        client = tweepy.Client(bearer_token=bearer)
        tweets = client.search_recent_tweets(query=f"{asset} -is:retweet lang:en", max_results=10)
        texts = [t.text for t in tweets.data or []]
        if not texts:
            return [], "Twitter (Real): No recent tweets found.", "ok"
        preview = " | ".join(t[:50] + "..." for t in texts[:2])
        return texts, f"Twitter (Real): Found {len(texts)} recent tweets. Preview: {preview}", "ok"
    except Exception as e:
        return [], f"Twitter Error: {str(e)}", "error"


def _recent_reddit_titles(asset: str) -> SourceResult:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not (client_id and client_secret and praw):
        return [], "Reddit: API Keys missing.", "not_configured"
    try:
        reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent="agent_zero_crypto_bot/1.0")
        titles = [p.title for p in reddit.subreddit("cryptocurrency").search(asset, limit=5, time_filter="day")]
        if not titles:
            return [], "Reddit (Real): No recent posts found.", "ok"
        return titles, f"Reddit (Real): Found {len(titles)} posts in r/CC. Preview: {' | '.join(titles[:2])}", "ok"
    except Exception as e:
        return [], f"Reddit Error: {str(e)}", "error"


def _describe(reading: SentimentReading) -> str:
    neutral = reading.texts - reading.bullish - reading.bearish
    mix = f"{reading.bearish} bearish / {reading.bullish} bullish / {neutral} neutral of {reading.texts} texts"
    if not reading.sufficient:
        return f"0.00 (not a measurement - only {reading.texts} distinct texts, need {MIN_TEXTS})"
    if reading.score == 0.0 and reading.bullish != reading.bearish:
        return f"+0.00 on [-1, +1] (no consensus - {mix}; need {MIN_DIRECTIONAL} directional texts to call a direction)"
    return f"{reading.score:+.2f} on [-1, +1] ({mix})"


def analyze_social_sentiment(symbol: str) -> str:
    """
    Score recent X and Reddit text about the symbol's base asset and cache the result for the
    Risk Guardian. Every call refreshes; the trade check reads the cached score.
    """
    asset = base_asset(symbol)
    if not asset:
        return "Social Sentiment Unavailable: no symbol given."

    tweets, twitter_result, twitter_state = _recent_tweets(asset)
    titles, reddit_result, reddit_state = _recent_reddit_titles(asset)
    states = (twitter_state, reddit_state)
    sources = frozenset(name for name, texts in (("twitter", tweets), ("reddit", titles)) if texts)
    configured = any(state != "not_configured" for state in states)
    reading = score_texts(tweets + titles)

    if configured:
        lines = [twitter_result, reddit_result]
    else:
        lines = [
            f"Social Sentiment Unavailable for {asset}: No sentiment APIs configured.",
            "To enable real-time sentiment analysis:",
            "1. X (Twitter): Get a Bearer Token from https://developer.x.com/ and set TWITTER_BEARER_TOKEN",
            "2. Reddit: Create an app at https://www.reddit.com/prefs/apps and set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET",
        ]

    # A degraded refresh must never relax the gate. A bearish reading is replaced only by a clean
    # measurement (no source failed) built on at least half as much text - or by expiry.
    previous = _sentiment_cache.set_preserving_bearish(asset, reading, configured, sources=sources, source_error="error" in states)
    if previous:
        held = previous["reading"]
        age_min = _sentiment_cache.age_seconds(previous) // 60
        lines.append(f"This refresh is degraded ({reading.texts} texts), so it does not replace the reading from {age_min} min ago.")
        lines.append(f"Sentiment score in force: {_describe(held)}. It expires one hour after it was taken.")
        return "\n".join(lines)

    if configured:
        lines.append(f"Sentiment score: {_describe(reading)}")
    else:
        lines.append("NOTE: Until a source is configured the Falling Knife check has no data and treats sentiment as neutral (0.0).")
    return "\n".join(lines)


def fetch_financial_news(symbol: str) -> str:
    """
    Fetch financial news using NewsAPI.
    """
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key or not NewsApiClient:
        return (
            f"Financial News Unavailable for {symbol}: NewsAPI not configured.\n"
            "To enable real financial news feeds, get an API key from https://newsapi.org/ and set NEWSAPI_KEY in your .env file."
        )

    try:
        newsapi = NewsApiClient(api_key=api_key)
        # Search for symbol + crypto or finance
        articles = newsapi.get_everything(q=f"{symbol} crypto", language="en", sort_by="relevancy", page_size=3)

        if articles["status"] == "ok" and articles["articles"]:
            headlines = [f"{i + 1}. {a['title']} ({a['source']['name']})" for i, a in enumerate(articles["articles"])]
            return "Financial Headlines (NewsAPI):\n" + "\n".join(headlines)
        return "NewsAPI: No articles found."
    except Exception as e:
        return f"NewsAPI Error: {str(e)}"
