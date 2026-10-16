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

## Local verification results

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
