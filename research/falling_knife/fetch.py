"""Fetch daily OHLCV history into ./data/<class>/<SYM>.json as [[ts_ms, o, h, l, c, v], ...].

    python3 fetch.py <class> SYMBOL [SYMBOL ...]

A class whose name starts with "crypto" is read from Binance's public archive API (daily klines);
anything else from Yahoo Finance's chart API. Existing files are skipped. See fetch_all.sh for the
exact universes used in docs/FALLING_KNIFE.md. Raw data is not committed (data/ is gitignored).
"""

import json
import os
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def get(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            # Every URL here is an https URL built from constants.
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(4 * (i + 1))
                continue
            raise
        except Exception:
            if i < tries - 1:
                time.sleep(3 * (i + 1))
                continue
            raise


def binance(sym):
    out, start = [], 1500000000000  # 2017-07
    while True:
        rows = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1d&startTime={start}&limit=1000")
        if not rows:
            break
        out += [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]
        if len(rows) < 1000:
            break
        start = rows[-1][0] + 1
        time.sleep(0.3)
    return out


def yahoo(sym, p1=946684800, p2=None):
    """Yahoo daily bars from 2000-01-01. Uses curl: Yahoo rate-limits browser-like client fingerprints."""
    p2 = p2 or int(time.time())
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1={p1}&period2={p2}&interval=1d&events=split"
    for i in range(4):
        # curl with a fixed argument list (no shell); url is an https URL built from constants.
        r = subprocess.run(  # nosec B603 B607
            ["curl", "-sS", "--max-time", "30", "-A", "Mozilla/5.0", url], capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.startswith("{"):
            d = json.loads(r.stdout)
            if d.get("chart", {}).get("result"):
                break
        time.sleep(8 * (i + 1))
        url = url.replace("query2.", "query1.") if "query2." in url else url.replace("query1.", "query2.")
    else:
        raise RuntimeError((r.stdout or r.stderr)[:120])
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    out = []
    for i, ts in enumerate(res.get("timestamp", [])):
        o, h, low, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, low, c):
            continue
        # Scale OHLC by adjclose / close, so splits (and dividends) do not read as crashes.
        f = (adj[i] / c) if adj and adj[i] and c else 1.0
        out.append([ts * 1000, o * f, h * f, low * f, c * f, float(v or 0)])
    return out


def _day(ts_ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ts_ms / 1000))


if __name__ == "__main__":
    kind, syms = sys.argv[1], sys.argv[2:]
    os.makedirs(f"data/{kind}", exist_ok=True)
    for s in syms:
        path = f"data/{kind}/{s.replace('=', '_').replace('^', 'IDX_')}.json"
        if os.path.exists(path):
            print("skip", s)
            continue
        try:
            rows = binance(s) if kind.startswith("crypto") else yahoo(s)
            json.dump(rows, open(path, "w"))
            print(f"{s:<12} {len(rows):>5} bars  {_day(rows[0][0])} .. {_day(rows[-1][0])}")
        except Exception as e:
            print(f"{s:<12} FAILED {type(e).__name__}: {str(e)[:80]}")
        time.sleep(0.2 if kind.startswith("crypto") else 1.5)
