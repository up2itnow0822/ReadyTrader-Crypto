"""
Falling Knife gate, end to end: fetched text -> sentiment score -> RiskGuardian verdict.

The guardian rule itself is covered in test_risk.py with hand-fed scores. These tests cover the
producer side: the score must come from the fetched text, be able to go negative, and reach the
trade check under the symbol the trade uses.
"""

import json
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import intelligence.core as core
from app.core.container import global_container
from app.tools.trading import validate_trade_risk
from intelligence.sentiment import LARGE_DROP_PCT, MIN_DIRECTIONAL, SentimentReading, large_drop_pct, score_texts

FEEDS = json.loads((Path(__file__).parent / "fixtures" / "sentiment_feeds.json").read_text(encoding="utf-8"))["feeds"]
GATE = -0.5  # risk_manager.RiskGuardian blocks a BUY below this

PANIC = [
    "Bitcoin plunges 12% as liquidations top $1.2B in 24 hours",
    "BTC is crashing and I just got liquidated. Absolutely rekt.",
    "Exchange halts withdrawals after exploit, users fear insolvency",
    "This is a bloodbath. Sell-off is accelerating, no support until 52k",
    "Bearish structure confirmed, lower lows everywhere. Staying out.",
    "Panic selling across the board, capitulation incoming",
    "Bitcoin ETF outflows hit record as price collapses",
    "Worst week since the FTX fraud. Brutal.",
    "Massive dump, stops got hunted, market is dead",
    "Scam wicks everywhere, terrible price action",
    "BTC $58,204 -11.8% 24h | vol $71B",
    "Long/short ratio 0.71 on Northbay",
]

EUPHORIA = [
    "Bitcoin surges past $100k to new ATH, bulls in full control",
    "BTC breakout confirmed, extremely bullish, love this rally",
    "ETF inflows hit record as price keeps soaring",
    "Best day of the year, portfolio skyrocketing",
    "Parabolic move, shorts getting squeezed",
    "Uptrend intact on every timeframe",
    "Happy to be long here, beautiful chart",
    "BTC $101,250 +6.2% 24h",
]

# Trading jargon and data-bot output that general-English sentiment reads as negative.
JARGON = [
    "Fear & Greed Index: 54 (Neutral)",
    "My stop loss keeps getting hit, what am I doing wrong?",
    "Reminder: always use a stop loss and size your risk",
    "Mining difficulty to adjust lower next week",
    "Weekly options expiry Friday, max pain sits at 63k",
    "Attack surface of the new bridge was audited, report published",
    "Hard fork on a testnet next week, no action for holders",
    "Total liquidations across all exchanges: $142M",
    "Northbay delisted three low-cap tokens today",
    "Court hearing in the long-running lawsuit set for October",
    "Short interest unchanged week over week",
    "Cut my size in half while we wait for the CPI print",
]

PROMO = [
    "GIVEAWAY: 1 BTC to a lucky follower, retweet to win!",
    "Our VIP signals room is now open - link in bio, amazing results",
    "100x GEM stealth launch, don't miss out!",
    "Claim your welcome bonus today, best rewards in crypto",
    "Free BTC airdrop for early supporters, love this community",
]

SARCASM = ["Great, another 20% dump. Love it.", "Wonderful, portfolio tanking again. Fantastic day."]


@pytest.fixture(autouse=True)
def _clean_sentiment_state(monkeypatch):
    # validate_trade_risk also reads drawdown / daily loss for the shared paper account from
    # data/paper.db; pin them so only the sentiment rule is under test.
    monkeypatch.setattr(type(global_container.paper_engine), "get_risk_metrics", lambda self, user_id: {"daily_pnl_pct": 0.0, "drawdown_pct": 0.0})
    core._sentiment_cache.cache.clear()
    for var in ("TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    yield
    core._sentiment_cache.cache.clear()


def _feed(monkeypatch, tweets, reddit_titles):
    """Configure both social sources and make them return the given text."""
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test-secret")

    tweepy = MagicMock()
    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in tweets] or None)
    praw = MagicMock()
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in reddit_titles]
    monkeypatch.setattr(core, "tweepy", tweepy)
    monkeypatch.setattr(core, "praw", praw)
    return tweepy, praw


def _fail_both_sources(tweepy, praw):
    tweepy.Client.return_value.search_recent_tweets.side_effect = RuntimeError("rate limited")
    praw.Reddit.return_value.subreddit.return_value.search.side_effect = RuntimeError("503")


def _risk_check(side, symbol):
    return json.loads(validate_trade_risk(side, symbol, 100.0, 10_000.0))["data"]


