"""v2 dev sweep, dev years only: python3 dev_v2.py <equity|fx> 0.03,0.05,..."""

import sys

from knife import line
from knife2 import evaluate2, feat_close, feat_high
from sweep_all import load_class

kind = sys.argv[1]
floors = [float(x) for x in sys.argv[2].split(",")]
data, c = load_class(kind)
data = {k: v for k, v in data.items() if k not in ("SPY", "QQQ", "IWM")}
print(f"DEV {kind} (before split), K=3, still=lowest")
for dmin in floors:
    for name, fn in (("high-based ", feat_high), ("close-based", feat_close)):
        s = evaluate2(data, fn, 3, dmin, c["H"], c["severe"], t1=c["split"])
        print(line(f"{name} dmin={dmin:.0%}", s))
