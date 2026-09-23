from unittest.mock import MagicMock, patch

import pytest

from signing.remote_signer import RemoteSigner


def test_remote_signer_requires_url():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            RemoteSigner()


def test_remote_signer_get_address_and_sign():
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "http://signer"}):
        addr_resp = MagicMock()
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()
        sign_resp.json.return_value = {"rawTransactionHex": "0xdeadbeef"}
        sign_resp.raise_for_status.return_value = None
        sign_resp.headers = {"content-type": "application/json"}

        with patch("signing.remote_signer.requests.get", return_value=addr_resp):
            with patch("signing.remote_signer.requests.post", return_value=sign_resp) as post:
                s = RemoteSigner()
                assert s.get_address() == "0xabc"
                tx = {"to": "0x1", "value": 1}
                signed = s.sign_transaction(tx, chain_id=1)
                assert signed.rawTransaction == bytes.fromhex("deadbeef")
                post.assert_called()
                args, kwargs = post.call_args
                payload = kwargs.get("json") or {}
                assert payload.get("chain_id") == 1
                assert "intent" in payload


def test_remote_signer_sends_bearer_header_when_auth_token_configured():
    """Both /address and /sign_transaction carry the header the sentinel reference signer
    requires when REMOTE_SIGNER_AUTH_TOKEN is set."""
    env = {"SIGNER_REMOTE_URL": "http://signer", "REMOTE_SIGNER_AUTH_TOKEN": "tok-abc-123"}
    with patch.dict("os.environ", env, clear=True):
        addr_resp = MagicMock()
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()
        sign_resp.json.return_value = {"rawTransactionHex": "0xdeadbeef"}
        sign_resp.raise_for_status.return_value = None
        sign_resp.headers = {"content-type": "application/json"}

        with patch("signing.remote_signer.requests.get", return_value=addr_resp) as get_mock:
            with patch("signing.remote_signer.requests.post", return_value=sign_resp) as post_mock:
                s = RemoteSigner()
                s.get_address()
                s.sign_transaction({"to": "0x1", "value": 1}, chain_id=1)

        assert get_mock.call_args.kwargs.get("headers") == {"Authorization": "Bearer tok-abc-123"}
        assert post_mock.call_args.kwargs.get("headers") == {"Authorization": "Bearer tok-abc-123"}


def test_remote_signer_omits_bearer_header_when_auth_token_unset():
    """Third-party remote signers that don't expect this header keep working unchanged."""
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "http://signer"}, clear=True):
        addr_resp = MagicMock()
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()
        sign_resp.json.return_value = {"rawTransactionHex": "0xdeadbeef"}
        sign_resp.raise_for_status.return_value = None
        sign_resp.headers = {"content-type": "application/json"}

        with patch("signing.remote_signer.requests.get", return_value=addr_resp) as get_mock:
            with patch("signing.remote_signer.requests.post", return_value=sign_resp) as post_mock:
                s = RemoteSigner()
                s.get_address()
                s.sign_transaction({"to": "0x1", "value": 1}, chain_id=1)

        assert get_mock.call_args.kwargs.get("headers") == {}
        assert post_mock.call_args.kwargs.get("headers") == {}
