# MPC signer: authenticated two-party EVM signing

This optional service uses Coinbase cb-mpc. The runtime control plane now requires
TLS 1.3 client authentication, an exact pinned workload/peer certificate, mandatory
signer policy, and a separately signed, single-use transaction approval. Neither
party accepts arbitrary digest requests. No live keys, ceremonies, or signing were
performed during the security repair.

## Migration and supported operations

The old HTTP `/sign_digest` and runtime `/dkg` endpoints are removed. Existing
plaintext clients and previously unapproved requests intentionally stop working.
The supplied compose file publishes **no host ports** and uses an internal network.
Attach the authorized calling service to that network explicitly; do not restore a
public plaintext listener. Production parties should be on independently secured
hosts. Each party mounts only its own private TLS key, not the peer's key or CA key.

Supported transactions are legacy EIP-155 and EIP-1559 type 2 with an empty access
list. Both parties independently reconstruct the Ethereum signing digest and enforce:

- Allowed chains; native-transfer destinations and native-value caps.
- ERC-20 `transfer(address,uint256)` with an allowed token and decoded recipient.
- ERC-20 `approve(address,uint256)` with an allowed token and decoded spender.
- Token-amount, gas, per-gas fee, and worst-case total-fee caps. Type 2 priority fees
  cannot exceed max fees; mixed legacy/dynamic fee fields are refused.
- No contract creation, unknown calldata, trailing ABI data, noncanonical ABI
  addresses, arbitrary router calls, or nonempty access lists.

Opaque 1inch aggregation is not supported. This is not a general-purpose digest or
contract signer. The independent operator approval is additional to application
trade approval; `/api/approve-trade` does not grant MPC approval authority.

## Runtime configuration

Existing party transport variables remain: `MPC_ROLE_INDEX` (exactly `0` or `1`),
`MPC_PARTY0_ADDR`, `MPC_PARTY1_ADDR`, `MPC_CA_CERT`, `MPC_CERT`, `MPC_KEY`,
`MPC_PARTY0_CERT`, `MPC_PARTY1_CERT`, and `MPC_KEYSHARE_PATH`.

- `MPC_HTTP_LISTEN`: TLS listener, default `127.0.0.1:8787`.
- `MPC_PEER_HTTP_URL`: leader's follower HTTPS origin, no path or credentials.
- `MPC_WORKLOAD_CERT`: leader's exact authorized caller certificate (public PEM).
- `MPC_APPROVAL_PUBLIC_KEY`: independent operator Ed25519 public key, 64 lowercase
  hex characters. The application and both MPC services must **not** hold its
  private key. Provision it through the operator's existing signing system.
- `MPC_POLICY_FILE`: required bounded JSON policy. Copy `policy.example.json` into
  `policy.party0.json` and `policy.party1.json`, then independently review budgets
  and lowercase address allowlists. The example authorizes no destinations.
- `MPC_REPLAY_DIR`: durable private replay/audit directory, default beside the share
  in `approvals/`. Keep it across service restarts and backups. Never clear it to
  retry an ambiguous operation or roll it back independently of custody state.
- `MPC_CEREMONY_ENABLED`: exactly `false` (default) or `true`. Normal deployments
  must leave it false.

The Python `CoinbaseMpc2pcSigner` requires `MPC_SIGNER_URL=https://...`,
`MPC_CLIENT_CERT`, `MPC_CLIENT_KEY`, `MPC_CA_CERT`, and `MPC_APPROVAL_DIR`.
It refuses redirects, ambient proxy configuration, plaintext and missing mTLS
credentials. `HTTP_TIMEOUT_SEC` is finite, positive, at most 90 seconds, default 65.
Provision certificates with the actual service DNS SANs and correct client/server
usages. The local certificate-generation script is development-only and is never
run automatically.

## Exact transaction approvals

The client sends `POST /sign_transaction` with exactly two objects:

```json
{
  "transaction": {
    "type": 0, "chain_id": "1", "nonce": "9", "gas": "21000",
    "to": "0x3535353535353535353535353535353535353535",
    "value": "1000000000000000000", "data": "0x",
    "gas_price": "20000000000", "max_fee_per_gas": "0",
    "max_priority_fee_per_gas": "0"
  },
  "approval": {
    "id": "<64 lowercase hex characters, unique random approval id>",
    "expires_at": 0,
    "wallet": "<lowercase 0x-prefixed signer wallet>",
    "digest_hex": "<0x-prefixed exact transaction digest>",
    "signature_hex": "<128 lowercase hex characters>"
  }
}
```

All quantity strings are canonical unsigned decimal without leading zeros. Unused
fee fields are `"0"`. Addresses and data are lowercase 0x-prefixed hex; no access
list is accepted by the service. `type` is a JSON integer, not a string or boolean.

The independent operator signs these exact UTF-8 bytes with Ed25519, with newlines
between lines and **no trailing newline**:

```text
readytrader-mpc-approval-v1
<id>
<expires_at as decimal UNIX seconds>
<wallet>
<digest_hex>
```

The expiry must be in the next 300 seconds. Inspect the actual chain, wallet,
recipient/spender, amounts, nonce, calldata and maximum fees before issuance.
Approval signatures are portable between the two parties but single-use on each.
A proof is persisted and fsynced before peer orchestration or local crypto starts.
Invalid proofs do not consume valid ones. Failure, timeout or lost response after
consumption does not permit replay: reconcile externally before issuing a new id.

