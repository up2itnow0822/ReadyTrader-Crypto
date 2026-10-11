"""Build the real-bar test fixtures for ReadyTrader-Stocks and -FOREX from the research data.

    python3 make_fixtures.py stocks ../../tests/fixtures/market_guard_real_bars.json   (Stocks)
    python3 make_fixtures.py fx ../../tests/fixtures/market_guard_real_bars.json       (FOREX)

Expectations come from the research implementation (knife2.feat_close / volhalt ratio) on the full
series, never from the shipped module, so the tests pin the module to an independent reference.
"""

import json
import math
import sys

from knife import outcome, ymd
from knife2 import feat_close
from sweep_all import despike


def cc_ratio(b, d, N=20):
    m = [abs(math.log(b[i][4] / b[i - 1][4])) for i in range(d - N, d)]
    return abs(math.log(b[d][4] / b[d - 1][4])) / (sum(m) / N)


def case(path, sym, date, note, dmin, prec, fx=False, invert=False):
    full = json.load(open(path))
    full = [b for b in full if b[4] > 0 and b[2] >= b[3] > 0]
    if fx:
        full = despike(full)
    if invert:
        full = [[x[0], 1 / x[1], 1 / x[3], 1 / x[2], 1 / x[4], x[5]] for x in full]
    idx = [i for i, b in enumerate(full) if ymd(b[0]) == date]
    assert idx, (sym, date)
    d = idx[0]
    f = feat_close(full, d, 3)

    # `prec` decimals for equities; significant digits for FX, whose inverted rates can be 0.05.
    def sig(x):
        return float(f"{x:.{prec}g}") if fx else round(float(x), prec)

    bars = [[int(b[0])] + [sig(x) for x in b[1:5]] + [float(b[5])] for b in full[d - 39 : d + 1]]
    o = outcome(full, d, 10)
    c = {
        "symbol": sym,
        "date": date,
        "note": note,
        "expect_falling_knife": bool(f["dd"] >= dmin and f["lowest"]),
        "expect_drop_pct": round(f["dd"], 6),
        "forward_10d_worst_pct": round(o["mae"], 4) if o else None,
    }
    if fx:
        c["expect_volatility_ratio"] = round(cc_ratio(full, d), 4)
    c["bars"] = bars
    return c


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "stocks":
        E = "data/equity/"
        cases = [
            case(E + "WAL.json", "WAL", "2023-03-10", "SVB weekend: down 31% and still falling; fell a further 85% intraday by 2023-03-13", 0.15, 4),
            case(E + "ZION.json", "ZION", "2023-03-09", "SVB day one: down 15.2%, just over the floor; fell a further 45% within ten sessions", 0.15, 4),
            case(E + "BA.json", "BA", "2020-03-09", "COVID: down 19.8%; fell a further 61% within ten sessions", 0.15, 4),
            case(E + "COIN.json", "COIN", "2022-05-06", "crypto rout: down 20.3%; fell a further 61% within ten sessions", 0.15, 4),
            case(E + "AAPL.json", "AAPL", "2025-04-04", "tariff shock: down 15.9% in two sessions; fell a further 10% by 2025-04-08", 0.15, 4),
            case(E + "WAL.json", "WAL", "2023-03-14", "day after the low: down 52% but it bounced, so not still falling", 0.15, 4),
            case(E + "TSLA.json", "TSLA", "2022-11-09", "down 14.4% and still falling: just under the 15% floor", 0.15, 4),
            case(E + "SPY.json", "SPY", "2020-03-16", "index down 12.6% from its highest close of four sessions: under the floor", 0.15, 4),
            case(E + "AAPL.json", "AAPL", "2024-06-12", "ordinary day", 0.15, 4),
        ]
        about = (
            "Real daily bars (Yahoo Finance, split-adjusted) ending on each date, 40 bars each, as the server requests "
            "them, prices rounded to 4 decimals. expect_* comes from the research implementation "
            "(research/falling_knife/) on the full series, not from core/market_guard.py."
        )
    else:
        X = "data/fx/"
        cases = [
            case(
                X + "EURCHF_X.json",
                "EURCHF",
                "2015-01-16",
                "SNB removes the EURCHF floor (Yahoo stamps the 15th's bar on the 16th): EUR down 17% against CHF, "
                "a 508x move - halted, and a falling knife for a buy of EURCHF",
                0.05,
                7,
                fx=True,
            ),
            case(
                X + "EURCHF_X.json",
                "CHFEUR",
                "2015-01-16",
                "same day from the other leg, buying CHF (EURCHF inverted): halted, not a falling knife",
                0.05,
                7,
                fx=True,
                invert=True,
            ),
            case(
                X + "USDTRY_X.json",
                "TRYUSD",
                "2021-11-25",
                "lira collapse, buying the lira (USDTRY inverted): a falling knife, below the halt",
                0.05,
                7,
                fx=True,
                invert=True,
            ),
            case(X + "USDTRY_X.json", "USDTRY", "2021-11-25", "same day, buying dollars: not a falling knife for USD", 0.05, 7, fx=True),
            case(X + "GBPUSD_X.json", "GBPUSD", "2016-10-06", "GBP flash crash: halted (5.6x) though only 3.5% down, under the knife floor", 0.05, 7, fx=True),
            case(X + "EURUSD_X.json", "EURUSD", "2024-06-12", "ordinary day", 0.05, 7, fx=True),
        ]
        about = (
            "Real daily FX bars (Yahoo Finance; single-bar bad ticks removed as in the study) ending on each date, "
            "40 bars each, prices rounded to 7 significant digits. Inverted symbols are the pair seen from the other leg. "
            "Yahoo stamps many FX days at 23:00 UTC the day before, so dates are the bar timestamps' UTC dates. "
            "expect_* comes from the research implementation (research/falling_knife/), not core/market_guard.py."
        )
    out = {"about": about, "cases": cases}
    json.dump(out, open(sys.argv[2], "w"), separators=(",", ":"))
    for c in cases:
        print({k: v for k, v in c.items() if k != "bars"})