# --- scorer -----------------------------------------------------------------


def test_score_follows_the_text():
    assert score_texts(PANIC).score < GATE
    assert score_texts(EUPHORIA).score > 0.5


def test_score_is_bounded_and_counts_add_up():
    for texts in (PANIC, EUPHORIA, JARGON):
        reading = score_texts(texts)
        assert -1.0 <= reading.score <= 1.0
        assert reading.bullish + reading.bearish <= reading.texts == len(texts)


def test_trading_jargon_and_data_bots_are_neutral():
    reading = score_texts(JARGON)
    assert (reading.bullish, reading.bearish, reading.score) == (0, 0, 0.0)


def test_promo_posts_neither_mask_nor_trip_the_gate():
    assert score_texts(PROMO).bullish == 0
    assert score_texts(PANIC + PROMO).score == score_texts(PANIC).score


def test_sarcasm_about_a_dump_counts_as_bearish():
    assert score_texts(SARCASM).bearish == len(SARCASM)


@pytest.mark.parametrize("text", ["Not bearish at all here", "This is not a crash", "Holding my position, no panic"])
def test_negated_bearish_words_are_not_bearish(text):
    assert score_texts([text]).bearish == 0


@pytest.mark.parametrize(
    "text",
    [
        "Thread: how a pump and dump works and how to spot one",
        "Anniversary of the 2020 crash today, wild how far we have come",
        "New documentary on the exchange meltdown, worth watching?",
        "bitcoin is dead (again) lol, obituary #482",
        "PSA: fake airdrop scam doing the rounds, mods please pin",
        "Post-mortem of the bridge hack at an unrelated protocol",
    ],
)
def test_alarming_words_that_are_not_present_panic_are_neutral(text):
    assert score_texts([text]).bearish == 0


def test_a_few_bearish_texts_are_not_a_consensus():
    reading = score_texts(PANIC[: MIN_DIRECTIONAL - 1] + JARGON)
    assert reading.bearish == MIN_DIRECTIONAL - 1
    assert reading.score == 0.0
    assert reading.sufficient is True


def test_large_printed_drop_is_bearish_without_panic_words():
    texts = [
        "BTC down 10% in two hours and I turned the app off",
        "$BTC/USD 91,880 (-10.4% 24h)",
        "watching the tape print -10% and people still saying pullback",
        "I sold the open, down 10% before lunch is a statement",
        "alerts are a wall of red, -10.4% on huge volume",
        "Daily Discussion",
        "price bot 91,900",
        "turned off alerts after the third ping",
        "is this a flush or the start",
        "muted the chat",
    ]
    reading = score_texts(texts)
    assert reading.bearish >= 3
    assert reading.score < GATE


def test_ordinary_red_day_percent_is_not_a_crash():
    texts = [
        "$BTC/USD 101,200 (-5.8% 24h)",
        "ugly red day, down almost 6%, still not the end of the world",
        "took a little off, -5.8% is annoying not scary",
        "BTC down 5.8% today, normal volatility or something more",
        "buying a sliver on a 6% day",
        "funding still fine",
        "muted the group chat",
        "Daily Discussion",
        "garden variety flush",
        "if we hold 100k I am not touching anything",
    ]
    reading = score_texts(texts)
    assert reading.score == 0.0
    assert reading.score >= GATE


def test_promo_win_rate_hyphen_is_not_a_drop():
    assert large_drop_pct("🚀 VIP SIGNALS - 92% WIN RATE - LINK IN BIO 🚀") is None
    texts = [
        "🚀 VIP SIGNALS - 92% WIN RATE - LINK IN BIO 🚀",
        "claimed a 12% month in the newsletter, cool story",
        "price is flat, down 0.4% if you squint",
        "rt for a chance to win, 100% free entry",
        "bot: BTC 108,112 (+0.28% 24h)",
        "Weekly: +1.2%, basically noise",
        "Reminder: a 92% win-rate ad is an ad",
        "Daily Discussion",
        "funding +0.01%, nothing happening",
        "going for a walk, call me if it moves 3%",
    ]
    assert score_texts(texts).bearish == 0
    assert large_drop_pct("$BTC -10%") >= LARGE_DROP_PCT


def test_consensus_needs_a_share_of_the_sample_not_just_a_count():
    """If the fetch size ever grows, five bearish posts in a hundred must not read as unanimous panic."""
    neutral = [f"BTC ${60000 + i} | 24h vol $28B" for i in range(100)]
    assert score_texts(neutral + PANIC[:5]).score == 0.0


