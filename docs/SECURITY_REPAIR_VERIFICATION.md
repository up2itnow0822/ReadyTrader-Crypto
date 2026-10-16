# Security repair verification ledger

Baseline: `3e4898820bd340974f3ccb0b9829dcd74eee49a5`.

This ledger records implementation scope and local regression evidence, not a clean
security certification. A new security-service scan must identify the repaired
commit. No merge, deployment, live trade, wallet transaction or credential rotation
was performed.

| Finding | Implementation                                                                                   | Primary regression coverage                                                           |
| ------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| 1       | Authenticated MPC control, canonical signer policy and exact-digest external approval            | `tests/test_mpc_security.py`, `mpc_signer/control/*_test.go`                          |
| 2       | Containment: opaque live aggregation refused before proposal or signing; paper swaps retained    | `tests/test_execution_security_repairs.py`                                            |
| 3       | Release input as validated environment data, least-privilege jobs                                | `tests/test_delivery_security_repairs.py`                                             |
| 4       | Strict legacy and EIP-1559 fee normalization and caps                                            | `tests/test_execution_security_repairs.py`, `tests/test_mpc_security.py`              |
| 5       | Strict safety settings and aggregate startup errors                                              | `tests/test_safety_config_risk_repairs.py`                                            |
| 6       | Sandbox/global tool admission and container resource limits                                      | `tests/test_research_resource_repairs.py`, `tests/test_safety_config_risk_repairs.py` |
| 7       | Dedicated login budgets and bounded off-loop password checks                                     | `tests/test_api_security_repairs.py`                                                  |
| 8       | Durable payload-bound pre-effect claims, read-only completed replay and conservative uncertainty | `tests/test_execution_security_repairs.py`                                            |
| 9       | Required Grafana Docker secret and loopback publication                                          | `tests/test_delivery_security_repairs.py`; Docker unavailable locally                 |
| 10      | Mandatory live fail-closed freshness and consumption-time recheck                                | `tests/test_safety_config_risk_repairs.py`                                            |
| 11      | Bounded insight fields, retention and atomic database quotas                                     | `tests/test_research_resource_repairs.py`                                             |
| 12      | Finite risk balances/prices/derived values and raw CCXT boolean rejection                        | `tests/test_safety_config_risk_repairs.py`                                            |
| 13      | Private bounded metadata-only webhook diagnostics                                                | `tests/test_delivery_security_repairs.py`                                             |
| 14      | Origin-bound short-lived single-use WebSocket tickets                                            | `tests/test_api_security_repairs.py`, `frontend/src/lib/useWebSocket.test.ts`         |
| 15      | Bounded source bytes and killable absolute request deadlines                                     | `tests/test_research_resource_repairs.py`                                             |
| 16      | Expiring capped limiter state and normalized peer keys                                           | `tests/test_api_security_repairs.py`                                                  |
| 17      | No blind CEX mutation retries; read-only supported reconciliation                                | `tests/test_execution_security_repairs.py`                                            |
| 18      | Disabled-by-default authenticated dual-approved bootstrap ceremony                               | `mpc_signer/control/*_test.go`                                                        |
| 19      | Frontend Docker context excludes local secrets and artifacts                                     | `tests/test_delivery_security_repairs.py`; Docker unavailable locally                 |
| 20      | Bounded authenticated MPC admission and operation deadlines                                      | `mpc_signer/control/*_test.go`                                                        |

## Review corrections

Independent review found and corrected three regressions with failing tests before
fixes: freshness was measured before a provider completed; CCXT boolean prices
were converted to floats before validation; completed execution requests were
re-evaluated against mutable risk/approval gates instead of replaying their durable
result. Regression coverage includes valid provider latency, each boolean price
field and completed/conflicting/pending keys after risk, halt, approval and venue
changes.

## Operational limitations

See [operational boundaries](SECURITY_REPAIR_OPERATIONS.md) and the MPC signer
README for migrations and unsupported paths. In particular:

- Live opaque aggregator swaps are contained, not feature-restored.
- Existing exposed credentials and historical logs require separately approved
  rotation/retention work. The repair does not erase or rotate them.
- Required release-environment reviewers are external repository configuration.
  YAML alone does not enforce approval; configuration was not changed here.
