"""
Falling-knife rule research harness. Pure functions over daily OHLCV [[ts,o,h,l,c,v], ...].

The rule only ever looks at bars <= d (the day being judged). Outcomes use bars > d.
"""

from __future__ import annotations

import glob
import json
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    K: int = 3  # drop window (bars, including today)
    N: int = 20  # baseline volatility window, ending before the drop window
    Z: float = 4.0  # drop, in baseline-ATR units, needed to fire
    still: str = "lowest"  # "none" | "lowest" (today's close is the window's lowest close) | "lowerq" (close in bottom quarter of window range)
    M: float = 0.0  # min volume ratio (0 = ignore volume)
    dmin: float = 0.0  # absolute drawdown floor (fraction)


def features(bars, d, K, N):
    """Features for day index d using bars[0..d] only. Returns None if not enough history."""
    if d < K + N + 1:
        return None
    base = range(d - K - N + 1, d - K + 1)
    trs = []
    for i in base:
        h, low, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        if pc <= 0:
            return None
        trs.append((max(h, pc) - min(low, pc)) / pc)
    atr = sum(trs) / len(trs)
    win = bars[d - K : d + 1]  # K prior bars + today
    hi = max(b[2] for b in win)
    lo = min(b[3] for b in win)
    c = bars[d][4]
    dd = (hi - c) / hi if hi > 0 else 0.0
    prior_closes = [b[4] for b in bars[d - K : d]]
    vols = [bars[i][5] for i in base]
    vbar = sum(vols) / len(vols) if vols else 0.0
    return {
        "atr": atr,
        "dd": dd,
        "z": dd / atr if atr > 0 else 0.0,
        "lowest": c <= min(prior_closes),
        "lowerq": (c - lo) <= 0.25 * (hi - lo) if hi > lo else False,
        "vr": (bars[d][5] / vbar) if vbar > 0 else None,
    }


def fires(rule: Rule, f) -> bool:
    if f is None or f["z"] < rule.Z or f["dd"] < rule.dmin:
        return False
    if rule.still == "lowest" and not f["lowest"]:
        return False
    if rule.still == "lowerq" and not f["lowerq"]:
        return False
    if rule.M and f["vr"] is not None and f["vr"] < rule.M:
        return False
    return True


def outcome(bars, d, H):
    """Forward return and max adverse excursion of a buy at close d over the next H bars."""
    if d + H >= len(bars):
        return None
    c = bars[d][4]
    lows = [b[3] for b in bars[d + 1 : d + H + 1]]
    return {"ret": bars[d + H][4] / c - 1, "mae": min(lows) / c - 1}


def load(kind, clip=None):
    out = {}
    for p in sorted(glob.glob(f"data/{kind}/*.json")):
        sym = os.path.basename(p)[:-5]
        bars = [b for b in json.load(open(p)) if b[4] > 0 and b[2] >= b[3] > 0]
        if clip and sym in clip:
            bars = [b for b in bars if b[0] < clip[sym]]
        out[sym] = bars
    return out


def ymd(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))


def evaluate(data, rule: Rule, H: int, severe: float, t0=None, t1=None, invert=()):
    """Day-weighted evaluation over every (asset, day) with a known outcome, days in [t0, t1)."""
    all_o, fire_o, fire_days = [], [], []
    for sym, bars in data.items():
        if sym in invert:
            bars = [[b[0], 1 / b[1], 1 / b[3], 1 / b[2], 1 / b[4], b[5]] for b in bars]
        for d in range(len(bars)):
            ts = bars[d][0]
            if (t0 and ts < t0) or (t1 and ts >= t1):
                continue
            o = outcome(bars, d, H)
            if o is None:
                continue
            f = features(bars, d, rule.K, rule.N)
            if f is None:
                continue
            all_o.append(o)
            if fires(rule, f):
                fire_o.append(o)
                fire_days.append((sym, ymd(ts), round(f["dd"], 3), round(f["z"], 1), round(o["mae"], 3)))
    return summarise(all_o, fire_o, severe), fire_days


def pct(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return xs[k]


def summarise(all_o, fire_o, severe):
    def stats(os_):
        maes = [o["mae"] for o in os_]
        rets = [o["ret"] for o in os_]
        return {
            "n": len(os_),
            "p_severe": sum(m <= -severe for m in maes) / len(maes) if maes else float("nan"),
            "mae_p10": pct(maes, 0.10),
            "mae_med": pct(maes, 0.50),
            "ret_med": pct(rets, 0.50),
            "ret_mean": sum(rets) / len(rets) if rets else float("nan"),
        }

    a, f = stats(all_o), stats(fire_o)
    return {"all": a, "fire": f, "fire_rate": f["n"] / a["n"] if a["n"] else 0.0, "lift": (f["p_severe"] / a["p_severe"]) if a["p_severe"] else float("nan")}


def line(label, s):
    a, f = s["all"], s["fire"]
    return (
        f"{label:<46} fire {s['fire_rate'] * 100:5.2f}% ({f['n']:>4}/{a['n']:>6})  "
        f"P(severe) {f['p_severe'] * 100:5.1f}% vs {a['p_severe'] * 100:4.1f}%  lift {s['lift']:4.2f}  "
        f"MAE p10 {f['mae_p10'] * 100:6.1f}% vs {a['mae_p10'] * 100:6.1f}%  "
        f"ret med {f['ret_med'] * 100:5.1f}% vs {a['ret_med'] * 100:4.1f}%"
    )