def test_too_few_texts_is_not_a_measurement():
    reading = score_texts(PANIC[:3])
    assert (reading.score, reading.sufficient) == (0.0, False)
    four_directional = score_texts(PANIC[:4])
    assert (four_directional.score, four_directional.sufficient) == (0.0, False)
    assert score_texts([]).score == 0.0


def test_repeated_text_counts_once():
    reading = score_texts(["BTC is crashing, total disaster"] * 20)
    assert (reading.texts, reading.score) == (1, 0.0)


def test_non_text_and_oversized_inputs_are_tolerated():
    reading = score_texts([None, 42, "", "   ", "crash " * 5000] + PANIC)
    assert reading.texts == len(PANIC) + 1


@pytest.mark.parametrize("feed", FEEDS, ids=[feed["id"] for feed in FEEDS])
def test_simulated_feeds_keep_their_verdict(feed):
    """Feeds written blind to the vocabulary (see the fixture's `about`). Any change to a verdict must be deliberate."""
    assert (score_texts(feed["texts"]).score < GATE) is feed["blocks_buy"]


def test_simulated_feeds_never_block_outside_a_crash_except_known_limits():
    wrong = {feed["id"] for feed in FEEDS if feed["blocks_buy"] != (feed["scenario"] == "crash")}
    assert wrong == {feed["id"] for feed in FEEDS if feed.get("known_limit")}
    assert sum(feed["blocks_buy"] for feed in FEEDS if feed["scenario"] == "crash") >= 5


# --- symbol handling --------------------------------------------------------


@pytest.mark.parametrize("symbol", ["BTC", "btc", " BTC/USDT ", "btc-usd", "BTC_USDT", "BTC/USDT:USDT", "BTCUSDT", "btcusdc", "XBT/USD"])
def test_symbol_variants_share_one_base_asset(symbol):
    assert core.base_asset(symbol) == "BTC"


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("WBTC", "WBTC"),
        ("STETH", "STETH"),
        ("ETHBTC", "ETHBTC"),
        ("CRVUSD", "CRVUSD"),
        ("USDT", "USDT"),
        ("OPUSDT", "OP"),
        ("SUSDT", "S"),
        ("TUSDC", "T"),
        ("", ""),
        (None, ""),
    ],
)
def test_base_asset_does_not_guess_ambiguous_tickers(symbol, expected):
    assert core.base_asset(symbol) == expected


def test_blank_symbol_is_rejected_without_caching():
    assert "no symbol" in core.analyze_social_sentiment("  ")
    assert core._sentiment_cache.cache == {}


def test_social_search_uses_base_asset(monkeypatch):
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC/USDT")
    query = tweepy.Client.return_value.search_recent_tweets.call_args.kwargs["query"]
    assert query.startswith("BTC ")
    assert praw.Reddit.return_value.subreddit.return_value.search.call_args.args[0] == "BTC"


# --- producer -> gate, through the real tool path ---------------------------


def test_bearish_feed_blocks_buy_but_not_sell(monkeypatch):
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")

    buy = _risk_check("buy", "BTC/USDT")
    assert buy["result"]["allowed"] is False
    assert "Falling Knife" in buy["result"]["reason"]
    assert buy["sentiment"]["status"] == "ok"
    assert buy["sentiment"]["score"] < GATE

    assert _risk_check("sell", "BTC/USDT")["result"]["allowed"] is True


def test_exchange_native_symbol_reads_the_same_reading(monkeypatch):
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    assert _risk_check("buy", "BTCUSDT")["result"]["allowed"] is False


@pytest.mark.parametrize("texts", [EUPHORIA, JARGON], ids=["euphoria", "quiet"])
def test_bullish_and_quiet_feeds_allow_buy(monkeypatch, texts):
    _feed(monkeypatch, texts[:6], texts[6:])
    core.analyze_social_sentiment("BTC")
    check = _risk_check("buy", "BTC/USDT")
    assert check["sentiment"]["status"] == "ok"
    assert check["sentiment"]["score"] >= 0.0
    assert check["result"]["allowed"] is True


def test_sentiment_for_one_asset_does_not_gate_another(monkeypatch):
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    eth = _risk_check("buy", "ETH/USDT")
    assert eth["result"]["allowed"] is True
    assert eth["sentiment"]["status"] == "no_data"


def test_missing_data_is_neutral_and_says_so():
    check = _risk_check("buy", "BTC/USDT")
    assert check["result"]["allowed"] is True
    hint = check["sentiment"].pop("hint")
    assert "get_social_sentiment" in hint
    assert check["sentiment"] == {"score": 0.0, "status": "no_data", "texts": 0, "bullish": 0, "bearish": 0, "age_seconds": None}


