"""v2 features: close-based (robust to bad high/low prints) and, for comparison, high-based.

Same outcome definitions as knife.py. feat_close is the rule shipped in core/market_guard.py.
"""

import math

from knife import outcome, summarise


def feat_close(bars, d, K, N=20):
    if d < K + N + 1:
        return None
    closes = [b[4] for b in bars[d - K : d + 1]]
    hi = max(closes)
    c = closes[-1]
    rets = [abs(math.log(bars[i][4] / bars[i - 1][4])) for i in range(d - N, d)]
    mean = sum(rets) / N
    today = abs(math.log(bars[d][4] / bars[d - 1][4]))
    return {"dd": (hi - c) / hi, "lowest": c <= min(closes[:-1]), "vr": (today / mean) if mean > 0 else None}


def feat_high(bars, d, K, N=20):
    if d < K + N + 1:
        return None
    win = bars[d - K : d + 1]
    hi = max(b[2] for b in win)
    c = bars[d][4]
    return {"dd": (hi - c) / hi, "lowest": c <= min(b[4] for b in win[:-1]), "vr": None}


def evaluate2(data, featfn, K, dmin, H, severe, t0=None, t1=None):
    all_o, fire_o = [], []
    for sym, bars in data.items():
        for d in range(len(bars)):
            ts = bars[d][0]
            if (t0 and ts < t0) or (t1 and ts >= t1):
                continue
            o = outcome(bars, d, H)
            if o is None:
                continue
            f = featfn(bars, d, K)
            if f is None:
                continue
            all_o.append(o)
            if f["dd"] >= dmin and f["lowest"]:
                fire_o.append(o)
    return summarise(all_o, fire_o, severe)