Save the proof only as `<digest without 0x>.json` in `MPC_APPROVAL_DIR`, or supply it
as `tx["mpc_approval"]` to the adapter. Missing/invalid proofs raise
`MPCApprovalRequired`, exposing the canonical **unsigned** transaction and digest
for independent review, without sending a signing request. Normal transfer tools
fetch nonce/fees at execution time; a retry with changed fields needs a new proof.
Do not automatically approve whatever the application prints, and do not install
an approval private key in the agent to remove this deliberate boundary.

`GET /address` and `/health` require the workload identity. Follower internal
control routes accept only the pinned leader identity and independently verify
exactly the same transaction policy and approval.

## Isolated, two-operator initialization ceremony

DKG is unavailable on the runtime listener. To initialize a new wallet:

1. Use a separate, isolated administration interface/network on both parties. Set
   `MPC_CEREMONY_ENABLED=true` only for the supervised ceremony, and set
   `MPC_BOOTSTRAP_LISTEN` to that interface (default `127.0.0.1:8788`). Do not bind it
   to a runtime/client-shared network. Configure the leader's
   `MPC_PEER_BOOTSTRAP_URL` as the follower's HTTPS administration origin.
2. Supply `MPC_OPERATOR_CERT` (the authorized operator's public mTLS certificate)
   and two **distinct** Ed25519 public keys in `MPC_CEREMONY_PUBLIC_KEY_1` and
   `MPC_CEREMONY_PUBLIC_KEY_2`. Both private keys remain with separate operators.
3. Both operators approve `POST /ceremony/start` on the leader. Proof fields are
   `id`, `ceremony_id`, `expires_at`, `public_key_hex`, `signatures`. At start,
   `id == ceremony_id` (unique 64-character lowercase hex) and public key is empty.
   `signatures` holds two 128-character hex signatures, in configured key order.
4. Shares are generated only in private staging directories, not active share
   paths. Query `GET /ceremony/status` on **both** parties with the operator mTLS
   identity. Independently verify they report the same uncompressed public key
   and wallet, and the intended ceremony id. No transaction can use staged shares.
5. Both operators issue a fresh commit proof with a **new approval id**, the same
   `ceremony_id`, and the exact agreed 130-character uncompressed public-key hex
   (`04...`, no `0x`). Send `POST /ceremony/commit` to the leader. Each party checks
   its staged identity before any active share is committed. An existing active
   share is never overwritten. Authorization and completion records are exclusive,
   fsynced files in the replay/audit directory, never edited by the service.
6. Verify the leader `/address` using the workload identity and both parties’
   completion audit records against the approved identity. Restart both with
   ceremony disabled and remove the administration network/configuration.
   Already initialized parties refuse another generation ceremony.

Each operator signs these bytes (UTF-8, no trailing newline), with `<stage>` equal
exactly to `start` or `commit`; expiry must again be within 300 seconds:

```text
readytrader-mpc-ceremony-v1
<stage>
<id>
<ceremony_id>
<expires_at>
<public_key_hex, empty at start>
```

Commit is not a distributed atomic filesystem transaction. A timeout may leave
only the follower committed. If both service processes retain the staged identity,
reconcile both states and obtain a **fresh dual-signed commit proof** for the same
ceremony/public key. An already committed party allows only that same identity;
the consumed proof itself cannot be retried. If a process restarted and lost staged
metadata, stop and use a separately reviewed offline custody recovery procedure.
Staging files are deliberately not auto-loaded, overwritten, or regenerated. Never
remove an initialized share or replay records as a troubleshooting shortcut.
The audit directory is append-only through this service, not tamper-proof against
a host administrator; protect/replicate it with the existing custody audit system.

## Resource and failure boundaries

- At most one MPC operation per party, shared across signing and ceremony routes.
  Excess work is rejected rather than queued; a follower cannot spawn unbounded
  crypto jobs.
- Request bodies: 64 KiB; headers: 16 KiB; 32 active connections and 32 handlers
  per listener/server budget. HTTP/2 multiplexing is disabled.
- Header/read/idle/write deadlines plus a 60-second end-to-end operation budget.
  Slow bodies time out and peer responses are bounded; redirects are refused.
- Native cb-mpc does not honor Go context cancellation. It runs in a dedicated
  child process, killed and reaped on deadline/cancellation **before** releasing
  its operation permit. Logs are discarded; protocol output uses a bounded private
  result file. A child-local deadline watchdog also terminates orphaned workers if the parent
  crashes.
- The compose runtime is read-only with private writable share volumes, bounded
  tmpfs, CPU/memory/PID limits, no new privileges and no capabilities.

## Verification and native-build prerequisite

`go test -race ./control` exercises the real authorization, canonical hashing,
policy, request/connection admission, HTTP deadlines, subprocess termination and
reaping, replay persistence, and staged-commit implementation. Native cryptography
is replaced only at the explicit backend boundary in control-route tests.
`pytest tests/test_mpc_security.py tests/test_remote_signer.py tests/test_signer_policy.py -q`
checks the Python adapter and existing signer contracts without a network signer.

The frozen repository's native dependency is incomplete: commit `3098afa` removed
`vendor/cb-mpc/src` and its build scripts. It is not a root Git submodule and cannot
be recovered with `git submodule update`. Historical source exists at integration
commit `2bbcb4861717b5ad37bc0b22e07f472f791b52ec`, but restoring and validating that
native supply chain is a separate prerequisite. A local historical-header check
passes Go/C binding compilation then fails linking the missing custom OpenSSL
`/usr/local/lib64/libcrypto.a` and `libcbmpc`. The patched native binary has not
been linked or exercised in a two-party deployment. Do not treat control-unit
success as production custody certification; retain live halt until reproducible
native builds and a funded-free two-party ceremony/signing validation are complete.
