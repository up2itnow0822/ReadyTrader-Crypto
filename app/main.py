"""
Backwards-compatible entrypoint.

`server.py` is the canonical FastMCP entrypoint and tool registry.
This module re-exports `mcp` for imports like `from app.main import mcp`.
"""

from __future__ import annotations

import os
import sys

# `python app/main.py` puts app/ (not the repo root) on sys.path, which breaks
# `from server import ...`. Make the repo root importable so the documented
# entrypoint (README, Dockerfile, smithery.yaml, Hermes MCP config) works.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from server import main, mcp  # noqa: E402

__all__ = ["main", "mcp"]

if __name__ == "__main__":
    main()
