## Security Policy

### Supported versions

| Version                    | Status                                             |
| :------------------------- | :------------------------------------------------- |
| 0.2.x (unreleased, `main`) | Supported — active development; see `CHANGELOG.md` |
| 0.1.x                      | Supported for security fixes only                  |

No version has been tagged or released yet (`git tag -l` / `gh release list` both empty as of
2026-09-23) — "0.2.x" above means current `main`, not a downloadable release.

### Security posture (2026-09)

September 2026 hardening landed across several PRs (each verified live against GitHub with
`gh pr view <n>` on 2026-09-23):

- **#4** — SEC-001/002: `/ws` requires a JWT when auth is enabled; `.env.live` and
  `.env.*.local` are gitignored.
- **#7** — Closed issue #6's live-safety gaps: `start_cex_private_ws` now requires live
  execution to be allowed before opening a private stream; paper `place_cex_order` no longer
  fills at a fabricated placeholder price; paper `get_cex_balance` needs no CEX credentials.
- **#12** — Restored real CI: `.github/workflows/ci.yml` had been an 8-line Node stub since
  2026-03-11 with no Python test/lint/security gate running on push or PR; this closed that
  half of issue #2's 2026-09-06 finding.
- **#13** — M2 back-end security hardening: agent-supplied strategy code now runs in an
  isolated child process (`strategy_sandbox.py`: RestrictedPython plus a static AST pre-check
  plus POSIX rlimits — not a filesystem jail, see `docs/STRATEGY_SANDBOX.md`); the approval
  gate's in-flight flag became a per-call `ContextVar` instead of a process-wide switch; paper
  ledger writes became atomic.

Fail-closed defaults already in place before this window — `TRADING_HALTED` defaults `true`,
`api_server` refuses to start under `DEV_MODE=false` without JWT auth or with wildcard CORS,
`SIGNER_TYPE=env_private_key` is refused whenever `PAPER_MODE=false` or
`LIVE_TRADING_ENABLED=true` — remain unchanged and were re-verified in
`docs/uat/2026-09-23-reverification.md`.

### Reporting a Vulnerability

If you believe you have found a security vulnerability, **do not** open a public issue.

Please report details privately with:

- **Description** of the issue
- **Reproduction steps**
- **Impact** assessment
- Any relevant **logs** or **screenshots** (redact secrets)

### Scope Notes

- This project can be configured for **live trading** (`PAPER_MODE=false`). Keep secrets out of source control.
- This project uses a **signer abstraction**; prefer keystore-based signing over raw private keys.
- For live trading deployments, review `docs/THREAT_MODEL.md` and follow least-privilege patterns.

### Known gaps

- **Sentinel signer (issue #2, open since 2026-09-06):** `docker-compose.sentinel.yml` runs
  `sentinel/app.py` bound to `0.0.0.0:8888` with `SIGNER_TYPE=env_private_key` and a raw
  `PRIVATE_KEY` environment variable. Its `POST /sign_transaction` and `GET /address` routes
  have no authentication — no API key, JWT, or middleware; the only integrity check is an
  optional client-supplied `intent` field a caller can simply omit. **Do not deploy
  `docker-compose.sentinel.yml`** until this is authenticated or the compose file is marked
  unsupported. **PR #18** (opened 2026-09-23, `fix/sentinel-signer-auth-2026-09-23`, open and
  mergeable, not yet merged) adds required `Authorization: Bearer` auth to both routes and
  stops publishing port 8888 on the host; until it merges, `main` has the gap described above
  — see `UAT.md`.
- **`EXECUTION_MODE=auto` routing (issue #8):** `venue_allowed()` denies the documented
  default `EXECUTION_MODE=auto`, failing closed (denies rather than misroutes) but blocking
  legitimate use of that default. Fix is PR #9 — open and mergeable, not yet merged, as of
  2026-09-23. Operators following the documented BTC production path are unaffected:
  `env.live.btc.example` sets `EXECUTION_MODE=cex` explicitly.
- **Frontend dependency advisories:** `npm audit --include=dev` against `frontend/` reported
  **0 vulnerabilities** (549 dependencies: 63 prod, 448 dev, 89 optional, 43 peer) as of
  2026-09-23 — see `docs/uat/2026-09-23-reverification.md` for the exact command and output.
- **M4 operator dashboard e2e coverage:** the 18-journey Playwright suite in `frontend/e2e/`
  is not wired into any GitHub Actions workflow, so dashboard regressions are not caught
  automatically — see `docs/uat/2026-09-23-reverification.md`.

### Secret scanning guidance

- See `.github/secret-scanning.md` for recommended GitHub settings and local hygiene.
