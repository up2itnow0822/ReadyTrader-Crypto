"""Check the shipped core/market_guard.py against the frozen v2 research rule on every instrument-day.

    python3 verify_module_v2.py <equity|fx> [path/to/core/market_guard.py]

The module sees what it sees at runtime - the last BARS_REQUESTED daily bars - and must agree with
the research implementation (knife2.feat_close, and the close-based volatility ratio for FX) on
every day of the development and fresh data.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

from classes import CLASSES
from knife import load
from knife2 import feat_close
from sweep_all import FX_EXCLUDE, despike

kind = sys.argv[1]
path = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[2] / "core" / "market_guard.py")
spec = importlib.util.spec_from_file_location("mg", path)
mg = importlib.util.module_from_spec(spec)
sys.modules["mg"] = mg
spec.loader.exec_module(mg)

F = json.load(open("FROZEN_v2.json"))[kind]
assert (mg.KNIFE_WINDOW, mg.KNIFE_MIN_DROP) == (F["K"], F["dmin"])
if kind == "fx":
    assert mg.VOLATILITY_HALT_RATIO == F["volatility_halt"]["ratio"] and mg.VOLATILITY_BASELINE == F["volatility_halt"]["N"]


def cc(b, d, N=20):
    m = [abs(math.log(b[i][4] / b[i - 1][4])) for i in range(d - N, d)]
    mean = sum(m) / N
    return abs(math.log(b[d][4] / b[d - 1][4])) / mean if mean > 0 else None


for dirname in (kind, kind + "_fresh"):
    data = load(dirname, CLASSES[kind]["clip"])
    if kind == "fx":
        data = {k: despike(v) for k, v in data.items() if k not in FX_EXCLUDE}
        data = {**data, **{s + "_inv": [[x[0], 1 / x[1], 1 / x[3], 1 / x[2], 1 / x[4], x[5]] for x in b] for s, b in data.items()}}
    checked = agree = r_fire = m_fire = halt_agree = halts = 0
    bad = []
    for sym, bars in data.items():
        for d in range(24, len(bars)):
            f = feat_close(bars, d, F["K"])
            research = f["dd"] >= F["dmin"] and f["lowest"]
            reading = mg.assess(bars[max(0, d - mg.BARS_REQUESTED + 1) : d + 1], now_ms=bars[d][0])
            ok = research == reading.falling_knife
            checked += 1
            agree += ok
            r_fire += research
            m_fire += reading.falling_knife
            if kind == "fx":
                rh = (cc(bars, d) or 0) > F["volatility_halt"]["ratio"]
                mh = (reading.volatility_ratio or 0) > mg.VOLATILITY_HALT_RATIO
                halt_agree += rh == mh
                halts += rh
                ok = ok and rh == mh
            if not ok and len(bad) < 5:
                bad.append((sym, d, research, reading))
    extra = f", halt agree {halt_agree}/{checked}, halts {halts}" if kind == "fx" else ""
    print(f"{dirname}: days {checked}, knife agree {agree} ({agree / checked * 100:.4f}%), research fires {r_fire}, module fires {m_fire}{extra}")
    for b in bad:
        print("  MISMATCH", b[:3], b[3].drop_pct, b[3].volatility_ratio)
