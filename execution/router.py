from __future__ import annotations


def venue_allowed(execution_mode: str, venue: str) -> bool:
    """
    Basic router for Phase 3.

    - dex mode: only DEX actions
    - cex mode: only CEX actions
    - hybrid mode: both
    - auto mode (the Settings default): both — the venue is chosen per call, so
      routing must not veto either one. Before this branch existed, operators who
      never set EXECUTION_MODE had every live call denied (issue #8).

    Anything else is denied (fail closed).
    """
    m = (execution_mode or "").strip().lower()
    v = (venue or "").strip().lower()

    if m in {"hybrid", "auto"}:
        return v in {"dex", "cex"}
    if m == "dex":
        return v == "dex"
    if m == "cex":
        return v == "cex"
    # Unknown execution mode: safest is deny
    return False
