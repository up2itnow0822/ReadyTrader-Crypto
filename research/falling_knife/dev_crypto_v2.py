"""Crypto, close-based, DEV years only (< 2022). Same pre-registered selection rule as v1/v2."""

from knife import line
from knife2 import evaluate2, feat_close
from sweep_all import load_class

data, c = load_class("crypto")
print("DEV crypto (before 2022), K=3, still=lowest, close-based")
for dmin in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
    s = evaluate2(data, feat_close, 3, dmin, c["H"], c["severe"], t1=c["split"])
    print(line(f"close-based dmin={dmin:.0%}", s))
