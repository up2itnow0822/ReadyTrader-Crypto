"""
Roster-truth guard for documentation (DOX milestone m3).

The MCP tool roster is whatever `server.py` actually registers via the `register_*`
functions in `app/tools/*.py` — nothing else. This test:

  (a) builds that roster live, by importing `server.mcp` (the same FastMCP instance the
      real process serves) and asking it for its tools;
  (b) scans shipped documentation and example scripts for text that *looks like* a tool
      call — a backticked ``name(`` / ``name(...)`` span, or a bare backticked name in a
      row of any Markdown table whose header mentions "Tool" — and fails, naming the exact
      file:line, for every name that is neither a registered tool nor covered by the
      explicit, commented ALLOWLIST below (HTTP endpoints written as paths such as
      ``GET /api/health`` never match this pattern and need no entry; internal Python APIs,
      shell commands, and the strategy contract function the *agent* writes do, and are
      listed with a reason);
  (c) asserts `docs/TOOLS.md` documents exactly the registered roster (no more, no less).

This must FAIL against `main`'s docs (see BUILD-REPORT.md for the recorded failure list
and the mutation-check transcript that proves this test actually catches a regression).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterable, List, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------------------
# (a) The real roster, straight from the FastMCP instance server.py assembles.
# ---------------------------------------------------------------------------------------


def _load_registered_tool_names() -> set[str]:
    """Import server.mcp (registers all 4 tool modules) and list its tools.

    Installed fastmcp (3.2.0 as of this branch) exposes async `list_tools()` returning a
    `Sequence[Tool]`; older fastmcp releases exposed an async `get_tools()` returning a
    `dict[name, Tool]`. Support both so this test does not silently rot on a fastmcp bump.
    """
    from server import mcp

    async def _load() -> set[str]:
        if hasattr(mcp, "list_tools"):
            tools = await mcp.list_tools()
            return {t.name for t in tools}
        if hasattr(mcp, "get_tools"):
            tools = await mcp.get_tools()
            if isinstance(tools, dict):
                return set(tools.keys())
            return {t.name for t in tools}
        raise RuntimeError("Installed fastmcp exposes neither list_tools() nor get_tools() on FastMCP; inspect the installed fastmcp API and update this test.")

    return asyncio.run(_load())


# ---------------------------------------------------------------------------------------
# (b) Scan shipped docs/examples for tool-call-shaped text.
# ---------------------------------------------------------------------------------------

# Backticked `name(` / `name(...)` anywhere in a scanned file. `name` may be dotted
# (e.g. `PaperTradingEngine.execute_trade_result(`) to catch Python-API references too.
_BACKTICK_CALL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)\(")

# A bare backticked `name` (no trailing paren), used only inside rows of a table whose
# header mentions "Tool" -- e.g. `| \`swap_tokens\` | Swap tokens on a DEX. |`.
_BACKTICK_NAME_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

# Explicit allowlist: things that look like a tool call in backticks but are not one of
# the registered MCP tools. Every entry needs a reason; nothing here may be a real,
# unregistered tool name -- that would defeat the point of this test.
ALLOWLIST: dict[str, str] = {
    # Strategy contract: this is a function the AGENT writes and hands to
    # run_backtest_simulation / the stress lab; strategy_sandbox.py executes it in a
    # child process. It is never itself an MCP tool.
    "on_candle": "strategy contract function the agent writes (strategy_sandbox.py), not an MCP tool",
    # FastMCP's own Python API for listing a server's registered tools, used by
    # tools/generate_tool_docs.py and tools/verify_docs.py and documented in docs/AGENTS.md.
    "mcp.list_tools": "FastMCP Python API used by the doc generators, not an MCP tool",
    "list_tools": "FastMCP Python API used by the doc generators, not an MCP tool",
    # strategy_sandbox.run_strategy is the isolation entrypoint BacktestEngine/stress_test_engine
    # call internally. Only run_backtest_simulation (the MCP tool) is agent-facing.
    "run_strategy": "strategy_sandbox.run_strategy: internal isolation entrypoint, not an MCP tool",
    "strategy_sandbox.run_strategy": "internal isolation entrypoint used by run_backtest_simulation, not an MCP tool",
    # Internal PaperTradingEngine methods. deposit_paper_funds and place_cex_order (paper
    # branch) call these; agents never call them directly.
    "PaperTradingEngine.execute_trade_result": "internal Python API behind the paper order path, not an MCP tool",
    "PaperTradingEngine.deposit": "internal Python API behind deposit_paper_funds, not an MCP tool",
    # backtest_engine.BacktestEngine.run is what run_backtest_simulation calls; not itself a tool.
    "BacktestEngine.run": "internal Python API behind the run_backtest_simulation tool, not an MCP tool",
    # stress_test_engine.run_synthetic_stress_test is a plain Python function imported by
    # examples/stress_test_demo.py. It has never been registered with mcp.tool().
    "run_synthetic_stress_test": "stress_test_engine function; a local Python import in examples/, never an MCP tool",
    "stress_test_engine.run_synthetic_stress_test": "same function, dotted form; a local Python import in examples/, never an MCP tool",
    "ExchangeProvider.get_marketdata_capabilities": "internal Python API behind the get_cex_capabilities tool, not an MCP tool",
    "recommend_settings": "recommendations.recommend_settings: internal helper used by examples/stress_test_demo.py, not an MCP tool",
    # execution_store.ExecutionStore methods and the approved_execution() context manager
    # are only ever called from api_server.py (the HTTP admin path). No MCP tool may call
    # them -- see AGENTS.md Work Guidance.
    "ExecutionStore.confirm_as_operator": "internal Python API, HTTP-admin-only path (api_server.py), not an MCP tool",
    "ExecutionStore.list_pending": "internal Python API behind GET /api/pending-approvals, not an MCP tool",
    "ExecutionStore.confirm": "internal Python API behind POST /api/approve-trade, not an MCP tool",
    "approved_execution": "app.tools.execution.approved_execution: internal context manager, not an MCP tool",
    "app.tools.execution.approved_execution": "fully-qualified form of the same context manager, not an MCP tool",
    # MarketDataBus.fetch_ticker is the internal method get_crypto_price/fetch_ohlcv call;
    # ccxt's own fetch_ticker is referenced once in UAT evidence describing a raw probe.
    "MarketDataBus.fetch_ticker": "internal Python API behind get_crypto_price, not an MCP tool",
    "fetch_ticker": "raw ccxt method referenced in UAT evidence as a manual connectivity probe, not an MCP tool",
    # Signer factory and settings validation: internal Python entry points named in AGENTS.md /
    # HERMES_INTEGRATION.md prose, not MCP tools.
    "get_signer": "signing/factory.py::get_signer(): internal signer factory, not an MCP tool",
    "Settings._validate": "app.core.settings.Settings._validate(): internal validation method, not an MCP tool",
    # docs/STRATEGY_SANDBOX.md's threat-model section illustrates a PAST vulnerability (the old
    # in-process sandbox exposed pandas) using these two pandas methods as attack examples.
    "pd.read_csv": "illustrative attack example in docs/STRATEGY_SANDBOX.md's threat model, not an MCP tool",
    "pd.read_pickle": "illustrative attack example in docs/STRATEGY_SANDBOX.md's threat model, not an MCP tool",
}

# Files/dirs always scanned in full.
_FLAT_FILES = ["README.md", "RUNBOOK.md", "RELEASE_READINESS_CHECKLIST.md", "CHANGELOG.md"]


def _unreleased_line_range(lines: List[str]) -> Tuple[int, int]:
    """Return the [start, end) 0-based line index range covering CHANGELOG's Unreleased section."""
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if start is None and re.match(r"^#{1,3}\s*Unreleased\b", line.strip(), re.IGNORECASE):
            start = i
            continue
        if start is not None and re.match(r"^#{1,3}\s+\S", line):
            end = i
            break
    if start is None:
        return (0, 0)
    return (start, end)


