"""tools/setup_wizard.py, as a new user runs it (UAT 2026-09-24, CLI-01)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(tmp_path: Path, stdin: bytes | None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    work = tmp_path / "w"
    if not work.exists():
        shutil.copytree(REPO_ROOT / "tools", work / "tools")
        shutil.copy(REPO_ROOT / "env.example", work / "env.example")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PAPER_MODE", "LIVE_TRADING", "SIGNER_TYPE", "PRIVATE_KEY"))}
    env.update(env_extra or {})
    # The connectivity check is not under test and needs no network: point requests at nothing.
    env["HTTPS_PROXY"] = env["HTTP_PROXY"] = "http://127.0.0.1:9"
    return subprocess.run([sys.executable, "tools/setup_wizard.py"], cwd=work, input=stdin, capture_output=True, timeout=120, env=env)


def test_a_closed_stdin_does_not_crash(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/setup_wizard.py")],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
        env={**os.environ, "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"},
    )
    assert proc.returncode == 0, proc.stderr.decode()[-1500:]
    assert "EOFError" not in proc.stderr.decode()


def test_the_example_env_is_not_told_it_misses_a_private_key(tmp_path):
    out = ANSI.sub("", _run(tmp_path, b"y\n").stdout.decode())
    assert "PRIVATE_KEY is MISSING" not in out and "MISSING" not in out
    assert "SIGNER_TYPE" in out and "not needed: paper orders" in out
    assert "CRYPTOPANIC_API_KEY not set (optional" in out


def test_a_raw_key_signer_is_called_out(tmp_path):
    (tmp_path / "w").mkdir()
    shutil.copytree(REPO_ROOT / "tools", tmp_path / "w" / "tools")
    shutil.copy(REPO_ROOT / "env.example", tmp_path / "w" / "env.example")
    (tmp_path / "w" / ".env").write_text("PAPER_MODE=true\nSIGNER_TYPE=env_private_key\n")
    out = ANSI.sub("", _run(tmp_path, b"").stdout.decode())
    assert "development only, refused for live trading" in out
