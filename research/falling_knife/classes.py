"""Per-class settings for the falling-knife study. Split dates were fixed before any scoring."""

import calendar


def T(y, m=1, d=1):
    return calendar.timegm((y, m, d, 0, 0, 0)) * 1000


CLASSES = {
    # held-out = everything from `split` onward; dev = everything before it
    "crypto": {"H": 10, "severe": 0.20, "split": T(2022), "clip": {"LUNAUSDT": T(2022, 5, 28)}, "invert": ()},
    "equity": {"H": 10, "severe": 0.10, "split": T(2020), "clip": {}, "invert": ()},
    # FX: every pair is also scored inverted (EURUSD -> USDEUR), since either leg can be the one bought.
    "fx": {"H": 10, "severe": 0.03, "split": T(2017), "clip": {}, "invert": "both"},
}
