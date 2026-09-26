"""
Print the live FastMCP registry as Markdown: every tool's name, signature and the description
agents see.

Usage:
  python tools/generate_tool_docs.py                 # print to stdout
  python tools/generate_tool_docs.py --write PATH    # write to PATH instead

`docs/TOOLS.md` is the curated catalog (parameters, examples, error codes) and is NOT regenerated
from this output: writing over it would drop everything that is not in a docstring.
`tests/test_docs_tool_roster.py` keeps its tool roster identical to the registry.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import mdformat

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "TOOLS.md"

# Ensure repo root is importable when running as `python tools/generate_tool_docs.py`
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _anchor(name: str) -> str:
    return name.replace("_", "-")


def _format_default(v: object) -> str:
    if isinstance(v, str):
        return repr(v)
    return repr(v)


def _signature(fn: Any) -> str:
    """
    Render a readable signature without type annotations (stable for docs).
    """
    try:
        sig = inspect.signature(fn)
    except Exception:
        return f"{getattr(fn, '__name__', 'tool')}(...)"

    posonly: List[inspect.Parameter] = []
    pos_or_kw: List[inspect.Parameter] = []
    kwonly: List[inspect.Parameter] = []
    varpos: inspect.Parameter | None = None
    varkw: inspect.Parameter | None = None

    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.POSITIONAL_ONLY:
            posonly.append(p)
        elif p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            pos_or_kw.append(p)
        elif p.kind == inspect.Parameter.VAR_POSITIONAL:
            varpos = p
        elif p.kind == inspect.Parameter.KEYWORD_ONLY:
            kwonly.append(p)
        elif p.kind == inspect.Parameter.VAR_KEYWORD:
            varkw = p

    parts: List[str] = []

    def add_param(p: inspect.Parameter, *, prefix: str = "") -> None:
        s = f"{prefix}{p.name}"
        if p.default is not inspect._empty:
            s = f"{s}={_format_default(p.default)}"
        parts.append(s)

    for p in posonly:
        add_param(p)
    if posonly:
        parts.append("/")

    for p in pos_or_kw:
        add_param(p)

    if varpos is not None:
        add_param(varpos, prefix="*")
    elif kwonly:
        parts.append("*")

    for p in kwonly:
        add_param(p)

    if varkw is not None:
        add_param(varkw, prefix="**")

    name = getattr(fn, "__name__", "tool")
    return f"{name}({', '.join(parts)})"


def _section_title_for_module(module: str) -> str:
    m = (module or "").strip()
    if m == "app.tools.execution":
        return "Execution (DEX/CEX)"
    if m == "app.tools.market_data":
        return "Market data"
    if m == "app.tools.trading":
        return "Trading & risk"
    if m == "app.tools.research":
        return "Research & intelligence"
    return "Other"


async def _load_tools() -> Dict[str, Any]:
    # Importing `server` must be safe in a clean environment (paper mode defaults).
    from server import mcp

    tools = await mcp.list_tools()
    return {tool.name: tool for tool in tools}


def _first_line(doc: str) -> str:
    s = (doc or "").strip()
    if not s:
        return "No description."
    return s.splitlines()[0].strip()


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Print the live MCP tool registry as Markdown.")
    parser.add_argument("--write", metavar="PATH", help="write to PATH (never docs/TOOLS.md, the curated catalog)")
    args = parser.parse_args(argv)
    if args.write and Path(args.write).resolve() == OUT.resolve():
        parser.error("docs/TOOLS.md is curated; write the registry somewhere else and compare")
    tools = asyncio.run(_load_tools())

    # Group tools by module for stable, readable sections.
    grouped: Dict[str, List[Tuple[str, Any]]] = {}
    for name, tool in tools.items():
        fn = getattr(tool, "fn", None)
        mod = getattr(fn, "__module__", "") if fn else ""
        section = _section_title_for_module(mod)
        grouped.setdefault(section, []).append((name, tool))

    section_order = ["Trading & risk", "Execution (DEX/CEX)", "Market data", "Research & intelligence", "Other"]

    lines: List[str] = []
    lines.append("# ReadyTrader-Crypto MCP Tool Catalog")
    lines.append("")
    lines.append("Generated from the tools `server.py` registers: the descriptions agents see.")
    lines.append("")
    lines.append("> [!TIP]")
    lines.append("> AI agents can use these tools to gather intelligence, assess risk, and execute trades.")
    lines.append("")

    for section in section_order:
        items = grouped.get(section) or []
        if not items:
            continue
        items = sorted(items, key=lambda t: t[0])

        lines.append(f"## {section}")
        lines.append("")
        lines.append("| Tool Name | Description |")
        lines.append("| :--- | :--- |")

        for name, tool in items:
            fn = getattr(tool, "fn", None)
            doc = inspect.getdoc(fn) if fn else ""
            lines.append(f"| [`{name}`](#{_anchor(name)}) | {_first_line(doc or getattr(tool, 'description', '') or '')} |")

        lines.append("")

        for name, tool in items:
            fn = getattr(tool, "fn", None)
            doc = (inspect.getdoc(fn) if fn else "") or ""
            lines.append(f"### `{name}`")
            lines.append("")
            lines.append(f"**Signature:** `{_signature(fn)}`")
            lines.append("")
            if doc.strip():
                lines.append(f"```text\n{doc.strip()}\n```")
            lines.append("")
            lines.append("")

    text = mdformat.text("\n".join(lines).rstrip() + "\n", extensions=("gfm", "tables"))
    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"Wrote {target} ({len(tools)} tools)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
