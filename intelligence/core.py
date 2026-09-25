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


class SourceError(Exception):
    """A news or sentiment source that could not answer: `code` is not_configured (a key is missing)
    or source_unavailable (it failed). The MCP tools return it as an error, never as news."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fear_greed_index() -> str:
    """The Crypto Fear & Greed Index from alternative.me. Raises SourceError when it cannot be read."""
    try:
        response = requests.get("https://api.alternative.me/fng/", timeout=10)
        data = response.json()
        item = data["data"][0]
        return f"Fear & Greed Index: {item['value']} ({item['value_classification']})"
    except Exception as e:
        raise SourceError("source_unavailable", f"The Fear & Greed Index could not be read: {type(e).__name__}") from e


def get_fear_greed_index() -> str:
    """String form of fear_greed_index() (kept for existing callers): a failure comes back as text."""
    try:
        return fear_greed_index()
    except SourceError as e:
        return f"Error: {e.message}"


def market_news() -> str:
    """CryptoPanic hot news. Raises SourceError when not configured or when CryptoPanic fails."""
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        raise SourceError("not_configured", "Market news needs CRYPTOPANIC_API_KEY (https://cryptopanic.com/developers/api/).")
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&kind=news&filter=hot"
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception as e:
        raise SourceError("source_unavailable", f"CryptoPanic did not answer: {type(e).__name__}") from e
    if "results" not in data:
        raise SourceError("source_unavailable", "CryptoPanic answered without results.")
    headlines = [f"{i + 1}. {p['title']}" for i, p in enumerate(data["results"][:5])]
    return "CryptoPanic News:\n" + "\n".join(headlines) if headlines else "CryptoPanic: no hot news right now."


def get_market_news() -> str:
    """String form of market_news() (kept for existing callers): a failure comes back as text."""
    try:
        return market_news()
    except SourceError as e:
        return f"Market News Unavailable: {e.message}"


def fetch_rss_news(symbol: str = "") -> str:
    """String form of rss_news() (kept for existing callers): a failure comes back as text."""
    try:
        return rss_news(symbol)
    except SourceError as e:
        return f"Error: {e.message}"


def rss_news(symbol: str = "") -> str:
    """
    Fetch free market news from RSS feeds (CoinDesk, Cointelegraph); no API key needed. Raises
    SourceError(source_unavailable) when no feed could be read.
    """
    if not feedparser:
        raise SourceError("source_unavailable", "feedparser is not installed; RSS news cannot be read.")

    feeds = [("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("Cointelegraph", "https://cointelegraph.com/rss")]

    all_headlines = []
    failed = []

    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            if getattr(feed, "bozo", False) and not feed.entries:
                raise ValueError(str(getattr(feed, "bozo_exception", "unreadable feed")))
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
            failed.append(f"{name}: {type(e).__name__}")

    if len(failed) == len(feeds):
        raise SourceError("source_unavailable", "No RSS feed could be read (" + "; ".join(failed) + ").")
    if failed:
        all_headlines.append("Unavailable feed(s): " + ", ".join(failed))

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
            current_sources = frozenset(sources)
            self.cache[base_asset(symbol)] = {
                "time": time.monotonic(),
                "reading": reading,
                "configured": configured,
                "sources": current_sources,
                "guard_sources": current_sources,
            }

    def set_preserving_bearish(
        self,
        symbol: str,
        reading: SentimentReading,
        configured: bool,
        sources: Collection[str],
        errored_sources: Collection[str],
    ) -> Optional[Dict[str, Any]]:
        """Atomically store a refresh, or return the bearish reading a degraded refresh must hold."""
        with self._lock:
            key = base_asset(symbol)
            current_sources = frozenset(sources)
            guard_sources = current_sources
            previous = self.cache.get(key)
            if previous and not self._fresh(previous):
                self.cache.pop(key, None)
                previous = None
            if previous and previous["reading"].score < 0:
                held = previous["reading"]
                previous_guard_sources = previous.get("guard_sources", previous.get("sources", frozenset()))
                lost_source = not previous_guard_sources.issubset(current_sources)
                contributing_source_error = bool(previous_guard_sources.intersection(errored_sources))
                degraded = contributing_source_error or lost_source or not reading.sufficient or reading.texts * 2 < held.texts
                more_bearish = reading.sufficient and reading.score < held.score
                if degraded and not more_bearish:
                    return previous
                if degraded:
                    # The new reading came only from current_sources. Keep earlier contributors
                    # as recovery guards so another degraded refresh cannot immediately relax it.
                    guard_sources = previous_guard_sources.union(current_sources)
            self.cache = {cached_key: entry for cached_key, entry in self.cache.items() if self._fresh(entry)}
            self.cache[key] = {
                "time": time.monotonic(),
                "reading": reading,
                "configured": configured,
                "sources": current_sources,
                "guard_sources": guard_sources,
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
    return social_sentiment_report(symbol)[0]


def social_sentiment_report(symbol: str) -> Tuple[str, Dict[str, str]]:
    """analyze_social_sentiment, plus each source's state this refresh: {"twitter": ..., "reddit": ...}
    with "ok" (it answered, possibly with nothing), "not_configured" or "error"."""
    asset = base_asset(symbol)
    if not asset:
        return "Social Sentiment Unavailable: no symbol given.", {}

    tweets, twitter_result, twitter_state = _recent_tweets(asset)
    titles, reddit_result, reddit_state = _recent_reddit_titles(asset)
    states = (twitter_state, reddit_state)
    source_states = {"twitter": twitter_state, "reddit": reddit_state}
    sources = frozenset(name for name, texts in (("twitter", tweets), ("reddit", titles)) if any(isinstance(text, str) and text.strip() for text in texts))
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

    # A degraded refresh must never relax the gate, but sufficient evidence that is more bearish
    # may tighten it. Only failures from sources that contributed to the held reading count.
    errored_sources = frozenset(name for name, state in zip(("twitter", "reddit"), states) if state == "error")
    previous = _sentiment_cache.set_preserving_bearish(asset, reading, configured, sources=sources, errored_sources=errored_sources)
    if previous:
        held = previous["reading"]
        age_min = _sentiment_cache.age_seconds(previous) // 60
        lines.append(f"This refresh is degraded ({reading.texts} texts), so it does not replace the reading from {age_min} min ago.")
        lines.append(f"Sentiment score in force: {_describe(held)}. It expires one hour after it was taken.")
        return "\n".join(lines), source_states

    if configured:
        lines.append(f"Sentiment score: {_describe(reading)}")
    else:
        lines.append("NOTE: Until a source is configured the Falling Knife check has no data and treats sentiment as neutral (0.0).")
    return "\n".join(lines), source_states


def financial_news(symbol: str) -> str:
    """NewsAPI headlines for the symbol. Raises SourceError when not configured or when NewsAPI fails."""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key or not NewsApiClient:
        raise SourceError("not_configured", "Financial news needs NEWSAPI_KEY (https://newsapi.org/).")
    try:
        newsapi = NewsApiClient(api_key=api_key)
        articles = newsapi.get_everything(q=f"{symbol} crypto", language="en", sort_by="relevancy", page_size=3)
    except Exception as e:
        raise SourceError("source_unavailable", f"NewsAPI did not answer: {type(e).__name__}") from e
    if articles.get("status") != "ok":
        raise SourceError("source_unavailable", f"NewsAPI answered status {articles.get('status')!r}.")
    if not articles.get("articles"):
        return "NewsAPI: No articles found."
    headlines = [f"{i + 1}. {a['title']} ({a['source']['name']})" for i, a in enumerate(articles["articles"])]
    return "Financial Headlines (NewsAPI):\n" + "\n".join(headlines)


def fetch_financial_news(symbol: str) -> str:
    """String form of financial_news() (kept for existing callers): a failure comes back as text."""
    try:
        return financial_news(symbol)
    except SourceError as e:
        return f"Financial News Unavailable for {symbol}: {e.message}"
