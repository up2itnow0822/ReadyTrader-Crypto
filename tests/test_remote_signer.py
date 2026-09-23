from unittest.mock import MagicMock, patch

import pytest

from signing.remote_signer import RemoteSigner


def test_remote_signer_requires_url():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            RemoteSigner()


def test_remote_signer_get_address_and_sign():
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "https://signer"}):
        addr_resp = MagicMock()
        addr_resp.status_code = 200
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()

        sign_resp.status_code = 200
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
    env = {"SIGNER_REMOTE_URL": "https://signer", "REMOTE_SIGNER_AUTH_TOKEN": "tok-abc-123"}
    with patch.dict("os.environ", env, clear=True):
        addr_resp = MagicMock()
        addr_resp.status_code = 200
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()

        sign_resp.status_code = 200
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
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "https://signer"}, clear=True):
        addr_resp = MagicMock()
        addr_resp.status_code = 200
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}

        sign_resp = MagicMock()

        sign_resp.status_code = 200
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


def test_remote_signer_refuses_plaintext_http_by_default():
    """REMOTE_SIGNER_REQUIRE_TLS defaults to true, so an http:// signer URL is refused up front."""
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "http://signer"}, clear=True):
        with pytest.raises(ValueError, match="https://"):
            RemoteSigner()


def test_remote_signer_never_sends_token_over_http_when_tls_required():
    """Even with a bearer token configured, nothing is sent: construction fails first."""
    env = {"SIGNER_REMOTE_URL": "http://sentinel-host:8888", "REMOTE_SIGNER_AUTH_TOKEN": "tok-abc-123", "REMOTE_SIGNER_REQUIRE_TLS": "true"}
    with patch.dict("os.environ", env, clear=True):
        with patch("signing.remote_signer.requests.get") as get_mock, patch("signing.remote_signer.requests.post") as post_mock:
            with pytest.raises(ValueError, match="REMOTE_SIGNER_REQUIRE_TLS"):
                RemoteSigner()
        get_mock.assert_not_called()
        post_mock.assert_not_called()


@pytest.mark.parametrize("flag", ["false", "0", "no", "off"])
def test_remote_signer_allows_http_only_with_explicit_tls_opt_out(flag):
    """The private-network dev path (compose sentinel) must opt out explicitly."""
    env = {"SIGNER_REMOTE_URL": "http://sentinel:8888", "REMOTE_SIGNER_AUTH_TOKEN": "tok-abc-123", "REMOTE_SIGNER_REQUIRE_TLS": flag}
    with patch.dict("os.environ", env, clear=True):
        addr_resp = MagicMock()
        addr_resp.status_code = 200
        addr_resp.json.return_value = {"address": "0xabc"}
        addr_resp.raise_for_status.return_value = None
        addr_resp.headers = {"content-type": "application/json"}
        with patch("signing.remote_signer.requests.get", return_value=addr_resp) as get_mock:
            assert RemoteSigner().get_address() == "0xabc"
        assert get_mock.call_args.kwargs.get("headers") == {"Authorization": "Bearer tok-abc-123"}


@pytest.mark.parametrize("flag", ["treu", "maybe", "enabled", "yes please"])
def test_remote_signer_unrecognised_tls_flag_fails_closed(flag):
    """A typo in REMOTE_SIGNER_REQUIRE_TLS must keep TLS required, never fall open."""
    env = {"SIGNER_REMOTE_URL": "http://signer", "REMOTE_SIGNER_REQUIRE_TLS": flag}
    with patch.dict("os.environ", env, clear=True):
        with pytest.raises(ValueError, match="https://"):
            RemoteSigner()


def test_settings_tls_flag_uses_the_same_fail_closed_rule():
    from app.core.settings import Settings

    for flag, expected in (("", True), ("true", True), ("treu", True), ("FALSE", False), ("off", False)):
        with patch.dict("os.environ", {"REMOTE_SIGNER_REQUIRE_TLS": flag}):
            assert Settings().REMOTE_SIGNER_REQUIRE_TLS is expected, flag


def test_remote_signer_refuses_redirects_without_following_them():
    """Both requests go out with allow_redirects=False, and a 3xx is refused, not followed."""
    redirect = MagicMock()
    redirect.status_code = 307
    redirect.headers = {"location": "http://attacker.example/sign_transaction"}
    with patch.dict("os.environ", {"SIGNER_REMOTE_URL": "https://signer"}, clear=True):
        with patch("signing.remote_signer.requests.post", return_value=redirect) as post_mock:
            with pytest.raises(ValueError, match="redirect"):
                RemoteSigner().sign_transaction({"to": "0x1", "value": 1}, chain_id=1)
        with patch("signing.remote_signer.requests.get", return_value=redirect) as get_mock:
            with pytest.raises(ValueError, match="redirect"):
                RemoteSigner().get_address()
    assert post_mock.call_args.kwargs.get("allow_redirects") is False
    assert get_mock.call_args.kwargs.get("allow_redirects") is False


def test_remote_signer_does_not_resend_payload_on_307_real_http():
    """Unmocked: a real signer answering 307 must not receive the transaction a second time.

    Before allow_redirects=False, requests followed the 307 to /leak, resent the JSON body
    there, and returned that response's signed transaction as if it came from the signer.
    """
    import http.server
    import threading

    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("content-length") or 0)
            hits.append((self.path, self.rfile.read(length)))
            if self.path == "/sign_transaction":
                self.send_response(307)
                self.send_header("Location", "/leak")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b'{"rawTransactionHex": "0xdeadbeef"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            "SIGNER_REMOTE_URL": f"http://127.0.0.1:{server.server_port}",
            "REMOTE_SIGNER_REQUIRE_TLS": "false",
        }
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="redirect"):
                RemoteSigner().sign_transaction({"to": "0x1", "value": 1}, chain_id=1)
    finally:
        server.shutdown()
        server.server_close()
    assert [path for path, _ in hits] == ["/sign_transaction"]
