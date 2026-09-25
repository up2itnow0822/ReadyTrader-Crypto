"""Class loaders shared by every script, and the v1 dev sweep (python3 sweep_all.py <class>)."""

import sys

from classes import CLASSES
from knife import Rule, evaluate, line, load

FX_EXCLUDE = {"USDCNY_X", "USDARS_X", "USDRUB_X"}  # managed/pegged regimes or unreliable Yahoo history


def despike(bars, up=0.08, back=0.06):
    """Drop single bars that jump more than `up` and reverse more than `back` the next bar (bad ticks)."""
    keep = [bars[0]]
    for i in range(1, len(bars) - 1):
        r1 = bars[i][4] / keep[-1][4] - 1
        r2 = bars[i + 1][4] / bars[i][4] - 1
        if abs(r1) > up and abs(r2) > back and r1 * r2 < 0:
            continue
        keep.append(bars[i])
    keep.append(bars[-1])
    return keep


def load_class(kind):
    c = CLASSES[kind]
    data = load(kind, c["clip"])
    if kind == "fx":
        data = {k: despike(v) for k, v in data.items() if k not in FX_EXCLUDE}
    if c["invert"] == "both":
        inv = {}
        for s, b in data.items():
            inv[s + "_inv"] = [[x[0], 1 / x[1], 1 / x[3], 1 / x[2], 1 / x[4], x[5]] for x in b]
        data = {**data, **inv}
    return data, c


if __name__ == "__main__":
    kind = sys.argv[1]
    data, c = load_class(kind)
    print(f"DEV {kind}: {len(data)} series, H={c['H']}, severe={c['severe']:.0%}")
    base, _ = evaluate(data, Rule(Z=999), c["H"], c["severe"], t1=c["split"])
    nsev = base["all"]["p_severe"] * base["all"]["n"]
    print(f"baseline P(severe)={base['all']['p_severe'] * 100:.1f}%  n={base['all']['n']}")
    for K in (2, 3, 4):
        print(f"-- K={K} still=lowest")
        for Z in (3, 3.5, 4, 4.5, 5, 6):
            s, _ = evaluate(data, Rule(K=K, Z=Z, still="lowest"), c["H"], c["severe"], t1=c["split"])
            caught = s["fire"]["p_severe"] * s["fire"]["n"]
            print("  " + line(f"Z={Z}", s) + f"  recall {caught / nsev * 100:4.1f}%")
