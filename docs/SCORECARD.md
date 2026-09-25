# ReadyTrader-Crypto — Production Scorecard (Target: 10/10)

This scorecard turns “10/10 production quality” into **measurable, repeatable gates**.

## Environment assumptions

- **Python**: 3.12+ (CI uses 3.12; `pyproject.toml` requires `>=3.12`)
- **Primary run mode**: Docker-first, with optional local dev

## Quality gates (must be green)

### Lint (ruff)

```bash
ruff check .
```

- **Pass**: exit code 0
- **Notes**: import sorting and unused imports must be fixed repo-wide.

### Unit tests (pytest)

```bash
pytest -q
```

- **Pass**: exit code 0
- **Policy**: no stub tests (`pass`) in the suite once we reach 10/10.

### Coverage (pytest-cov)

Core runtime modules should meet a minimum coverage threshold.

```bash
pytest --cov=app \
  --cov=marketdata \
  --cov=observability \
  --cov=execution_store \
  --cov=idempotency_store \
  --cov=paper_engine \
  --cov=policy_engine \
  --cov=api_server \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=60
```

> Note: coverage is intentionally scoped to “core runtime modules” and excludes `vendor/` and `frontend/`.

### Static security scan (bandit)

```bash
bandit -q -r . -c bandit.yaml
```

- **Pass**: exit code 0 (or only explicitly-configured skips)

### Dependency vulnerability audit (pip-audit)

```bash
pip-audit -r requirements.txt
```

- **Pass**: no known vulns in runtime deps.

### Tool-surface correctness (docs drift)

The documented tool catalog must name exactly the **actual registered tools**.

```bash
pytest -q tests/test_docs_tool_roster.py
python tools/generate_tool_docs.py   # prints the live registry to compare descriptions by eye
```

- **Pass**: `docs/TOOLS.md` and the README name every registered tool and no other.

### Docs format (mdformat)

Markdown documentation should be consistently formatted.

```bash
mdformat --check docs README.md RUNBOOK.md SECURITY.md CONTRIBUTING.md CHANGELOG.md RELEASE_READINESS_CHECKLIST.md DISCLAIMER.md prompts .github mpc_signer/README.md
```

- **Pass**: exit code 0
- **Fix**: rerun the same command without `--check`

### Frontend (optional dashboard)

If the dashboard is a production target, it must lint and build:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

### “No stubs/TODOs” runtime policy

```bash
pytest -q tests/test_no_stubs_policy.py
```

- **Pass**: no `TODO/FIXME/XXX` markers and no “simulated live” runtime paths.

## Baseline snapshot (captured 2026-01-01)

This section is informational; the commands above are the source of truth.

### Notes / common gotchas

- **Tool docs drift**: `docs/TOOLS.md` is curated; update it with any tool change (the roster test catches added or removed tools, not changed behaviour).
- **Paper mode**: default mode should not require signing keys; live signing requires explicit signer configuration.
