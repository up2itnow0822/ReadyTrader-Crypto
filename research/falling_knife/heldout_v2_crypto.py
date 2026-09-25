"""Score FROZEN_v2_crypto exactly once: old held-out years (disclosed as seen) + 30 never-seen coins."""

import hashlib
import json

from classes import CLASSES
from knife import line, load, outcome, summarise
from knife2 import feat_close

raw = open("FROZEN_v2_crypto.json").read()
assert hashlib.sha256(raw.encode()).hexdigest() == open("FROZEN_v2_crypto.sha256").read().split()[0], "frozen file changed"
F = json.loads(raw)
cfg = F["crypto"]
split = CLASSES["crypto"]["split"]


def score(data, t0=None, t1=None):
    all_o, fire_o, fires = [], [], []
    for sym, bars in data.items():
        for d in range(len(bars)):
            ts = bars[d][0]
            if (t0 and ts < t0) or (t1 and ts >= t1):
                continue
            o = outcome(bars, d, cfg["H"])
            f = feat_close(bars, d, cfg["K"]) if o else None
            if f is None:
                continue
            all_o.append(o)
            if f["dd"] >= cfg["dmin"] and f["lowest"]:
                fire_o.append(o)
                fires.append(sym)
    return summarise(all_o, fire_o, cfg["severe"]), fires


old = load("crypto", CLASSES["crypto"]["clip"])
new = load("crypto_fresh")
out = {}
for name, data, lo, hi in (
    ("dev (seen)", old, None, split),
    ("old HELD-OUT (seen by v1)", old, split, None),
    ("FRESH all years", new, None, None),
    ("FRESH held-out years", new, split, None),
):
    s, fires = score(data, lo, hi)
    print(line(f"crypto {name}", s) + f"  coins firing {len(set(fires))}")
    out[name] = s
fa, fh = out["FRESH all years"], out["FRESH held-out years"]
ok = fa["lift"] >= 2.0 and fh["lift"] >= 1.5 and 0.001 <= fa["fire_rate"] <= 0.02
print("PASS" if ok else "FAIL", "against the pre-registered criterion:", F["pass_criterion"])
json.dump(out, open("heldout_v2_crypto_results.json", "w"), default=str)
