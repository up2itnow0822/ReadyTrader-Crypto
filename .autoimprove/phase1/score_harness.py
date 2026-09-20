#!/usr/bin/env python3
"""Score the frozen Phase 1 Falling Knife split. Measurement only — not a product path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.sentiment import score_texts  # noqa: E402

GATE = -0.5
TRAIN_IDS = (
    "crash-01",
    "crash-07",
    "crash-exchange-hack",
    "crash-05",
    "calm-01",
    "red_day-01",
    "green_day-03",
    "contested-01",
    "alarming-jokes",
)
HELD_OUT_IDS = (
    "crash-03",
    "crash-12",
    "crash-02",
    "calm-02",
    "red_day-02",
    "contested-05",
    "alarming-anniversary",
    "alarming-altcoin-implodes",
)
CRASH_HELD_OUT = ("crash-03", "crash-12", "crash-02")
CRASH_TRAIN = ("crash-01", "crash-07", "crash-exchange-hack", "crash-05")


def _load_feeds() -> dict[str, dict]:
    payload = json.loads((ROOT / "tests" / "fixtures" / "sentiment_feeds.json").read_text(encoding="utf-8"))
    return {feed["id"]: feed for feed in payload["feeds"]}


def score_feed(feed: dict) -> dict:
    reading = score_texts(feed["texts"])
    blocks = reading.score < GATE
    return {
        "id": feed["id"],
        "scenario": feed["scenario"],
        "blocks_buy": feed.get("blocks_buy"),
        "known_limit": bool(feed.get("known_limit")),
        "score": reading.score,
        "texts": reading.texts,
        "bullish": reading.bullish,
        "bearish": reading.bearish,
        "blocks": blocks,
    }


def _hits(rows: list[dict], ids: tuple[str, ...]) -> int:
    by_id = {row["id"]: row for row in rows}
    return sum(1 for feed_id in ids if by_id[feed_id]["blocks"] and not by_id[feed_id]["known_limit"])


def summarize(feeds: dict[str, dict]) -> dict:
    train = [score_feed(feeds[i]) for i in TRAIN_IDS]
    held = [score_feed(feeds[i]) for i in HELD_OUT_IDS]
    extra = [score_feed(feed) for feed_id, feed in feeds.items() if feed_id not in TRAIN_IDS + HELD_OUT_IDS]
    held_crash_recall = _hits(held, CRASH_HELD_OUT) / len(CRASH_HELD_OUT)
    train_crash_blocks = _hits(train, CRASH_TRAIN)
    held_fp = [
        row["id"]
        for row in held
        if row["blocks"] and row["scenario"] in {"calm", "red_day", "green_day", "contested"}
    ]
    alarming_fp = [row["id"] for row in held if row["blocks"] and row["scenario"] == "alarming_but_fine" and not row["known_limit"]]
    return {
        "train": train,
        "held_out": held,
        "extra_held_out": extra,
        "train_crash_blocks": f"{train_crash_blocks}/{len(CRASH_TRAIN)}",
        "held_out_crash_blocks": f"{_hits(held, CRASH_HELD_OUT)}/{len(CRASH_HELD_OUT)}",
        "held_out_crash_recall": held_crash_recall,
        "held_out_noncrash_blocks": held_fp,
        "held_out_new_alarming_fp": alarming_fp,
    }


def main() -> None:
    report = summarize(_load_feeds())
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
