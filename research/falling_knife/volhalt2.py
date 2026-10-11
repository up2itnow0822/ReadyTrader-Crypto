"""Calibrate the close-based volatility halt on the FX development years.

ratio = |ln(close_t / close_t-1)| / mean of the 20 prior |ln(close_i / close_i-1)|. Robust to bad
high/low prints. The threshold is the round value whose dev frequency is closest to that of the v1
rule it replaces (true range > 3.0x the 20-day mean true range). Held-out frequencies are printed
for information only (no outcomes are looked at here).
"""

import math

from sweep_all import load_class

data, c = load_class("fx")
data = {k: v for k, v in data.items() if not k.endswith("_inv")}  # the ratio is direction-free


def tr_ratio(b, d, N=20):
    trs = [(max(b[i][2], b[i - 1][4]) - min(b[i][3], b[i - 1][4])) / b[i - 1][4] for i in range(d - N, d)]
    atr = sum(trs) / N
    tr = (max(b[d][2], b[d - 1][4]) - min(b[d][3], b[d - 1][4])) / b[d - 1][4]
    return tr / atr if atr > 0 else 0


def cc_ratio(b, d, N=20):
    m = [abs(math.log(b[i][4] / b[i - 1][4])) for i in range(d - N, d)]
    mean = sum(m) / N
    return abs(math.log(b[d][4] / b[d - 1][4])) / mean if mean > 0 else 0


dev, ho = [], []
trdev = 0
for s, b in data.items():
    for d in range(22, len(b)):
        r = cc_ratio(b, d)
        if b[d][0] < c["split"]:
            dev.append(r)
            if tr_ratio(b, d) > 3.0:
                trdev += 1
        else:
            ho.append(r)
target = trdev / len(dev)
print(f"DEV n={len(dev)}  TR>3.0x frequency = {target * 100:.2f}%")
for t in (3, 3.5, 4, 4.5, 5, 5.5, 6, 7):
    fd = sum(r > t for r in dev) / len(dev)
    fh = sum(r > t for r in ho) / len(ho)
    print(f"  cc>{t}x  dev {fd * 100:.2f}%  held-out {fh * 100:.2f}%")
q = sorted(dev)[int(len(dev) * (1 - target))]
print(f"frequency-matched dev quantile: {q:.2f}x")
