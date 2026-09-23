"""Routing table for execution/router.py::venue_allowed (issue #8).

`auto` is the Settings default and must route like `hybrid`; unknown values stay denied.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.settings import ExecutionMode, settings
from app.tools.execution import _require_live_allowed
from execution.router import venue_allowed


@pytest.mark.parametrize(
    ("mode", "venue", "allowed"),
    [
        ("auto", "cex", True),
        ("auto", "dex", True),
        ("hybrid", "cex", True),
        ("hybrid", "dex", True),
        ("cex", "cex", True),
        ("cex", "dex", False),
        ("dex", "dex", True),
        ("dex", "cex", False),
        ("", "cex", False),
        (None, "cex", False),
        ("bogus", "cex", False),
        ("auto", "otc", False),
        ("  AUTO ", "CEX", True),
    ],
)
def test_venue_allowed_table(mode, venue, allowed):
    assert venue_allowed(mode, venue) is allowed


def test_venue_allowed_accepts_enum_members():
    assert venue_allowed(ExecutionMode.AUTO, "cex") is True
    assert venue_allowed(ExecutionMode.AUTO, "dex") is True
    assert venue_allowed(ExecutionMode.CEX, "dex") is False


def test_default_execution_mode_is_auto_and_does_not_block_live_cex():
    """An operator who opens the live flags but never sets EXECUTION_MODE must not be
    vetoed by the routing default (issue #8)."""
    assert ExecutionMode("auto") is ExecutionMode.AUTO
    with patch.multiple(settings, PAPER_MODE=False, LIVE_TRADING_ENABLED=True, TRADING_HALTED=False, EXECUTION_MODE=ExecutionMode.AUTO):
        _require_live_allowed(venue="cex")
        _require_live_allowed(venue="dex")


def test_unknown_mode_is_still_fail_closed_through_the_guard():
    with patch.multiple(settings, PAPER_MODE=False, LIVE_TRADING_ENABLED=True, TRADING_HALTED=False, EXECUTION_MODE=ExecutionMode.DEX):
        with pytest.raises(ValueError, match="EXECUTION_MODE=dex"):
            _require_live_allowed(venue="cex")
