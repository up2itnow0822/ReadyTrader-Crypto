"""MPC adapter security regressions; never contacts a signer or a chain."""

import json

import pytest

from signing.cb_mpc_2pc import CoinbaseMpc2pcSigner


@pytest.fixture
def mpc_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MPC_SIGNER_URL", "https://signer.invalid:8787")
    monkeypatch.setenv("MPC_CLIENT_CERT", str(tmp_path / "client.crt"))
    monkeypatch.setenv("MPC_CLIENT_KEY", str(tmp_path / "client.key"))
    monkeypatch.setenv("MPC_CA_CERT", str(tmp_path / "ca.crt"))
    monkeypatch.setenv("MPC_APPROVAL_DIR", str(tmp_path))
    return tmp_path


def test_mpc_rejects_plaintext_control_plane(monkeypatch):
    """A caller must not send approval/signing authority over plaintext HTTP."""
    monkeypatch.setenv("MPC_SIGNER_URL", "http://signer.invalid:8787")
    with pytest.raises(ValueError, match="https"):
        CoinbaseMpc2pcSigner()


def test_mpc_requires_workload_identity(monkeypatch):
    monkeypatch.setenv("MPC_SIGNER_URL", "https://signer.invalid:8787")
    for name in ("MPC_CLIENT_CERT", "MPC_CLIENT_KEY", "MPC_CA_CERT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="MPC_CLIENT_CERT"):
        CoinbaseMpc2pcSigner()


def test_mpc_requires_exact_digest_approval_before_network(mpc_env, monkeypatch):
    signer = CoinbaseMpc2pcSigner()

    def no_network(*args, **kwargs):
        pytest.fail("Unapproved transaction reached the network")

    monkeypatch.setattr("requests.sessions.Session.send", no_network)
    with pytest.raises(ValueError, match="approval"):
        signer.sign_transaction({"chainId": 1, "nonce": 0, "gasPrice": 1, "gas": 21000, "to": "0x" + "11" * 20, "value": 1})


@pytest.mark.parametrize(
    "change",
    [
        {"chainId": 2},
        {"accessList": [["0x" + "22" * 20, []]]},
        {"type": True},
        {"nonce": -1},
        {"data": "0x123"},
        {"gas": 0},
        {"to": None},
        {"unknown": 1},
    ],
)
def test_mpc_rejects_noncanonical_or_unsupported_transaction(mpc_env, monkeypatch, change):
    signer = CoinbaseMpc2pcSigner()
    tx = {"chainId": 1, "nonce": 0, "gasPrice": 1, "gas": 21000, "to": "0x" + "11" * 20, "value": 1}
    tx.update(change)

    def no_network(*args, **kwargs):
        pytest.fail("Invalid transaction reached the network")

    monkeypatch.setattr("requests.sessions.Session.send", no_network)
    with pytest.raises(ValueError):
        signer.sign_transaction(tx, chain_id=1)


def test_mpc_approval_file_is_bounded(mpc_env, monkeypatch):
    # EIP-155 worked example, from the EIP, also cross-checks the Go digest fixture.
    digest = "daf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
    (mpc_env / (digest + ".json")).write_text(" " * (65536 + 1))
    signer = CoinbaseMpc2pcSigner()

    def no_network(*args, **kwargs):
        pytest.fail("Oversized approval reached the network")

    monkeypatch.setattr("requests.sessions.Session.send", no_network)
    with pytest.raises(ValueError, match="approval"):
        signer.sign_transaction(
            {"chainId": 1, "nonce": 9, "gasPrice": 20000000000, "gas": 21000, "to": "0x" + "35" * 20, "value": 1000000000000000000, "data": "0x"}
        )


def test_mpc_transmits_canonical_intent_and_approval_with_mtls(mpc_env, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from eth_keys import keys
    from eth_utils import keccak
    from requests import Response

    key = keys.PrivateKey(bytes.fromhex("46" * 32))
    digest = "daf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
    approval = {
        "id": "ab" * 32,
        "expires_at": 2000000000,
        "wallet": key.public_key.to_checksum_address().lower(),
        "digest_hex": "0x" + digest,
        "signature_hex": "cd" * 64,
    }
    (mpc_env / (digest + ".json")).write_text(json.dumps(approval))
    observed = []

    def serve(self, request, **kwargs):
        observed.append((request, kwargs))
        response = Response()
        response.status_code = 200
        if request.url.endswith("/address"):
            response._content = json.dumps({"address": approval["wallet"]}).encode()
        else:
            signed = key.sign_msg_hash(bytes.fromhex(digest))
            response._content = json.dumps({"ok": True, "signature_der_hex": "0x" + encode_dss_signature(signed.r, signed.s).hex()}).encode()
        return response

    monkeypatch.setattr("requests.sessions.Session.send", serve)
    signer = CoinbaseMpc2pcSigner()
    result = signer.sign_transaction(
        {"chainId": 1, "nonce": 9, "gasPrice": 20000000000, "gas": 21000, "to": "0x" + "35" * 20, "value": 1000000000000000000, "data": "0x"}
    )
    # Independent EIP-155 fixture validates signed transaction assembly.
    assert keccak(result.rawTransaction).hex() == "33469b22e9f636356c4160a87eb19df52b7412e8eac32a4a55ffe88ea8350788"
    post, options = next((r, opts) for r, opts in observed if r.method == "POST")
    assert post.url == "https://signer.invalid:8787/sign_transaction"
    body = json.loads(post.body)
    assert body["approval"] == approval
    assert body["transaction"] == {
        "type": 0,
        "chain_id": "1",
        "nonce": "9",
        "gas": "21000",
        "to": "0x" + "35" * 20,
        "value": "1000000000000000000",
        "data": "0x",
        "gas_price": "20000000000",
        "max_fee_per_gas": "0",
        "max_priority_fee_per_gas": "0",
    }
    assert options["cert"] == (str(mpc_env / "client.crt"), str(mpc_env / "client.key"))
    assert options["verify"] == str(mpc_env / "ca.crt")
    assert options["allow_redirects"] is False


def test_missing_approval_reports_exact_unsigned_intent_for_operator(mpc_env):
    signer = CoinbaseMpc2pcSigner()
    with pytest.raises(ValueError) as caught:
        signer.sign_transaction(
            {"chainId": 1, "nonce": 9, "gasPrice": 20000000000, "gas": 21000, "to": "0x" + "35" * 20, "value": 1000000000000000000, "data": "0x"}
        )
    assert getattr(caught.value, "digest_hex", None) == "0xdaf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
    assert getattr(caught.value, "transaction", {}).get("nonce") == "9"


def test_type2_matches_independent_eth_account_golden_transaction(mpc_env, monkeypatch):
    """Golden values independently derived with eth-account TypedTransaction/Account.

    Catches fee ordering, omitted 0x02 domain separation, digest/envelope drift,
    parity and signed RLP assembly defects without executing a native signature.
    """
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from eth_utils import keccak
    from requests import Response

    digest = "577f072b4be21dbe73cdd90f32675d67d2fdfefdecfbc579f52025caf096400a"
    address = "0x9d8a62f656a8d1615c1294fd71e9cfb3e4855a4f"
    proof = {"id": "ab" * 32, "expires_at": 2000000000, "wallet": address, "digest_hex": "0x" + digest, "signature_hex": "cd" * 64}
    (mpc_env / (digest + ".json")).write_text(json.dumps(proof))
    observed = []

    def serve(self, request, **kwargs):
        response = Response()
        response.status_code = 200
        if request.method == "GET":
            payload = {"address": address}
        else:
            observed.append(json.loads(request.body))
            payload = {
                "ok": True,
                "signature_der_hex": "0x"
                + encode_dss_signature(
                    35520354145343619523594023241878581587327031125497181026949872498250322979472,
                    15985376843586106142193028908041788455375653768377442367663754371184615907037,
                ).hex(),
            }
        response._content = json.dumps(payload).encode()
        return response

    monkeypatch.setattr("requests.sessions.Session.send", serve)
    result = CoinbaseMpc2pcSigner().sign_transaction(
        {
            "type": 2,
            "chainId": 1,
            "nonce": 9,
            "gas": 21000,
            "maxPriorityFeePerGas": 1000000000,
            "maxFeePerGas": 20000000000,
            "to": "0x" + "35" * 20,
            "value": 1000000000000000000,
            "data": "0x",
            "accessList": [],
        }
    )
    assert result.rawTransaction.hex() == (
        "02f8730109843b9aca008504a817c800825208943535353535353535353535353535353535353535"
        "880de0b6b3a764000080c080a04e87ced8b47d801c979c6baa52bbd78b42c9db2515c9d1f473e06f65d49aaa90"
        "a02357671517c59544ebd95012d1988c102292eb570cc840ac9af72bb4c52e5edd"
    )
    assert keccak(result.rawTransaction).hex() == "85c29adc6584224bbd5a304d2e7a3a2f26ca67e4e4dd69e64cc0c71a028a12a3"
    assert observed == [
        {
            "approval": proof,
            "transaction": {
                "type": 2,
                "chain_id": "1",
                "nonce": "9",
                "gas": "21000",
                "to": "0x" + "35" * 20,
                "value": "1000000000000000000",
                "data": "0x",
                "gas_price": "0",
                "max_fee_per_gas": "20000000000",
                "max_priority_fee_per_gas": "1000000000",
            },
        }
    ]
