# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Purpose

ReadyTrader-Crypto is an MCP + FastAPI crypto trading stack (CEX via ccxt, optional DEX) with paper/live gates, policy/risk controls, and agent-facing tools. Primary production path for Agent Economy BTC work: spot BTC/USDT via Hermes stdio MCP.

## Ownership

- Owner: Agent Economy, LLC / Bill Wilson (@up2itnow0822)
- Runtime surfaces: MCP (`server.py` / `app/main.py`), FastAPI (`api_server.py`), optional Next.js frontend

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for project-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects purpose, scope, ownership, durable structure, contracts, workflows, required inputs/outputs, permissions, or AGENTS.md index contents.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index

## User Preferences

- Fail closed for production: when `DEV_MODE=false`, API auth required (including WebSocket `/ws` JWT), CORS must not be `*`, `TRADING_HALTED` defaults true; keep `.env.live` / `.env.*.local` gitignored
- Never use `SIGNER_TYPE=env_private_key` when `PAPER_MODE=false` or `LIVE_TRADING_ENABLED=true`
- Hermes integration is stdio MCP + skill — do not grow core Hermes tools for ReadyTrader
- Live dust trades are out of scope until a dedicated Phase 4 UAT

## Work Guidance

- Paper-first: `PAPER_MODE=true`, `LIVE_TRADING_ENABLED=false` for local/dev
- BTC production profile: `EXECUTION_MODE=cex`, allowlist BTC pairs only, `EXECUTION_APPROVAL_MODE=approve_each`
- Secrets stay in `.env` / operator vault — never commit
- Quality gate: `make check` and `make security`
- `requirements.txt` owns pinned runtime dependencies; regenerate `requirements.lock.txt` from a clean `requirements-dev.txt` environment after dependency changes and verify it with `pip check` and `pip-audit`
- `sentiment_score` fed to the Risk Guardian is the bull-bear spread in [-1, 1] from `intelligence/sentiment.py` (scored locally and deterministically - no model or network call); missing, unconfigured or thin data is neutral `0.0` and `validate_trade_risk` must report it in `sentiment.status`; a fresh bearish reading stays in force when a contributing source is lost, errors, or yields a degraded sample, while an intentionally single-source clean refresh may replace it; change the vocabulary only with fresh feeds added to `tests/fixtures/sentiment_feeds.json`

## Verification

- `make check` (ruff + pytest)
- `make security` (bandit + pip-audit)
- Paper BTC harness: `python examples/paper_btc_uat.py`
- UAT evidence: `docs/UAT_BTC_PRODUCTION_MINUS_DUST.md`
- Hermes skill (public MIT package): https://github.com/up2itnow0822/readytrader-crypto-hermes → install as `optional-skills/finance/readytrader-crypto/`

## Child DOX Index

| Path | Owns |
|------|------|
| [signing/AGENTS.md](signing/AGENTS.md) | Signer backends, policy wrapper, live-key custody rules |
| [docs/AGENTS.md](docs/AGENTS.md) | Operator docs, Hermes integration, UAT/runbooks |
| [app/](app/) | Core settings, container, MCP/API tool wiring (parent-owned until split) |
| [execution/](execution/) | CEX/DEX executors (parent-owned) |
| [intelligence/](intelligence/) | News/social fetchers and the sentiment scorer behind Falling Knife protection (parent-owned) |
| [tests/](tests/) | Unit/integration tests (parent-owned) |

---

# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

## Child DOX Index

See the operational Child DOX Index in the first half of this file (`signing/`, `docs/`, parent-owned `app/` / `execution/` / `intelligence/` / `tests/`).