def test_risk_check_never_fetches(monkeypatch):
    """validate_trade_risk is documented as pure validation: it reads the cache and nothing else."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    _risk_check("buy", "BTC/USDT")
    tweepy.Client.assert_not_called()
    praw.Reddit.assert_not_called()


def test_unconfigured_sources_are_reported_as_such():
    out = core.analyze_social_sentiment("BTC")
    assert "Unavailable" in out
    sentiment = _risk_check("buy", "BTC/USDT")["sentiment"]
    assert sentiment["status"] == "not_configured"
    assert "TWITTER_BEARER_TOKEN" in sentiment["hint"]


def test_thin_sample_is_reported_as_insufficient(monkeypatch):
    _feed(monkeypatch, PANIC[:2], PANIC[2:3])
    core.analyze_social_sentiment("BTC")
    check = _risk_check("buy", "BTC/USDT")
    assert check["sentiment"]["status"] == "insufficient_data"
    assert check["result"]["allowed"] is True


def test_stale_reading_is_ignored_and_evicted(monkeypatch):
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    core._sentiment_cache.cache["BTC"]["time"] -= core._sentiment_cache.ttl + 1
    check = _risk_check("buy", "BTC/USDT")
    assert check["result"]["allowed"] is True
    assert check["sentiment"]["status"] == "no_data"
    assert core._sentiment_cache.cache == {}


def test_expired_readings_are_swept_on_write():
    core._sentiment_cache.set("ETH", SentimentReading(score=0.0, texts=9, bullish=0, bearish=0))
    core._sentiment_cache.cache["ETH"]["time"] -= core._sentiment_cache.ttl + 1
    core._sentiment_cache.set("BTC", SentimentReading(score=0.0, texts=9, bullish=0, bearish=0))
    assert set(core._sentiment_cache.cache) == {"BTC"}


def test_source_error_degrades_to_the_other_source(monkeypatch):
    tweepy, _ = _feed(monkeypatch, [], PANIC[:10])
    tweepy.Client.return_value.search_recent_tweets.side_effect = RuntimeError("rate limited")
    out = core.analyze_social_sentiment("BTC")
    assert "Twitter Error" in out
    assert core.get_cached_sentiment_score("BTC") < GATE


# --- a degraded refresh must never relax the gate ---------------------------


def test_failed_refresh_cannot_reopen_the_gate(monkeypatch):
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    _fail_both_sources(tweepy, praw)

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" in out
    assert "Sentiment score in force: -1.00" in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False


def test_one_source_erroring_cannot_reopen_the_gate_even_with_a_full_neutral_sample(monkeypatch):
    """Reddit 503s while Twitter returns ten price-bot posts: sample size alone would pass, the error must not."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in JARGON[:10]])
    praw.Reddit.return_value.subreddit.return_value.search.side_effect = RuntimeError("503")

    core.analyze_social_sentiment("BTC")

    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False


def test_one_source_down_cannot_reopen_the_gate(monkeypatch):
    """Twitter rate-limited, Reddit returns five routine titles: a 5-text sample must not replace a 12-text panic."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    tweepy.Client.return_value.search_recent_tweets.side_effect = RuntimeError("429")
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in JARGON[:5]]

    core.analyze_social_sentiment("BTC")

    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False


@pytest.mark.parametrize(
    "reddit_posts",
    [[], [types.SimpleNamespace(title=""), types.SimpleNamespace(title="   ")]],
    ids=["empty", "blank-only"],
)
def test_source_returning_no_usable_text_cannot_reopen_the_gate(monkeypatch, reddit_posts):
    """A successful response without scored text still loses a previously contributing feed."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in JARGON[:10]])
    praw.Reddit.return_value.subreddit.return_value.search.return_value = reddit_posts

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False


