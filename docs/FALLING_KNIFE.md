# Falling Knife (crypto)

"Don't catch a falling knife": do not buy an asset while it is still crashing. The Risk Guardian
has one Falling Knife rule for crypto, on **sentiment**. It has **no price-based rule**, and this
page is why.

## What runs

Every BUY that adds exposure — through `validate_trade_risk`, `place_cex_order`, a
`swap_tokens` into a non-stablecoin, or an approved proposal — is refused while the cached social
sentiment for the asset is below **-0.5** (the bull-bear spread of recent X and Reddit text,
scored locally; `docs/SENTIMENT.md`). The score is only as fresh as the last
`get_social_sentiment(symbol)` call and expires after an hour; with no sources configured it is a
neutral 0.0 that the rule cannot act on, and `validate_trade_risk` says so (`sentiment.status`).

Every Risk Guardian answer carries a `falling_knife` block that states both halves:

```json
{"sentiment": {"active": true, "threshold": -0.5},
 "price": {"active": false, "reason": "No price-based Falling Knife rule ships for crypto: ..."}}
```

## Why there is no price rule

ReadyTrader-Stocks and ReadyTrader-FOREX block a BUY while the instrument is down sharply over its
last few daily closes and still at the low. The same kind of rule was tested for crypto twice, with
the selection rule and a pass criterion written down before the held-out data was scored. It failed
both times.

The question each rule answers: after it fires, is a further severe drop (20% within 10 days for
crypto) more likely than on an ordinary day? "Lift" is that probability divided by the base rate;
1.0 means the rule knows nothing.

| Attempt | Rule                                                                                                                           | Development years (before 2022) | Held-out years (2022 on)                                                                                               |
| :------ | :----------------------------------------------------------------------------------------------------------------------------- | :------------------------------ | :--------------------------------------------------------------------------------------------------------------------- |
| v1      | close at least 4.5 average true ranges (20-day) below the highest high of the last 4 days, and the lowest of the last 4 closes | lift 2.76                       | **lift 1.39** (fails)                                                                                                  |
| v2      | close at least 30% below the highest of the last 4 closes, and the lowest of them                                              | lift 3.22                       | 30 coins never downloaded before the rule was frozen: lift 2.04 over all years, **1.21** on the held-out years (fails) |

v2's pre-registered criterion was lift ≥ 2.0 over all years **and** ≥ 1.5 on the held-out years for
the fresh coins, firing on 0.1%–2% of days. It met the first and missed the second. The reason is
visible in the results: after a 30% crypto crash the typical next ten days were a **bounce**
(median return +10.9% against -1.5% on ordinary days). A rule that blocks those buys would mostly
have blocked the rebound, and would give the false comfort of a guard that does not predict what
it claims to.

So, as the frozen v2 file says: report the failure and ship nothing for crypto. The rule may be
revisited with new data under the same protocol; it will not be switched on because it sounds
prudent.

## Reproducing

`research/falling_knife/` holds the scripts, the frozen configurations (`FROZEN.json`,
`FROZEN_v2_crypto.json`, each with its SHA-256) and the output of every run
(`results/dev_v2_crypto.txt`, `results/heldout_v1.txt`, `results/heldout_v2_crypto.txt`). Crypto
bars come from the Binance public archive; `research/falling_knife/README.md` has the commands and
the protocol. The frozen files can be checked against their SHA-256; the git history cannot show
that freezing preceded scoring (both were committed together after the study ran), so that order
rests on the protocol.

## What protects a crypto account instead

- The position-size rule: the part of an order that adds exposure may be at most 5% of the
  account's value (the paper account, the exchange account for live CEX orders, the signer wallet
  for live swaps). The order is valued at the market price (a limit order at the higher of its
  limit and the market), never at a price the caller supplies alone. An order that adds exposure
  and has no market price, cannot be valued, or whose account cannot be read, is refused.
- The 5% daily-loss and 10% drawdown limits (paper account, measured on trading results:
  deposits are not gains and do not end a halt), after which only orders that reduce exposure
  pass. Live accounts have no loss history here; live orders list these two in
  `risk.inactive_rules`.
- For live trading: the policy allowlists and size limits, `EXECUTION_APPROVAL_MODE=approve_each`,
  and the kill switch `TRADING_HALTED` (`RUNBOOK.md`).
