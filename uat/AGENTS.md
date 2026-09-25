# uat/

> Child AGENTS.md. Governed by the DOX chain above it; the root AGENTS.md is authoritative
> for project-wide rules. This doc controls local details for its subtree.

## Purpose
User Acceptance Testing record for this project: every UAT run's checks, findings, fixes,
retests, and evidence. This folder is the audit trail that proves the project works as a
user would use it — not that its tests pass, but that its features do.

## Ownership
- Owns: `UAT-LOG.md` (rendered), `runs/<run-id>/findings.json` (ledger, source of truth),
  `evidence/<run-id>/` (screenshots, HTTP captures, command output, DB dumps).
- Does not own: the code under test, its test suite, or CI. Fixes made during UAT land in
  the code's own folders and are governed by those folders' AGENTS.md.
- Parent retains: what "done" means for a release, branch/PR policy, deploy rules.

## Local Contracts
- The ledger is written only through `uat_log.py` (from the `uat` skill). `UAT-LOG.md` is
  regenerated with `uat_log.py render`; never hand-edit it — edits are lost on next render.
- Run ids are `YYYY-MM-DD-NN`. One ledger and one evidence folder per run. Runs are never
  deleted; a superseded run stays as history.
- Check ids are `<SECTION>-<NN>` (e.g. `BE-03`, `FE-12`, `MEM-02`). A FAIL keeps its id
  through fix and retest so the history is one thread.
- Every FAIL has: severity, steps, expected, observed, at least one evidence path. Every
  fix has: root cause, files, commit. Every VERIFIED has a fresh retest evidence path
  captured after the fix — the original failing capture never counts as retest evidence.
- Evidence paths are recorded relative to the repo root (`uat/evidence/<run>/<file>`).
- Nothing in `evidence/` contains secrets: tokens, cookies, API keys, and `.env` contents
  are redacted before capture. If a capture cannot be redacted, describe it instead of
  storing it.
- BLOCKED is reserved for checks that cannot be executed in this environment (missing
  credentials, unreachable third-party, hardware). It always names what is needed. A
  check that *could* run but fails is a FAIL, never BLOCKED.

## Work Guidance
- Sections run in this order unless the project makes it impossible: preflight, backend,
  data, memory, frontend, integrations, cli, config, docs, regression. Fix and retest at
  the end of each section before starting the next.
- A run is closed only when `uat_log.py summary` reports zero unresolved items. BLOCKED
  items may remain, each with a stated unblock condition.

## Verification
- `python3 <uat-skill>/scripts/uat_log.py --root <repo> summary --run <run-id>` prints
  `UNRESOLVED: 0` (or omits the line) and every FAIL row shows VERIFIED.
- Every evidence path in `UAT-LOG.md` resolves to a file.

## Child DOX Index
No child boundaries.
