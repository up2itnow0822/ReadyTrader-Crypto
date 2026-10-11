"""Where the server keeps its files.

An MCP client launches the server from a working directory of its own choosing (Claude Desktop uses
/, others the user's home folder), so default data files are anchored to the install, not the
working directory: `<repo>/data/`, or `READYTRADER_DATA_DIR` when set. Each file's own `*_PATH`
variable still wins.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def data_path(name: str) -> str:
    base = (os.getenv("READYTRADER_DATA_DIR") or "").strip() or str(REPO_ROOT / "data")
    return str(Path(base).expanduser() / name)


def ensure_parent(path: str) -> str:
    """Create the file's folder if needed; a bare file name lives in the working directory."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path