def _is_separator_row(line: str) -> bool:
    s = line.strip()
    if not s or "-" not in s:
        return False
    return all(c in "-:| \t" for c in s)


def _candidate_lines(path: Path) -> List[Tuple[int, str]]:
    """Return [(1-based lineno, text), ...] for the portion of `path` this test scans."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if path.name == "CHANGELOG.md":
        start, end = _unreleased_line_range(lines)
        return [(i + 1, lines[i]) for i in range(start, end)]
    return [(i + 1, line) for i, line in enumerate(lines)]


def _discover_files() -> List[Path]:
    files: List[Path] = []
    for name in _FLAT_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)

    def _skip(p: Path) -> bool:
        parts = p.parts
        return any(bad in parts for bad in ("vendor", "node_modules", "__pycache__", ".git")) or "_deprecated" in parts

    files += sorted(p for p in ROOT.glob("**/AGENTS.md") if not _skip(p.relative_to(ROOT)) and "frontend" not in p.relative_to(ROOT).parts)
    files += sorted(p for p in ROOT.glob("docs/**/*.md") if not _skip(p.relative_to(ROOT)))
    files += sorted(p for p in ROOT.glob("prompts/**/*.md") if not _skip(p.relative_to(ROOT)))
    files += sorted(p for p in ROOT.glob("examples/*.py") if not _skip(p.relative_to(ROOT)))

    # de-dupe while preserving order
    seen = set()
    out = []
    for p in files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _check_candidate(candidate: str, path: Path, lineno: int, registered: set[str], failures: List[str], seen: set[Tuple[str, int, str]]) -> None:
    if candidate in registered or candidate in ALLOWLIST:
        return
    key = (str(path), lineno, candidate)
    if key in seen:
        return
    seen.add(key)
    rel = path.relative_to(ROOT)
    failures.append(f"{rel}:{lineno}: `{candidate}` is not a registered MCP tool and is not in the ALLOWLIST")


def _scan_file(path: Path, registered: set[str], failures: List[str], seen: set[Tuple[str, int, str]]) -> None:
    lines = _candidate_lines(path)

    # Pass 1: backticked `name(` anywhere in the file.
    for lineno, line in lines:
        for m in _BACKTICK_CALL_RE.finditer(line):
            _check_candidate(m.group(1), path, lineno, registered, failures, seen)

    # Pass 2: bare backticked names inside rows of any table whose header mentions "Tool".
    i = 0
    n = len(lines)
    while i < n - 1:
        header_lineno, header_line = lines[i]
        _, sep_line = lines[i + 1]
        if "|" in header_line and _is_separator_row(sep_line):
            header_has_tool = "tool" in header_line.lower()
            j = i + 2
            while j < n and "|" in lines[j][1] and lines[j][1].strip():
                if header_has_tool:
                    row_lineno, row_line = lines[j]
                    for m in _BACKTICK_NAME_RE.finditer(row_line):
                        _check_candidate(m.group(1), path, row_lineno, registered, failures, seen)
                j += 1
            i = j
            continue
        i += 1


def _scan_all_docs(registered: set[str]) -> List[str]:
    failures: List[str] = []
    seen: set[Tuple[str, int, str]] = set()
    for path in _discover_files():
        _scan_file(path, registered, failures, seen)
    return failures


# ---------------------------------------------------------------------------------------
# (c) docs/TOOLS.md must list exactly the registered roster.
# ---------------------------------------------------------------------------------------


def _tools_md_roster() -> set[str]:
    tools_md = ROOT / "docs" / "TOOLS.md"
    text = tools_md.read_text(encoding="utf-8")
    return set(re.findall(r"^###\s+`([A-Za-z_][A-Za-z0-9_]*)`\s*$", text, flags=re.MULTILINE))


# ---------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------


def test_registered_roster_is_nonempty() -> None:
    registered = _load_registered_tool_names()
    assert len(registered) >= 1, "server.py registered zero tools -- something is badly broken"


def test_no_phantom_tool_references_in_docs() -> None:
    registered = _load_registered_tool_names()
    failures = _scan_all_docs(registered)
    if failures:
        pytest.fail(
            "Phantom/stale tool references found in shipped docs "
            f"({len(failures)} total; see AGENTS.md / docs/AGENTS.md for the DOX contract):\n" + "\n".join(sorted(failures))
        )


def test_docs_tools_md_matches_registered_roster() -> None:
    registered = _load_registered_tool_names()
    documented = _tools_md_roster()
    missing = sorted(registered - documented)
    extra = sorted(documented - registered)
    assert not missing, f"Tools registered in server.py but missing from docs/TOOLS.md: {missing}"
    assert not extra, f"docs/TOOLS.md documents tools that server.py does not register: {extra}"


def _iter_allowlist() -> Iterable[Tuple[str, str]]:
    return ALLOWLIST.items()


def test_allowlist_entries_are_not_actually_registered_tools() -> None:
    """Guard the guard: nothing in ALLOWLIST may secretly be a real, registered tool name --
    that would silently exempt a real tool from ever being checked."""
    registered = _load_registered_tool_names()
    overlapping = sorted(name for name, _reason in _iter_allowlist() if name in registered)
    assert not overlapping, f"ALLOWLIST entries that are actually registered tools (remove them): {overlapping}"
