#!/usr/bin/env python3
"""
Verify documentation consistency with codebase.

This script is run in CI to ensure:
1. Tool names in docs/TOOLS.md match registered tools in server.py
2. Environment variables in env.example match declared settings
3. No non-portable links (file://) in documentation
4. Version numbers are consistent

Usage:
    python tools/verify_docs.py

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

from __future__ import annotations

import asyncio
import re
import sys
import tomllib
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def check_non_portable_links(docs_dir: Path) -> list[str]:
    """Check for file:// links in documentation."""
    errors: list[str] = []
    file_url_pattern = re.compile(r"file://", re.IGNORECASE)

    for md_file in docs_dir.glob("**/*.md"):
        content = md_file.read_text()
        if file_url_pattern.search(content):
            # Find line numbers
            for i, line in enumerate(content.split("\n"), 1):
                if file_url_pattern.search(line):
                    errors.append(f"{md_file}:{i}: Non-portable file:// link found")

    # Also check root markdown files
    root = get_project_root()
    for md_file in ["README.md", "RUNBOOK.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md"]:
        path = root / md_file
        if path.exists():
            content = path.read_text()
            if file_url_pattern.search(content):
                for i, line in enumerate(content.split("\n"), 1):
                    if file_url_pattern.search(line):
                        errors.append(f"{path}:{i}: Non-portable file:// link found")

    return errors


def check_tool_names_in_docs(docs_dir: Path) -> list[str]:
    """Verify tool names in TOOLS.md match registered tools."""
    errors: list[str] = []
    tools_md = docs_dir / "TOOLS.md"

    if not tools_md.exists():
        errors.append("docs/TOOLS.md not found")
        return errors

    # Extract tool names from TOOLS.md
    content = tools_md.read_text()

    # Pattern to match tool signatures: **Signature:** `tool_name(...)`
    signature_pattern = re.compile(r"\*\*Signature:\*\*\s*`(\w+)\(")
    doc_tools = set(signature_pattern.findall(content))

    # Also match markdown headers like ### `tool_name`
    header_pattern = re.compile(r"###\s+`(\w+)`")
    doc_tools.update(header_pattern.findall(content))

    if not doc_tools:
        errors.append("Could not find any tool signatures in docs/TOOLS.md")
        return errors

    # Get registered tools from server.py
    try:
        # Import the server module to get registered tools
        root = get_project_root()
        sys.path.insert(0, str(root))

        from server import mcp

        # FastMCP 3.x exposes the enabled registry through its public async API.
        registered_tools = {tool.name for tool in asyncio.run(mcp.list_tools())}

        if not registered_tools:
            # Try alternative access pattern
            errors.append("Warning: Could not access registered tools from server.mcp")
            return errors

        # Compare
        missing_from_docs = registered_tools - doc_tools
        extra_in_docs = doc_tools - registered_tools

        if missing_from_docs:
            errors.append(f"Tools registered but not documented: {sorted(missing_from_docs)}")
        if extra_in_docs:
            errors.append(f"Tools documented but not registered: {sorted(extra_in_docs)}")

    except ImportError as e:
        errors.append(f"Could not import server module: {e}")
    except Exception as e:
        errors.append(f"Error checking tool registration: {e}")

    return errors


def check_env_example_settings() -> list[str]:
    """Verify env.example contains all declared settings."""
    errors: list[str] = []
    root = get_project_root()
    env_example = root / "env.example"

    if not env_example.exists():
        errors.append("env.example not found")
        return errors

    # Extract env vars from env.example
    env_content = env_example.read_text()
    env_vars: set[str] = set()

    for line in env_content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            # Handle both KEY=value and # KEY=value (commented examples)
            if "=" in line:
                key = line.split("=")[0].strip()
                env_vars.add(key)
        elif line.startswith("#") and "=" in line:
            # Commented example
            uncommented = line.lstrip("#").strip()
            if uncommented and "=" in uncommented:
                key = uncommented.split("=")[0].strip()
                env_vars.add(key)

    # Get settings from settings.py
    settings_file = root / "app" / "core" / "settings.py"
    if not settings_file.exists():
        errors.append("app/core/settings.py not found")
        return errors

    # Parse settings file for os.getenv calls
    settings_content = settings_file.read_text()
    getenv_pattern = re.compile(r'os\.getenv\(["\'](\w+)["\']')
    declared_vars = set(getenv_pattern.findall(settings_content))

    # Check for missing
    missing_from_env = declared_vars - env_vars

    # Filter out expected missing (these may be intentionally not in env.example)
    expected_missing = {"DEV_MODE"}  # Development-only settings
    missing_from_env -= expected_missing

    if missing_from_env:
        errors.append(f"Settings declared but not in env.example: {sorted(missing_from_env)}")

    return errors


def check_version_consistency() -> list[str]:
    """Verify version numbers are consistent."""
    errors: list[str] = []
    root = get_project_root()

    # Get version from pyproject.toml
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        errors.append("pyproject.toml not found")
        return errors

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    pyproject_version = data.get("project", {}).get("version")
    if not pyproject_version:
        errors.append("Version not found in pyproject.toml")
        return errors

    # Check api_server.py version
    api_server = root / "api_server.py"
    if api_server.exists():
        content = api_server.read_text()
        # Look for version in FastAPI definition
        version_match = re.search(r'version=["\']([^"\']+)["\']', content)
        if version_match:
            api_version = version_match.group(1)
            if api_version != pyproject_version:
                errors.append(f"Version mismatch: pyproject.toml={pyproject_version}, api_server.py={api_version}")

    return errors


def check_naming_consistency(docs_dir: Path) -> list[str]:
    """Check for naming inconsistencies (RealTrader vs ReadyTrader)."""
    errors: list[str] = []
    wrong_name_pattern = re.compile(r"RealTrader", re.IGNORECASE)

    for md_file in docs_dir.glob("**/*.md"):
        content = md_file.read_text()
        matches = wrong_name_pattern.findall(content)
        if matches:
            for i, line in enumerate(content.split("\n"), 1):
                if wrong_name_pattern.search(line):
                    errors.append(f"{md_file}:{i}: Incorrect naming 'RealTrader' (should be 'ReadyTrader')")

    return errors


def main() -> int:
    """Run all documentation verification checks."""
    root = get_project_root()
    docs_dir = root / "docs"

    all_errors: list[str] = []

    print("Checking for non-portable links...")
    errors = check_non_portable_links(docs_dir)
    all_errors.extend(errors)
    print(f"  {'✓' if not errors else '✗'} {len(errors)} issues found")

    print("Checking naming consistency...")
    errors = check_naming_consistency(docs_dir)
    all_errors.extend(errors)
    print(f"  {'✓' if not errors else '✗'} {len(errors)} issues found")

    print("Checking env.example matches settings...")
    errors = check_env_example_settings()
    all_errors.extend(errors)
    print(f"  {'✓' if not errors else '✗'} {len(errors)} issues found")

    print("Checking version consistency...")
    errors = check_version_consistency()
    all_errors.extend(errors)
    print(f"  {'✓' if not errors else '✗'} {len(errors)} issues found")

    print("Checking tool documentation...")
    errors = check_tool_names_in_docs(docs_dir)
    all_errors.extend(errors)
    print(f"  {'✓' if not errors else '✗'} {len(errors)} issues found")

    if all_errors:
        print("\n" + "=" * 60)
        print("Documentation verification FAILED:")
        print("=" * 60)
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print("\n" + "=" * 60)
    print("Documentation verification PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