- Process-local API limits and WebSocket tickets require careful multiworker
  routing and shared-budget design before horizontal scaling.
- Existing dependency audit findings are separate from these code repairs. The
  unrelated dependency PR is preserved. Audit failures prevent a clean overall
  security clearance.
- No actual Docker build or live two-party MPC signing ceremony was exercised.
  Native MPC compilation and browser end-to-end results are reported separately
  from the passing unit and control-package tests.

## Initial code-repair verification results

- Final offline Python suite (excluding only `tests/integration/test_exchange_sandbox.py`): **977 passed**, 123 warnings, 126.15 seconds.

- Full Python run before the final three added characterization cases: 977 passed,
  9 skipped and six failed public-exchange tests. The same six network tests failed
  on the baseline. Final additions passed in a separate 40-test signer/delivery run.

- The repeated run exposed fixed-key UAT fixture contamination from durable prior
  results. Each live UAT case now has its own real temporary SQLite claim store;
  all 59 UAT cases passed twice in the same process/environment. Production claim
  persistence was not weakened.

- Full Ruff lint/format checks and Bandit passed. Documentation verifier passed.

- Frontend ESLint, TypeScript, 67 unit tests and production Next.js build passed.

- Go control package passed a fresh race-enabled run (`go test -race ./control -count=1`). Legacy and type-2 cross-language digest/signed-transaction vectors are
  included. Go/C binding compilation against exact historical headers reached the
  linker; final missing native archives remain a blocker.

- Browser E2E: both localhost servers start, but all 18 cases stop at Chromium's
  sandbox-refused socket creation before browser assertions. This is not a passed
  browser acceptance run.

- Dependency consistency (`pip check`) passed, but vulnerability audits did not:
  Python audit printed four rows across two packages (one duplicate advisory row);
  frontend audit reported one critical and seven high findings in unchanged
  dependencies. Separate dependency review is required.

## Dependency follow-up verification (2026-10-16)

This follow-up supersedes the dependency and browser limitations of the initial
local run above, but not the native MPC/link, deployment or live-ceremony limits.

- Final offline Python suite, excluding only `tests/integration/test_exchange_sandbox.py`: **1024 passed**, 123 warnings, 114.08 seconds. The first follow-up run exposed an outdated `twitter.com` route in the local source-test server; correcting it to the official X hostname restored the real-transport regression without weakening assertions.
- Clean Python 3.12 runtime/development resolution and `pip check` pass. The
  regenerated lock preserves unrelated versions and platform markers. PyJWT is
  2.15.1 and multidict is 6.9.1; Tweepy, requests-oauthlib and OAuthlib are absent.
  Both `pip-audit -r requirements.txt` and `pip-audit -r requirements.lock.txt`
  report no known vulnerabilities.
- Next.js and its ESLint configuration are 16.3.8; sharp is 0.35.5 and
  source-map-js is 1.2.2. ESLint, TypeScript, all 67 frontend unit tests and the
  production build pass. All **18 Playwright browser journeys pass** against the
  local paper API after installing the official Chromium binary, without bypassing
  the browser or execution sandbox.
- Full `npm audit` still fails with five high affected-package entries in the
  single unpatched braces dependency chain. Production-only audit reports zero,
  but is diagnostic evidence, not a substitute for the full gate. No exclusions,
  severity downgrades or lint suppressions were added. See
  [dependency security gate](SECURITY_REPAIR_OPERATIONS.md#dependency-security-gate).
- The direct X source has 47 transport/parsing/error regression cases. Test-first
  execution observed 45 failures and two passes before the implementation; the
  combined X, sentiment and UAT regression set then passed all 198 cases.
  Real bounded-transport coverage now matches the exact official `api.x.com`
  hostname; deadline and redirect safeguards remain enabled.
- The CEX ingestion test used a stale 2024 timestamp, causing an unintended public
  exchange fallback. It now uses a fresh timestamp and explicitly asserts that
  the CCXT fallback was not called; all nine CEX integration cases pass. Product
  freshness and network behavior were not relaxed.
- Ruff lint/format, Bandit, documentation verification and Markdown checks pass.
  No live credentials, trades, new service subscriptions or provider accounts were
  used for these tests. Direct X preserves the existing bearer-token configuration;
  TwitterAPI.io would require a separate provider key and was not configured.
