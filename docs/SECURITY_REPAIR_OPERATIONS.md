# Security repair operational boundaries

## Release authorization

Release input is passed as environment data and validated before writing workflow
outputs. Ordinary jobs receive read-only repository access and checkout does not
persist credentials. Only the release job receives contents-write permission; it
references the `release` GitHub environment. Repository administrators must configure
required reviewers and branch/tag protections for that environment before relying
on it as an approval gate. Referencing an environment in YAML alone does not create
an enforced approval policy. No repository settings were changed by this repair.

## Local observability

See [local observability setup](../deploy/observability/README.md). Grafana requires
an operator-provided Docker secret rather than a default password. Monitoring ports
bind to loopback. Existing persisted Grafana passwords require separate rotation.

## Webhook diagnostics

Delivery failures persist only provider, random correlation ID, exception class and
timestamp in `READYTRADER_DATA_DIR/webhook_dead_letter.jsonl` (default `data/`). The
file is owner-readable/writable only and stops accepting records at a one-MiB cap.
Payloads, destination URLs, tokens, chat IDs and raw exception messages are excluded.
This intentionally prevents replaying failed notifications from the diagnostic file.
Older `logs/webhook_dead_letter.jsonl` files may contain credentials and payloads.
Review and remove them using the operator's retention policy, and rotate any exposed
credentials through separately authorized processes. This repair does not delete
operator data or rotate credentials.

## Frontend builds

The frontend build context excludes local environment files, keys, certificate
bundles, dependency trees, caches and generated reports. Do not pass actual secrets
through Docker build arguments. Use BuildKit secret mounts if a future build step
requires a private dependency credential.

## Safety settings and live risk inputs

Unknown execution, approval, risk or signer modes and malformed boolean settings
refuse startup. Explicit boolean values are true/false, 1/0, yes/no and on/off;
blank values are not defaults. Startup reports invalid field names together.

Live/non-paper configurations require MARKETDATA_FAIL_CLOSED=true. Risk sizing
consumes finite, fresh prices with explicit acceptable metadata and rechecks age
at use time. Invalid balances, prices or overflowed account valuations are refused
as risk_blocked. Genuine held-asset exits into cash remain available when only
price data is unavailable; account inspection and cancellation stay available
under the halt switch.

The live API and MCP compose services have read-only roots with writable data and
bounded temporary storage, two-GiB memory, two-CPU and 128-PID limits, no swap
expansion, no-new-privileges and dropped capabilities. Validate operator volume
permissions and plugin temporary-file needs before deployment. No live deployment
was performed by this repair.

## Live execution migration and reconciliation

Live place_cex_order, transfer_eth and replace_cex_order require an explicit
1–256-character idempotency_key before an effect. Approved proposals supply their
request ID. The default SQLite execution_attempts table binds a canonical payload
hash to a pending owner and lease before sending. Expiry becomes uncertain, not
available for retry. Old unbound cache entries are not replayed as new requests.
Completed payload-identical requests return their durable original result before
mutable risk/approval/halt gates; this is a read-only replay, not a new execution.
Payload conflicts and pending/uncertain claims remain refused. Fresh requests still
require every execution gate. In-memory SQLite claim stores are refused.

CEX client-order IDs are recorded before submission. Supported Binance-family
client-ID lookups may recover a known order after transport ambiguity; no create or
edit is blindly retried, even on exchanges that support IDs. For other exchanges,
inspect orders/fills manually using the persisted evidence. Native transfers record
the signed transaction hash, nonce and sender before broadcast; inspect chain
transaction/receipt and sender nonce. A single not-found response is not proof of
non-execution. Do not delete pending/uncertain records or change keys to bypass the
block. There is no automatic reset/unlock tool in this repair. Audit-write failures
after a durably recorded success do not convert that success to a retryable failure.

Opaque 1inch live swaps are disabled with unsupported_swap_semantics before
proposal/provider/signing/broadcast. The current swap API lacks an approved
minimum-output/deadline contract and arbitrary aggregation semantics cannot be
proven from its envelope. This closes the unsafe route by containment; restoring
live aggregated swaps requires a separately designed canonical intent/decoder and
verification integration. Paper swaps and validated native-transfer paths remain.

## Authentication and WebSocket migration

Login always enforces five attempts per minute per trusted peer and normalized
username, twenty aggregate attempts per minute and at most two concurrent password
checks, independent of the optional general limiter. Limiter buckets expire and
are capped at 4096 keys; saturation refuses new keys rather than evicting active
budgets. IPv6 peer budgets use /64 networks. Configure trusted proxies carefully.

Browser clients first authenticate POST /api/auth/ws-ticket and then offer
`readytrader,ticket.<opaque>` as WebSocket subprotocols. Tickets are Origin-bound,
single-use, expire in thirty seconds and have a 1024-entry capacity. The server
negotiates only `readytrader`. Query-string JWTs and tickets are refused; nonbrowser
clients may use the authorization header. Tickets and budgets are process-local:
multiple workers need sticky routing and an independently reviewed shared budget
store; aggregate limits otherwise multiply by worker count.

## Research and source resource limits

Backtests have one tool invocation in flight and six requests per minute. The
sandbox allows two global runs including preparation, 500000 total candles,
512 MiB child memory and the existing 120-second deadline. Research/news tools
share four concurrent slots; news, sentiment and regime calls have twelve requests
per minute. Insight writes allow thirty and reads sixty requests per minute.
These budgets use fixed tool keys, not caller-controlled agent IDs.

Insights validate UTF-8 byte lengths (symbol 64, agent 128, reasoning 8192,
JSON metadata 4096), finite confidence from zero to one, normalized
bullish/bearish/neutral sentiment and integer TTL from one to 86400 seconds.
SQLite transactions enforce 1000 rows per agent and 5000 total, reads return at
most 100 rows and expired/older-than-24-hour rows are pruned. Initial excess
legacy rows are evicted oldest first. The database page cap is 128 MiB; existing
oversized files require offline operator maintenance and do not automatically
shrink. Back up retained research data before maintenance.

Source requests run in killable, reaped subprocesses with a ten-second absolute
deadline including DNS, headers and body, one-MiB body and 16-KiB header limits.
At most four run at once. Multi-source calls can take twenty seconds overall.
SDK retries cannot extend the deadline. The isolated source environment deliberately
ignores proxy, netrc and custom-CA environment configuration: direct HTTPS with
standard CA trust is required. Redirects and compressed response bodies are
refused. Credentials are passed only over child stdin, never command arguments.
Limits return resource_busy/rate_limited, invalid insights return invalid_insight,
and failed or oversized sources return source_unavailable rather than empty news.

## MPC deployment and ceremony boundary

MPC runtime controls require pinned mTLS identities, canonical transaction policy
and a separately held operator's single-use exact-digest approval. Bootstrap is
isolated and disabled by default; key ceremony requires two operator approvals and
explicit expected-public-key commit. These are new operator prerequisites, not
credentials generated or provisioned by this repair.

Staged ceremony metadata is in memory. Restart before commit, or a peer committing
while the other fails, requires manual reconciliation; this is not crash-atomic
two-party commit or automatic restart/resume. A proof consumed before failure stays
consumed. Exclusive replay/audit records are durable but remain mutable by their
filesystem owner, not an immutable external audit system. Preserve records and
staged identity when investigating; do not rerun key generation as a retry.

The complete native signer build and real two-party ceremony require independent
validation before live use. Passing standalone control-package tests does not
prove native-library compatibility or transport correctness. See the signer README
for exact policy and approval formats and recovery requirements.