def test_configured_source_that_never_contributed_does_not_look_lost(monkeypatch):
    """A configured provider with no text in either refresh must not degrade the usable feed."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], [])
    core.analyze_social_sentiment("BTC")
    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in JARGON[:10]])
    praw.Reddit.return_value.subreddit.return_value.search.return_value = []

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is True


def test_error_from_source_that_never_contributed_does_not_hold_bearish(monkeypatch):
    """A noncontributing Reddit feed may fail while the sole contributor cleanly refreshes."""
    tweepy, praw = _feed(monkeypatch, PANIC[:10], [])
    core.analyze_social_sentiment("BTC")
    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in JARGON[:10]])
    praw.Reddit.return_value.subreddit.return_value.search.side_effect = RuntimeError("503")

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is True


def test_more_bearish_degraded_refresh_tightens_the_gate(monkeypatch):
    """A degraded tightening retains the missing contributor as a recovery guard."""
    core._sentiment_cache.set(
        "BTC",
        SentimentReading(score=-0.5, texts=10, bullish=2, bearish=6),
        sources={"twitter", "reddit"},
    )
    tweepy, praw = _feed(monkeypatch, PANIC[:10], [])
    praw.Reddit.return_value.subreddit.return_value.search.side_effect = RuntimeError("503")

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert core.get_cached_sentiment_score("BTC") < GATE
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False
    entry = core._sentiment_cache.get("BTC")
    assert entry["sources"] == {"twitter"}
    assert entry["guard_sources"] == {"twitter", "reddit"}

    tweepy.Client.return_value.search_recent_tweets.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(text=t) for t in JARGON[:10]])
    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False

    praw.Reddit.return_value.subreddit.return_value.search.side_effect = None
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in JARGON[10:]]
    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is True


def test_concurrent_degraded_refresh_cannot_overwrite_new_bearish_reading():
    cache = core.SentimentCache()
    start = threading.Barrier(2)
    bearish = SentimentReading(score=-1.0, texts=12, bullish=0, bearish=12)
    degraded = SentimentReading(score=0.0, texts=3, bullish=0, bearish=0)

    def update(reading, errored_sources):
        start.wait()
        cache.set_preserving_bearish("BTC", reading, configured=True, sources={"twitter"}, errored_sources=errored_sources)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, bearish, set()), pool.submit(update, degraded, {"twitter"})]
        for future in futures:
            future.result()

    assert cache.get("BTC")["reading"] == bearish


def test_concurrent_asset_writes_do_not_drop_either_reading():
    cache = core.SentimentCache()
    start = threading.Barrier(2)

    def update(symbol):
        start.wait()
        cache.set(symbol, SentimentReading(score=0.0, texts=5, bullish=0, bearish=0))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, "BTC"), pool.submit(update, "ETH")]
        for future in futures:
            future.result()

    assert set(cache.cache) == {"BTC", "ETH"}


def test_source_becoming_unconfigured_cannot_reopen_the_gate(monkeypatch):
    _, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    monkeypatch.delenv("TWITTER_BEARER_TOKEN")
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in JARGON[:5]]

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is False


def test_clean_single_source_refresh_can_replace_a_bearish_reading(monkeypatch):
    """An intentionally unconfigured provider must not make the configured provider look degraded."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test-secret")
    praw = MagicMock()
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in PANIC[:5]]
    monkeypatch.setattr(core, "praw", praw)
    core.analyze_social_sentiment("BTC")
    praw.Reddit.return_value.subreddit.return_value.search.return_value = [types.SimpleNamespace(title=t) for t in JARGON[:5]]

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is True


def test_full_refresh_replaces_a_bearish_reading(monkeypatch):
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    _feed(monkeypatch, JARGON[:10], JARGON[10:])

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["result"]["allowed"] is True


def test_held_reading_still_expires(monkeypatch):
    tweepy, praw = _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    first_seen = core._sentiment_cache.cache["BTC"]["time"]
    _fail_both_sources(tweepy, praw)
    core.analyze_social_sentiment("BTC")

    assert core._sentiment_cache.cache["BTC"]["time"] == first_seen  # holding does not extend the TTL
    core._sentiment_cache.cache["BTC"]["time"] -= core._sentiment_cache.ttl + 1
    assert _risk_check("buy", "BTC/USDT")["sentiment"]["status"] == "no_data"


def test_failed_refresh_does_not_hold_a_bullish_reading(monkeypatch):
    """Holding is one-directional: a stale upbeat reading must not pass as a live measurement."""
    tweepy, praw = _feed(monkeypatch, [], [])
    core._sentiment_cache.set("BTC", SentimentReading(score=0.9, texts=15, bullish=14, bearish=1))
    _fail_both_sources(tweepy, praw)

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" not in out
    assert _risk_check("buy", "BTC/USDT")["sentiment"]["status"] == "insufficient_data"


def test_held_reading_output_does_not_claim_neutral(monkeypatch):
    """Credentials vanish while a bearish reading is held: the output must not say sentiment is neutral."""
    _feed(monkeypatch, PANIC[:10], PANIC[10:])
    core.analyze_social_sentiment("BTC")
    for var in ("TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(var)

    out = core.analyze_social_sentiment("BTC")

    assert "does not replace" in out
    assert "treats sentiment as neutral" not in out
