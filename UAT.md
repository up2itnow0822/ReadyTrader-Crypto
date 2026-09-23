# UAT — ReadyTrader-Crypto

**Status:** as of 2026-09-23 (updated when PR #18 merged): paper-first and fail-closed by
default. BTC production-minus-dust hardening, docs, the operator dashboard, the
`EXECUTION_MODE=auto` routing fix (PR #9) and sentinel signer authentication (PR #18) are on
`main`, but this repo does **not** yet meet its own graduation gate (Section 6): the operator
dashboard's e2e suite has not been independently re-run, the cross-process approval-visibility
gap is open, and the owner-only gates remain. Phase 4 (any live capital, including a single
dust-sized trade) requires separate, explicit owner authorization regardless of gate status.

______________________________________________________________________

## 1. What "graduate to production" means for this repo

"Production" for ReadyTrader-Crypto means one narrow, specific thing: **spot BTC/USDT (or
BTC/USD) trading via a centralized exchange (`EXECUTION_MODE=cex`), under fail-closed defaults,
with every live order requiring explicit human approval**
(`EXECUTION_APPROVAL_MODE=approve_each`). It does not mean unattended fully-automatic trading,
DEX execution, or any asset other than BTC. Graduation happens in two stages that this
repository keeps deliberately separate:

- **"Production-minus-dust"** — every fail-closed control, the paper trading path, the risk
  guardian, the operator dashboard, and the ops pack are built, tested, and documented; **no
  live capital has moved**. This is the gate this document tracks.
- **Phase 4 (live dust trading)** — a small number of minimal-value real trades, run only after
  production-minus-dust is met, real CEX/signer credentials are in place, and Bill has given
  **written, explicit, separate authorization**. No automated pass — including this one — may
  claim Phase 4 is satisfied. See `docs/LIVE_TESTING_PROTOCOL.md` Phase 4 and the governing
  plan at `~/.cursor/plans/readytrader_btc_production_fefcf972.plan.md` (owner's device; not
  part of this repo) for its origin and locked scope.

## 2. Current state — shipped, open, limits

**Shipped (production-minus-dust hardening), each PR verified live with `gh pr view <n>` on
2026-09-23 — see `CHANGELOG.md`'s "0.2.0" section for the full grouping:**

- BTC production profile + Hermes stdio MCP surface — PR #3, #4
- Paper-trading correctness fixes — PR #5, #7 (closed issue #6)
- Falling Knife / sentiment risk gate made reachable and fail-closed — PR #10, #11, #17
- Restored real CI (closed half of issue #2) — PR #12
- M2 back-end security hardening (sandbox isolation, approval-gate `ContextVar`, paper-ledger
  atomicity) — PR #13
- M3 documentation truth + CI drift guard — PR #14
- M4 operator dashboard (approve/reject UI + 18-journey Playwright e2e suite) — PR #15

**Resolved on 2026-09-23 (re-verify at UAT):**

- **PR #9** (issue #8): `EXECUTION_MODE=auto` routes like `hybrid`; unknown modes still fail
  closed — T10.
- **PR #18** (issue #2's P0): sentinel signer requires Bearer auth and fails closed without a
  token; no host port; `RemoteSigner` enforces `REMOTE_SIGNER_REQUIRE_TLS` — T11. Sentinel stays
  a dev/demo signer.

**Open blockers:**

- **Cross-process approval-proposal visibility (see T5, Section 6).** A proposal created by
  the MCP process is invisible to the API/dashboard process in the standard two-process
  deployment (`docs/ARCHITECTURE.md#approval-gate`), so the mandated BTC-live `approve_each`
  flow cannot currently be completed through the dashboard. Elevated to a graduation gate in
  this pass rather than left as a footnote.
- **M4 dashboard e2e has no independent re-verification.** The 18-journey suite
  (`frontend/e2e/`) is wired into no GitHub Actions workflow and was last run once, manually,
  by its own PR author at merge time. The 2026-09-23 re-verification pass attempted to run it
  and could not — see Section 4, row T6, and
  `docs/uat/2026-09-23-reverification.md` Section 5.

**Known limits (apply to every automated pass to date, this one included):**

- No live CEX API keys configured anywhere in this consolidation effort, by design.
- No remote signer configured or reachable — `SIGNER_TYPE=remote` is template-only.
- 55 of 603 collected pytest cases fail on **this specific macOS host** for one shared root
  cause (the sandbox's `RLIMIT_AS` self-check; macOS does not honor the requested limit the way
  Linux does) — not independently re-verified against Linux in this pass; GitHub Actions' own
  last run on `fa52d1e` was green. Full detail:
  `docs/uat/2026-09-23-reverification.md` Section 3.

______________________________________________________________________

## 3. Environment & preconditions (exact commands)

**Paper (default, no secrets needed):**

```bash
git clone https://github.com/up2itnow0822/ReadyTrader-Crypto.git
cd ReadyTrader-Crypto
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp env.example .env   # defaults already paper-safe; no edits required to run T1-T8 below
```

Defaults from `env.example` that matter for this matrix: `PAPER_MODE=true`,
`LIVE_TRADING_ENABLED=false`, `TRADING_HALTED=true`, `EXECUTION_MODE=hybrid`,
`EXECUTION_APPROVAL_MODE=auto`, `SIGNER_TYPE=env_private_key` (fine in paper mode; forbidden
the moment `PAPER_MODE=false`).

**CI-equivalent full suite (matches `.github/workflows/ci.yml`):**

```bash
.venv/bin/pip install --no-deps -r requirements.lock.txt && .venv/bin/pip check
npm ci --prefix frontend && npm audit --prefix frontend
PATH="$PWD/.venv/bin:$PATH" make check
PATH="$PWD/.venv/bin:$PATH" make security
.venv/bin/pip-audit -r requirements.lock.txt
```

On a machine whose shell sets `NODE_ENV=production` (as this consolidation's Mac does), run the
`npm` steps with `env -u NODE_ENV` — see `docs/uat/2026-09-23-reverification.md` Section 1 for
why; `frontend/AGENTS.md` documents the same trap for `npm audit --omit=dev` specifically.

**Live-but-halted profile (owner-supplied secrets; never commit `.env.live`):**

```bash
cp env.live.btc.example .env.live   # fill JWT secret, admin hash, CEX trade+read keys (NO
                                     # withdraw), remote signer URL — out of band, never in git
docker-compose -f docker-compose.live.yml --env-file .env.live config    # validate only
docker-compose -f docker-compose.live.yml --env-file .env.live up -d     # starts HALTED
curl -s http://localhost:8000/api/health                                 # expect trading_halted: true
                                                                           # (this route is intentionally public — it proves the
                                                                           # process is up, not that auth is enforced)
curl -s -H "Authorization: Bearer $JWT" http://localhost:8000/api/metrics # protected route: 200 with a valid JWT
curl -s http://localhost:8000/api/metrics                                # same route with no token: expect 401 — together these
                                                                           # two calls prove auth is actually enforced
```

______________________________________________________________________

## 4. Test matrix

| ID  | Workflow                                                 | Steps (exact commands)                                                                                                                                                                                                                                | Expected result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Evidence to capture                                                                  | Result                                                                                                                                                                                                                                                                                                                                                                                                                     |
| :-- | :------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | Install/config, paper default                            | `python3 -m venv .venv`<br>`.venv/bin/pip install --no-deps -r requirements.lock.txt`<br>`.venv/bin/pip check`                                                                                                                                        | Clean install; `PAPER_MODE=true`/`LIVE_TRADING_ENABLED=false`/`TRADING_HALTED=true` hold without edits                                                                                                                                                                                                                                                                                                                                                                                                                       | `pip check` output                                                                   | **PASS** — re-verified 2026-09-23, `docs/uat/2026-09-23-reverification.md` §2.1                                                                                                                                                                                                                                                                                                                                            |
| T2  | MCP tool roster                                          | Start `server.py` over stdio (README "Zero-key quickstart" config); `initialize`; `list_tools()`                                                                                                                                                      | 29 tools returned; matches `docs/TOOLS.md` exactly                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | JSON tool-name list                                                                  | **PASS** — 2026-09-23, reverification §4                                                                                                                                                                                                                                                                                                                                                                                   |
| T3  | Paper trading flow                                       | Over the same MCP session: `call_tool` → `deposit_paper_funds(asset:"USDC", amount:10000.0)`, then `call_tool` → `validate_trade_risk(side:"buy", symbol:"BTC/USDT", amount_usd:600, portfolio_value:10000)`                                          | Deposit succeeds; oversized trade (6% > 5% limit) is blocked with a stated reason                                                                                                                                                                                                                                                                                                                                                                                                                                            | Tool-call JSON envelopes                                                             | **PASS** — 2026-09-23, reverification §4                                                                                                                                                                                                                                                                                                                                                                                   |
| T4  | Risk gates: Falling Knife / sentiment fail-closed        | `PAPER_MODE=true DEV_MODE=true pytest tests/test_sentiment_gate.py tests/test_risk.py -q`                                                                                                                                                             | Sentiment reports `status` truthfully (never a false measured neutral); Falling Knife blocks per PR #10/#11/#17's fixed behavior                                                                                                                                                                                                                                                                                                                                                                                             | pytest output                                                                        | **PASS** — both files are inside the 543-passed set from the 2026-09-23 full run (neither appears in the 55 sandbox-only failures; reverification §3)                                                                                                                                                                                                                                                                      |
| T5  | Approval gate: `approve_each` vs `auto` (explained)      | `pytest tests/test_approval_api.py -q`; compare `env.example` (`EXECUTION_APPROVAL_MODE=auto`) against `env.live.btc.example` (`EXECUTION_APPROVAL_MODE=approve_each`)                                                                                | `auto` (the paper/dev default) executes immediately; `approve_each` (the mandated BTC-live default) returns a proposal (`request_id`+`confirm_token`) instead — **only in live mode**, paper never proposes. **Graduation-blocking limitation, not a footnote**: a proposal created by the MCP process is invisible to the API/dashboard process in the standard two-process deployment (`docs/ARCHITECTURE.md#approval-gate`), so the mandated BTC-live `approve_each` flow cannot be completed through the dashboard today | pytest output; `docs/ARCHITECTURE.md#approval-gate`                                  | **PARTIAL** — unit-level approval-gate tests PASS, but the cross-process proposal-visibility gap blocks the mandated live `approve_each` flow end-to-end; this is a **graduation gate** (Section 6), not a plain PASS with a footnote — see Section 2                                                                                                                                                                      |
| T6  | Operator dashboard approve/reject (M4)                   | `cd frontend && npm ci --include=dev && env -u NODE_ENV npm run e2e` (builds, then runs the 18-journey Playwright suite against the real API harness)                                                                                                 | All 18 journeys pass; HTML report generated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Playwright HTML report / trace files                                                 | **LIMIT — not run.** Chromium install hung twice on this host in the 2026-09-23 pass (`docs/uat/2026-09-23-reverification.md` §5). Last actual evidence: PR #15's own manual run at merge time (unverified independently, per the PR's own text)                                                                                                                                                                           |
| T7  | Live-safety halt gates                                   | `pytest tests/test_live_safety_gates.py -q`                                                                                                                                                                                                           | `start_cex_private_ws` refuses unless live execution is allowed; `stop_cex_private_ws`/`list_cex_private_updates` work even while halted                                                                                                                                                                                                                                                                                                                                                                                     | pytest output                                                                        | **PASS** — inside the 543-passed set, 2026-09-23                                                                                                                                                                                                                                                                                                                                                                           |
| T8  | JWT / CORS / WS auth                                     | `pytest tests/test_api_server.py tests/test_settings_validation.py -q`; also `DEV_MODE=false API_AUTH_REQUIRED=false python -c "import api_server"`                                                                                                   | api_server refuses to start under `DEV_MODE=false` without JWT auth or with wildcard CORS; `/ws` requires a JWT when auth is on                                                                                                                                                                                                                                                                                                                                                                                              | pytest output; subprocess `RuntimeError` text                                        | **PASS** — inside the 543-passed set, 2026-09-23                                                                                                                                                                                                                                                                                                                                                                           |
| T9  | Remote signer (owner-supplied)                           | `SIGNER_TYPE=remote SIGNER_REMOTE_URL=<owner-supplied> python -c "from signing.factory import get_signer; print(get_signer().get_address())"`                                                                                                         | Resolves a signer address; no live transaction is signed                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Printed address; TLS/reachability notes                                              | **LIMIT — not exercised.** No remote signer is configured or reachable in this consolidation environment; owner must supply a URL                                                                                                                                                                                                                                                                                          |
| T10 | `EXECUTION_MODE=auto` routing (issue #8, fixed by PR #9) | `.venv/bin/python -c "from execution.router import venue_allowed; print(venue_allowed('auto','cex'))"` and `pytest tests/test_execution_router.py -q` on the release SHA                                                                              | Prints `True`; the routing table tests pass (`auto` routes like `hybrid`, unknown modes denied)                                                                                                                                                                                                                                                                                                                                                                                                                              | Interpreter + pytest output                                                          | Fixed on `main` by PR #9 (merged 2026-09-23); re-run at UAT time                                                                                                                                                                                                                                                                                                                                                           |
| T11 | Sentinel signer auth (issue #2 P0, fixed by PR #18)      | `pytest tests/test_sentinel_auth.py tests/test_remote_signer.py -q`; then start `uvicorn sentinel.app:app` with and without a 32+ character `SENTINEL_AUTH_TOKEN` and call `GET /address` with no, wrong, and correct `Authorization: Bearer` headers | Token unset/short: 503 on every route; missing or wrong token: 401; correct token: 200; `/docs` and `/openapi.json` not served; `RemoteSigner` refuses a non-https URL unless `REMOTE_SIGNER_REQUIRE_TLS=false`                                                                                                                                                                                                                                                                                                              | HTTP status codes + pytest output                                                    | Fixed on `main` by PR #18 (merged 2026-09-23); re-run at UAT time. Sentinel remains a dev/demo signer, not a production custody path                                                                                                                                                                                                                                                                                       |
| T12 | Release-readiness checklist                              | Review `RELEASE_READINESS_CHECKLIST.md` §1–8 and its Production Deployment Checklist                                                                                                                                                                  | §1–8 fully checked and accurate; Production checklist's code-enforced items (✅) match code; deploy-time items (secrets, `TRADING_HALTED=false`, monitoring) are correctly left unchecked pending operator action                                                                                                                                                                                                                                                                                                            | The checklist file itself                                                            | **PASS, with one correction made in this pass**: §8 had checked off "GitHub Release notes include upgrade steps / breaking changes / safety reminders," which was false — no release exists (`CHANGELOG.md`, `git tag -l`/`gh release list`). Unchecked those boxes in `RELEASE_READINESS_CHECKLIST.md` §8 to match reality; §1–7 reviewed and accurate; deploy-time boxes elsewhere are intentionally, honestly unchecked |
| T13 | Phase 4 — live dust trade(s)                             | Owner-supplied `.env.live` with real credentials; one minimal BTC spot order placed under `EXECUTION_APPROVAL_MODE=approve_each` with an explicit written operator OK, then `TRADING_HALTED=true` restored                                            | One dust-sized live order fills; exchange history, balance change, and audit-log entry all agree                                                                                                                                                                                                                                                                                                                                                                                                                             | Exchange order confirmation; `data/audit.db` entry; operator's written authorization | **NOT RUN — requires separate, explicit, written owner authorization.** Out of scope for this and every prior automated pass; see Section 1                                                                                                                                                                                                                                                                                |

______________________________________________________________________

## 5. Rules of evidence

- **UAT means a real workflow was executed against real code** — starting the actual server
  process, calling actual MCP tools or HTTP endpoints, running the actual test suite — not a
  description of what the code is expected to do, and not a mock standing in for the real
  dependency.
- **Skipped, mocked, unavailable, or handler-only is a LIMIT, never a PASS.** A test that
  didn't run because credentials were absent, a suite that hung before producing a result, or a
  code path exercised only through a stub is reported as a limit with its exact reason — it is
  never marked PASS, and it never silently disappears from the matrix.
- **A finding gets repaired and independently retested**, not just noted, wherever it is in
  scope for the pass that found it. Findings that are out of scope for the pass that found them
  (for example, a docs-only pass finding a code defect) are reported honestly and handed off —
  never fixed by editing around the DOX boundary, and never silently downgraded to "known
  issue" without a link to where it is actually tracked (an issue or PR number).
- **Every result above cites where its evidence lives.** For this UAT pass that is
  `docs/uat/2026-09-23-reverification.md` (exact commands, full output, pass/fail/skip counts)
  plus this document's own T-row citations. Future UAT passes add a new dated file under
  `docs/uat/` and update the citations here and in Section 8 — they do not overwrite prior
  evidence files.
- **Claims this document does not make:** it does not certify Phase 4 readiness, does not
  assert the dashboard e2e suite passes
  on this SHA, and does not assert any live capital has moved. Where a gate is not met, this
  document says so plainly rather than rounding up.

## 6. Graduation gates

Every box below must be checked, with a linked evidence entry, before this repo is considered
graduated to "production-minus-dust." None are checked as of 2026-09-23.

- [ ] **PR #9 merged** (closes issue #8 — `EXECUTION_MODE=auto` routes correctly) — merged
  2026-09-23; tick after T10 passes on the release SHA
- [ ] **Sentinel signer fix merged** (closes issue #2's P0 — `sentinel/app.py` authenticated) —
  **PR #18** merged 2026-09-23; tick after T11 passes on the release SHA
- [ ] **Fresh re-verification green on the release SHA** — the CI-equivalent suite, the MCP
  stdio smoke test, and the frontend e2e suite all pass with zero unexplained failures on
  the exact commit being graduated (today's pass, `fa52d1e`, has 55 pytest failures
  attributed to a host-specific macOS limitation — not confirmed clean on Linux in this
  pass — and did not complete the e2e suite at all; see
  `docs/uat/2026-09-23-reverification.md`)
- [ ] **M4 dashboard e2e wired into CI, or run with attached evidence** on the release SHA — an
  HTML report or recording, not a description of the suite
- [ ] **Cross-process approval-proposal visibility fixed or worked around** (see T5) — a
  proposal created by the MCP process must become confirmable by the API/dashboard process
  before the mandated BTC-live `approve_each` flow can be completed through the dashboard
  (`docs/ARCHITECTURE.md#approval-gate`'s documented gap)
- [ ] **Owner-supplied `.env.live` dry-run** — real JWT secret, admin hash, CEX trade+read
  (no-withdraw) keys, and remote signer URL, with the live-but-halted compose stack started,
  `/api/health` confirming `trading_halted: true` (that route needs no auth by design), and a
  JWT-authenticated call to a protected route (e.g. `/api/metrics`) succeeding while the same
  call with no token returns 401 — proving auth is actually enforced, not just that the
  process started
- [ ] **Phase 4 separately authorized** — Bill's explicit, written go-ahead for one minimal
  live dust trade, given only after every box above is checked

## 7. Owner-only actions

These cannot be completed by an automated pass and are Bill's alone:

- Confirm the sentinel signer stays dev/demo-only (PR #18 authenticated it; production custody
  uses keystore, a KMS/HSM-backed remote proxy over https, or `cb_mpc_2pc` — `docs/CUSTODY.md`)
- Supply real `.env.live` secrets (JWT secret, admin password hash, CEX trade+read keys with
  **no withdraw permission**, IP allowlist, remote signer URL) out of band; never commit them
- Decide whether `EXECUTION_APPROVAL_MODE`'s shipped default should change from `auto` to
  `approve_each` to match the stated "per-trade approval" production requirement, or whether a
  documentation-only fix (making the `auto` default's risk explicit) is sufficient — this is an
  open decision, not resolved by this document
- Give the written, explicit Phase 4 authorization described in Section 6 — and only after
  every other gate is checked
- Sign off Section 8 below

## 8. Sign-off table

| Gate                              | Evidence                                   | Result                                   | Date       | Signed (Bill) |
| :-------------------------------- | :----------------------------------------- | :--------------------------------------- | :--------- | :------------ |
| PR #9 merged                      | `gh pr view 9`, T10                        | Merged 2026-09-23 - re-verify T10 at UAT | 2026-09-23 |               |
| Sentinel signer fix merged        | `gh pr view 18`, T11                       | Merged 2026-09-23 - re-verify T11 at UAT | 2026-09-23 |               |
| Fresh re-verification green       | `docs/uat/2026-09-23-reverification.md`    | Not fully green — see Limits (§7 there)  | 2026-09-23 |               |
| Dashboard e2e (CI or evidenced)   | `docs/uat/2026-09-23-reverification.md` §5 | Pending — not run                        | 2026-09-23 |               |
| Cross-process approval visibility | `docs/ARCHITECTURE.md#approval-gate`, T5   | Pending — documented gap, not fixed      | 2026-09-23 |               |
| Owner `.env.live` dry-run         | —                                          | Pending                                  |            |               |
| Phase 4 authorization             | —                                          | Pending                                  |            |               |
