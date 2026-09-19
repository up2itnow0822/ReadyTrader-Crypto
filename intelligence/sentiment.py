"""
Deterministic text sentiment for the Risk Guardian's Falling Knife gate.

Each text is classified bullish / bearish / neutral, then the directional texts are aggregated
into a bull-bear spread:

    score = (bullish - bearish) / (bullish + bearish)        in [-1.0, +1.0]

`score < -0.5` therefore means bearish texts outnumber bullish ones by more than three to one.
Fewer than MIN_DIRECTIONAL directional texts, or less than a quarter of the sample, is "no
consensus" and scores 0.0.

Classification uses VADER's rule engine (negation, intensifiers, capitals) over a market-only
vocabulary instead of VADER's general-English lexicon. General sentiment words misfire on a
ticker search: "stop loss", "risk", "Fear & Greed Index", "hard fork" and "max pain" all read
as negative, while giveaway spam and sarcasm ("Great, another 20% dump. Love it.") read as
positive. Only words that state a market direction or distress count here; everything else is
neutral and is ignored by the score, so data bots and promo posts neither trip the gate nor
mask it.

Local and deterministic on purpose: the same texts always give the same score, no API key or
network call is involved, and the behaviour is pinned by tests/fixtures/sentiment_feeds.json.

Known limits: precision is bought with recall. A crash described in other words ("risk off",
"withdrawals frozen", "sell everything") goes unseen, negation more than a few words from its
target is missed, and an altcoin imploding while the searched asset sits flat still counts.
On 86 simulated feeds written blind to this vocabulary the rule caught about half of the
crashes and fired on none of the calm, red, green or contested days (docs/SENTIMENT.md). It
is a circuit breaker for broad, plain-spoken panic, not a forecast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Fewer distinct texts than this is not a sample.
MIN_TEXTS = 5

# Fewer directional texts than this - or less than this share of the sample - is not a
# consensus; the score stays 0.0. At today's fetch size (up to 15 texts) the two floors coincide.
# This is the sensitivity knob: on a calm feed about 1 text in 25 uses this vocabulary, in a
# crash about 1 in 4, so 4 of 15 is rare by chance and common in a panic.
MIN_DIRECTIONAL = 4
MIN_DIRECTIONAL_SHARE = 1 / 4

# VADER's conventional neutral band for the per-text compound score.
POLARITY_THRESHOLD = 0.05

# VADER's cost grows faster than linearly with length; tweets and post titles are far shorter.
MAX_TEXT_CHARS = 1000

# "Pump and dump" names a scheme, not a price move.
IGNORED_PHRASES = re.compile(r"pump\W*(?:and|&|n)\W*dump", re.IGNORECASE)

# Talk about past crashes is not present panic; such texts are scored neutral.
RETROSPECTIVE = re.compile(r"anniversar|documentar|years? ago|remember when|throwback|hindsight|footage", re.IGNORECASE)

# Valences use VADER's -4..+4 scale. Deliberately absent: words that name a topic without a
# direction (liquidation, delisting, lawsuit, exploit, hack, scam, fraud, ponzi, bankruptcy, fear,
# risk), words that are mostly historical or jokes ("the 2022 collapse", "bitcoin is dead
# (again)", "dead cat bounce"), and ambiguous ones (pump, dip, short, long, bear, bull, moon).
# Scam-warning threads, security write-ups and anniversaries run every day on a flat market.
MARKET_LEXICON = {
    # price direction
    "bearish": -2.0,
    "crash": -2.4,
    "crashes": -2.4,
    "crashed": -2.4,
    "crashing": -2.6,
    "plunge": -2.2,
    "plunges": -2.2,
    "plunged": -2.2,
    "plunging": -2.4,
    "plummet": -2.4,
    "plummets": -2.4,
    "plummeted": -2.4,
    "plummeting": -2.5,
    "tanked": -2.0,
    "tanking": -2.2,
    "tumble": -1.8,
    "tumbles": -1.8,
    "tumbled": -1.8,
    "tumbling": -2.0,
    "nosedive": -2.4,
    "nosedives": -2.4,
    "freefall": -2.6,
    "free-fall": -2.6,
    "slump": -1.6,
    "slumps": -1.6,
    "dump": -1.8,
    "dumps": -1.8,
    "dumped": -1.8,
    "dumping": -2.0,
    "selloff": -2.0,
    "sell-off": -2.0,
    "downtrend": -1.5,
    "bleeding": -1.8,
    "nuke": -2.4,
    "nukes": -2.4,
    "nuked": -2.4,
    "nuking": -2.5,
    "craters": -2.4,
    "cratered": -2.4,
    "cratering": -2.5,
    "implodes": -2.5,
    "imploded": -2.5,
    "imploding": -2.6,
    "implosion": -2.5,
    "wipeout": -2.4,
    "obliterated": -2.6,
    "annihilated": -2.6,
    "evaporated": -2.2,
    "evaporates": -2.2,
    # panic and distress
    "panic": -2.3,
    "panicking": -2.4,
    "capitulation": -2.4,
    "capitulating": -2.4,
    "capitulated": -2.4,
    "massacre": -2.8,
    "slaughter": -2.6,
    "slaughtered": -2.6,
    "bloodbath": -2.8,
    "carnage": -2.6,
    "meltdown": -2.6,
    "collapses": -2.4,
    "collapsing": -2.5,
    "rekt": -2.5,
    "wrecked": -2.2,
    "disaster": -2.8,
    "brutal": -2.2,
    "worthless": -2.4,
    # systemic distress
    "insolvent": -2.6,
    "insolvency": -2.6,
    "contagion": -2.2,
    "depeg": -2.2,
    "depegged": -2.4,
    # bullish
    "bullish": 2.0,
    "rally": 1.8,
    "rallies": 1.8,
    "rallied": 1.8,
    "rallying": 1.9,
    "surge": 1.8,
    "surges": 1.8,
    "surged": 1.8,
    "surging": 1.9,
    "soar": 2.0,
    "soars": 2.0,
    "soared": 2.0,
    "soaring": 2.1,
    "skyrocket": 2.2,
    "skyrockets": 2.2,
    "skyrocketed": 2.2,
    "skyrocketing": 2.3,
    "breakout": 1.6,
    "ath": 1.8,
    "uptrend": 1.5,
    "parabolic": 1.8,
    "mooning": 1.8,
}


@dataclass(frozen=True)
class SentimentReading:
    score: float
    texts: int
    bullish: int
    bearish: int

    @property
    def sufficient(self) -> bool:
        """Enough text came back for the score to count as a measurement (even a neutral one)."""
        return self.texts >= MIN_TEXTS


@lru_cache(maxsize=1)
def _analyzer() -> SentimentIntensityAnalyzer:
    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon = dict(MARKET_LEXICON)
    return analyzer


def _compound(text: str) -> float:
    if RETROSPECTIVE.search(text):
        return 0.0
    return _analyzer().polarity_scores(IGNORED_PHRASES.sub(" ", text))["compound"]


def score_texts(texts: Iterable[str]) -> SentimentReading:
    """Aggregate texts into a bull-bear spread over the directional ones. Repeated texts count once."""
    candidates = (t.strip()[:MAX_TEXT_CHARS] for t in texts if isinstance(t, str) and t.strip())
    distinct = {t.lower(): t for t in candidates}
    compounds = [_compound(t) for t in distinct.values()]
    bullish = sum(c >= POLARITY_THRESHOLD for c in compounds)
    bearish = sum(c <= -POLARITY_THRESHOLD for c in compounds)
    directional = bullish + bearish
    consensus = len(compounds) >= MIN_TEXTS and directional >= max(MIN_DIRECTIONAL, len(compounds) * MIN_DIRECTIONAL_SHARE)
    score = (bullish - bearish) / directional if consensus else 0.0
    return SentimentReading(score=round(score, 4), texts=len(compounds), bullish=bullish, bearish=bearish)
