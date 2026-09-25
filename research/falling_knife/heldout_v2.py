"""Score FROZEN_v2 exactly once: old held-out years (disclosed as previously seen) + fresh instruments."""

import hashlib
import json
import math

from classes import CLASSES
from knife import line, load, outcome, summarise, ymd
from knife2 import feat_close
from sweep_all import FX_EXCLUDE, despike

raw = open("FROZEN_v2.json").read()
assert hashlib.sha256(raw.encode()).hexdigest() == open("FROZEN_v2.sha256").read().split()[0], "frozen file changed"
F = json.loads(raw)


def prep(kind, dirname):
    c = CLASSES[kind]
    data = load(dirname, c["clip"])
    if kind == "equity":
        data = {k: v for k, v in data.items() if k not in ("SPY", "QQQ", "IWM")}
    if kind == "fx":
        data = {k: despike(v) for k, v in data.items() if k not in FX_EXCLUDE}
        data = {**data, **{s + "_inv": [[x[0], 1 / x[1], 1 / x[3], 1 / x[2], 1 / x[4], x[5]] for x in b] for s, b in data.items()}}
    return data


def outcome_close(bars, d, H):
    if d + H >= len(bars):
        return None
    c = bars[d][4]
    return {"ret": bars[d + H][4] / c - 1, "mae": min(b[4] for b in bars[d + 1 : d + H + 1]) / c - 1}


def score(data, cfg, t0=None, t1=None, ofn=outcome):
    all_o, fire_o, fires = [], [], []
    for sym, bars in data.items():
        for d in range(len(bars)):
            ts = bars[d][0]
            if (t0 and ts < t0) or (t1 and ts >= t1):
                continue
            o = ofn(bars, d, cfg["H"])
            f = feat_close(bars, d, cfg["K"]) if o else None
            if f is None:
                continue
            all_o.append(o)
            if f["dd"] >= cfg["dmin"] and f["lowest"]:
                fire_o.append(o)
                fires.append((sym, ymd(ts), round(f["dd"], 3), round(o["mae"], 3)))
    return summarise(all_o, fire_o, cfg["severe"]), fires


def cc_ratio(b, d, N=20):
    m = [abs(math.log(b[i][4] / b[i - 1][4])) for i in range(d - N, d)]
    mean = sum(m) / N
    return abs(math.log(b[d][4] / b[d - 1][4])) / mean if mean > 0 else 0


def halt_eval(data, thr, t0=None, t1=None, k=5, big=0.03):
    tot = hit = nh = hh = 0
    for s, b in data.items():
        if s.endswith("_inv"):
            continue
        for d in range(22, len(b) - k):
            ts = b[d][0]
            if (t0 and ts < t0) or (t1 and ts >= t1):
                continue
            exc = max(abs(b[d + j][4] / b[d][4] - 1) for j in range(1, k + 1)) >= big
            tot += 1
            hit += exc
            if cc_ratio(b, d) > thr:
                nh += 1
                hh += exc
    return {
        "days": tot,
        "halt_rate": nh / tot,
        "p_big_all": hit / tot,
        "p_big_halt": hh / nh if nh else float("nan"),
        "lift": (hh / nh) / (hit / tot) if nh and hit else float("nan"),
        "halt_days": nh,
    }


out = {"frozen_sha256": open("FROZEN_v2.sha256").read().split()[0]}
for kind, fresh in (("equity", "equity_fresh"), ("fx", "fx_fresh")):
    cfg = F[kind]
    split = CLASSES[kind]["split"]
    old = prep(kind, kind)
    new = prep(kind, fresh)
    for name, data, lo, hi in (
        ("dev (seen)", old, None, split),
        ("old HELD-OUT (seen by v1)", old, split, None),
        ("FRESH all years", new, None, None),
        ("FRESH held-out years", new, split, None),
    ):
        s, fires = score(data, cfg, lo, hi)
        sc, _ = score(data, cfg, lo, hi, ofn=outcome_close)
        print(line(f"{kind} {name}", s) + f"   [close-only outcome lift {sc['lift']:.2f}]")
        out[f"{kind}|{name}"] = {"summary": s, "close_outcome_summary": sc, "fires": fires}
    if kind == "fx":
        for name, data, lo, hi in (("dev", old, None, split), ("old held-out", old, split, None), ("FRESH", new, None, None)):
            h = halt_eval(data, cfg["volatility_halt"]["ratio"], lo, hi)
            print(
                f"fx HALT {name:<13} halt {h['halt_rate'] * 100:.2f}% of days  "
                f"P(5-day |move|>=3%) {h['p_big_halt'] * 100:.1f}% vs {h['p_big_all'] * 100:.1f}%  lift {h['lift']:.2f}"
            )
            out[f"fx_halt|{name}"] = h
json.dump(out, open("heldout_v2_results.json", "w"), default=str)
