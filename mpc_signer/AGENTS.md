# mpc_signer/

## Purpose

Optional two-party EVM custody service, including the authenticated runtime control plane, isolated initialization ceremony and bounded native workers.

## Ownership

- `control/`: independently testable Go authorization, canonical transaction decoding, replay/audit persistence, TLS HTTP boundaries and child-process lifecycle.
- `main.go`: operator configuration and cb-mpc native-worker bridge.
- `README.md`: operator migration, exact approval/ceremony protocols and native-build limitations.

## Local Contracts

- No public raw digest signing route. Both parties recompute the transaction digest, enforce mandatory semantic/fee policy and verify the independent single-use Ed25519 approval.
- Every control route requires verified, pinned TLS client identity. The approval private key is never held by the application or signer services.
- Runtime routes never generate keys. Bootstrap is disabled by default, isolated, and requires two distinct operator approvals; stage first, confirm identical public identity, then commit without overwriting an existing share.
- Replay records are durable before effects. Never clear them or silently retry an ambiguous signing/commit outcome. Preserve partial-commit recovery guidance.
- One cryptographic operation at a time per party. Native workers must be killed and reaped before releasing admission permits; a handler timeout alone is insufficient.
- Preserve only explicitly decoded transaction semantics; reject unknown calldata and envelope fields.
- The checked-in cb-mpc native source/build inputs are incomplete. Unit-control success is not evidence of native build, ceremony or signing success.

## Work Guidance

- Never generate/configure real custody identities or run live signing in unit tests.
- Use transient test keys and subprocess fixtures only. Keep native dependencies and key shares out of fixtures and source control.
- Keep protocol changes synchronized with `signing/cb_mpc_2pc.py` and its Python tests.

## Verification

- `go test -race ./control` within this directory.
- `pytest tests/test_mpc_security.py tests/test_remote_signer.py tests/test_signer_policy.py -q` from the root.
- Native build and isolated two-party acceptance require a separately restored, verified cb-mpc supply chain; report blockers explicitly.

## Child DOX Index

None. `control/` remains owned here.
