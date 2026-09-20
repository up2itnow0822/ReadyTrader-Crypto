# .autoimprove/phase1/

## Purpose

Accept-round evidence for the frozen Falling Knife crash-recall harness. Paper/CI only.

## Ownership

Agent Economy, LLC / Bill Wilson. Parent: `.autoimprove/AGENTS.md`.

## Local Contracts

- Train/held-out ids are frozen in `harness.md`. Do not edit the split mid-run.
- Primary metric is held-out crash-block recall on frozen ids only.
- New fixture feeds start held-out and do not change the primary denominator.
- Any guard failure is REJECT / STOP.
- Max 5 rounds; stop early on 3 consecutive rejects.

## Work Guidance

- Diagnose train misses first (`crash-05`). Note `crash-02` as a held-out miss; do not retune to it in the same round.
- Add feeds before lexicon or rule edits.
- Prefer a tighten that can lift crash recall without calm / red_day / contested false positives.
- Do not delete `known_limit` without a true score improvement.

## Verification

- `python .autoimprove/phase1/score_harness.py`
- Paper/safety pack and `examples/paper_btc_uat.py` as listed in `harness.md`
- Per-round notes in `rounds/rN.md`; summary in `REPORT.md`

## Child DOX Index

(none)
