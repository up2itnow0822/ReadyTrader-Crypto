## MPC Signer (Coinbase `cb-mpc`) — 2-Party ECDSA

This folder contains a **self-hosted**, open-source MPC signing service built on Coinbase’s `cb-mpc` (vendored under `vendor/cb-mpc`).

### What this provides

- **A single on-chain wallet address** (Ethereum-style) whose signing key is split across **two parties**.
- The ReadyTrader-Crypto agent never receives a private key; it can only request signatures through policy-guarded signers.

### How it integrates with ReadyTrader-Crypto

- Run the MPC services (party 0 + party 1).
- Run `sentinel/app.py` with:
  - `SIGNER_TYPE=cb_mpc_2pc`
  - `MPC_SIGNER_URL=http://<party-0-host>:8787`
  - `SENTINEL_AUTH_TOKEN=<a long, random token>` -- required. Every route on
    `sentinel/app.py`, including this MPC-backed one, fails closed (503) without it; see
    `sentinel/AGENTS.md`. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`.
- Run the trading agent with:
  - `SIGNER_TYPE=remote`
  - `SIGNER_REMOTE_URL=https://<sentinel-host>:8888` -- put sentinel behind TLS (uvicorn
    `--ssl-keyfile`/`--ssl-certfile`, or a TLS-terminating proxy). `RemoteSigner` refuses a
    non-https URL while `REMOTE_SIGNER_REQUIRE_TLS=true` (the default); set it to `false`
    only when sentinel and the agent share a private network.
  - `REMOTE_SIGNER_AUTH_TOKEN=<the same token as SENTINEL_AUTH_TOKEN above>`

### Running (high level)

You must provide:

- a CA cert (PEM)
- per-party TLS cert+key (PEM)
- each party’s expected cert file (PEM)
- party addresses for the MPC mTLS transport
- an HTTP control-plane address for each party

The binary reads these env vars:

- `MPC_ROLE_INDEX`: `0` (leader) or `1` (follower)
- `MPC_HTTP_LISTEN`: e.g. `0.0.0.0:8787`
- `MPC_PARTY0_ADDR`: e.g. `0.0.0.0:9787`
- `MPC_PARTY1_ADDR`: e.g. `mpc-party-0:9787` (from party 1) / `mpc-party-1:9787` (from party 0)
- `MPC_CA_CERT`: path to CA PEM
- `MPC_CERT`: path to this party’s cert PEM
- `MPC_KEY`: path to this party’s key PEM
- `MPC_PARTY0_CERT`: path to party0 cert PEM
- `MPC_PARTY1_CERT`: path to party1 cert PEM
- `MPC_PEER_HTTP_URL`: (leader only) base URL of follower control plane (e.g. `http://mpc-party-1:8787`)
- `MPC_KEYSHARE_PATH`: where this party stores its key share (default: `data/mpc_keyshare.bin`)

Leader endpoints:

- `POST /dkg`: run distributed key generation (first-time setup)
- `POST /sign_digest`: sign a 32-byte digest (hex)
- `GET /address`: return the derived EVM address once initialized

### Notes

- This is **real MPC** (no mocks). It requires both parties online to sign.
- Protect the party keyshare volumes as secrets.
- For production, run parties on separate hosts/VMs and restrict networking.
