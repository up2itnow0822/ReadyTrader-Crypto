# Falling Knife study: reproduction harness

These scripts produced every number in `docs/FALLING_KNIFE.md`: why ReadyTrader-Crypto ships **no**
price-based Falling Knife rule. The same study, run once for all three ReadyTrader servers, selected
the price rules that ReadyTrader-Stocks and ReadyTrader-FOREX ship; the harness is the same code in the
three repositories (formatting aside). `verify_module_v2.py` and `make_fixtures.py` check those servers'
`core/market_guard.py` and build their test fixtures; they have no counterpart here. This is research
code, not part of the server: nothing in `app/` or the top-level modules imports it.

Python 3.10+ standard library only; `fetch.py` also needs `curl`. Run everything from this
directory.

## Reproduce

```bash
bash fetch_all.sh                   # downloads daily bars into ./data/ (gitignored, ~95 MB)
python3 dev_v2.py equity 0.15,0.20,0.25          # development sweep -> results/dev_v2_equity.txt
python3 dev_v2.py fx 0.03,0.04,0.05,0.06,0.08    #                   -> results/dev_v2_fx.txt
python3 dev_crypto_v2.py                         #                   -> results/dev_v2_crypto.txt
python3 volhalt2.py                              # halt calibration  -> results/volhalt2.txt
python3 heldout_v2.py                            # frozen v2, scored -> results/heldout_v2.txt
python3 heldout_v2_crypto.py                     # frozen crypto v2  -> results/heldout_v2_crypto.txt
python3 heldout.py                               # frozen v1         -> results/heldout_v1.txt
python3 verify_module_v2.py equity|fx            # shipped module == research rule, every day
python3 make_fixtures.py stocks|fx <out.json>    # rebuild the test fixture
```

Yahoo revises history occasionally and the latest bars move every day, so a re-run months later
can differ slightly in the last decimal; the conclusions should not.

## Protocol

1. **Split first.** Development and held-out periods were fixed in `classes.py` before anything was
   scored: crypto 2022-01-01, equities 2020-01-01, FX 2017-01-01.
2. **Select on development years only**, with a rule written down in advance: the highest lift in
   P(a further severe drop within 10 days) among configurations firing on 0.3%-1.0% of
   instrument-days; ties within 0.2 lift go to the simpler rule.
3. **Freeze** the chosen configuration in a JSON file with its SHA-256 (`FROZEN*.json`). The v2
   scoring scripts (`heldout_v2.py`, `heldout_v2_crypto.py`) refuse to run if the file has changed;
   v1's `heldout.py` predates that check.
4. **Score once.**

What can be checked afterwards, and what cannot: each frozen file matches its SHA-256, and the pass
criterion is written inside `FROZEN_v2_crypto.json`. The git history does **not** show that the
freeze came before the scoring: the study ran before it was committed, and the frozen files and
the results landed in the same commit. The order rests on the protocol above, not on timestamps.

The history, because it matters for how far to trust the numbers:

- **v1** (`FROZEN.json`) used a high-based drawdown (and, for crypto, an ATR-normalised one). It
  passed held-out for equities and FX and **failed for crypto** (lift 1.39: after big crypto drops
  the typical next ten days were a bounce).
- Yahoo FX daily bars turned out to carry bad high/low prints (0.24% of bars have a high more than
  3% above the open-close body). A high-based rule fires on those phantom spikes, so **v2**
  (`FROZEN_v2.json`) uses closes only. v2 was selected on the development years with the same rule.
  Because v1 had already been scored on the held-out years, those years are not pristine for v2,
  so v2 was also scored on **instruments first downloaded after v2 was frozen** (64 stocks,
  24 currency pairs). Those are the headline numbers.
- A close-based crypto rule (`FROZEN_v2_crypto.json`) was selected the same way, with a pass
  criterion written into the frozen file, and scored on 30 never-downloaded coins. It **failed**
  (lift 1.21 on the fresh coins' held-out years), so no price rule ships for crypto.

## Files

| File | What it is |
| :--- | :--- |
| `classes.py` | Per-class split dates, horizon, severity threshold |
| `knife.py` | v1 features, outcomes (`outcome`: 10-day forward return and worst low), summaries |
| `knife2.py` | v2 close-based feature `feat_close` (the shipped rule) and `evaluate2` |
| `sweep_all.py` | Class loaders (`load_class`: FX exclusions, bad-tick removal, inverted pairs) and the v1 sweep |
| `fetch.py`, `fetch_all.sh` | Data download and the exact universes |
| `dev_v2.py`, `dev_crypto_v2.py`, `volhalt2.py` | Development-years selection and calibration |
| `heldout.py`, `heldout_v2.py`, `heldout_v2_crypto.py` | One-shot scoring of each frozen file |
| `verify_module_v2.py` | Shipped `core/market_guard.py` vs the research rule on every instrument-day |
| `make_fixtures.py` | Builds the real-bar test fixtures from independent research code |
| `FROZEN*.json`, `FROZEN*.sha256` | The frozen configurations |
| `results/` | Output of each script as run for the published numbers |

## Data notes

Equities: Yahoo daily bars, OHLC scaled by adjusted close / close so splits do not read as crashes;
index ETFs (SPY, QQQ, IWM) excluded from scoring. FX: Yahoo daily bars; every pair also scored
inverted (EURUSD and USDEUR), since either leg can be the one bought; USDCNY, USDARS and USDRUB
excluded (managed regimes or unreliable history); single-bar spikes over 8% that reverse over 6% the
next bar removed as bad ticks. Crypto: Binance public archive; LUNA clipped at 2022-05-28, when the
symbol was reused. Symbols Yahoo no longer serves (delisted: WBA, CMA, X) could not be downloaded, so
the equity universes carry survivorship bias.
