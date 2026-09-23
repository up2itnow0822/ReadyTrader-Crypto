"""
Tests for sentinel/app.py's fail-closed Bearer-token auth (the P0 from issue #2).

sentinel/app.py exposes POST /sign_transaction and GET /address; every route must require
`Authorization: Bearer <token>` checked against SENTINEL_AUTH_TOKEN, and must fail closed
(503) when that token is unset or too short rather than falling through to "no auth".
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Skip tests if httpx not available (TestClient dependency), matching tests/test_api_server.py.
pytest.importorskip("httpx")

from fastapi import HTTPException
from fastapi.testclient import TestClient

import sentinel.app as sentinel_app

VALID_TOKEN = "a" * 32
OTHER_VALID_TOKEN = "b" * 32


class _FakeSigner:
    """Null/fake signer so these tests never touch a real key."""

    def get_address(self):
        return "0xFAKE0000000000000000000000000000000000"

    def sign_transaction(self, tx, *, chain_id=None):
        return SimpleNamespace(rawTransaction=b"\xde\xad\xbe\xef")


@pytest.fixture
def client():
    return TestClient(sentinel_app.app)


def test_token_unset_returns_503_and_does_not_reach_signer(client):
    with patch.dict(os.environ, {}, clear=True):
        with patch("sentinel.app.get_signer") as get_signer:
            resp = client.get("/address", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 503
    get_signer.assert_not_called()


def test_token_shorter_than_32_chars_returns_503(client):
    short = "short-token"
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": short}, clear=True):
        with patch("sentinel.app.get_signer") as get_signer:
            resp = client.get("/address", headers={"Authorization": f"Bearer {short}"})
    assert resp.status_code == 503
    get_signer.assert_not_called()
    # Fail closed even when the (too-short) token in the request matches exactly.


def test_missing_header_returns_401(client):
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with patch("sentinel.app.get_signer") as get_signer:
            resp = client.get("/address")
    assert resp.status_code == 401
    assert VALID_TOKEN not in resp.text
    get_signer.assert_not_called()


def test_wrong_token_returns_401_and_never_echoes_the_real_token(client):
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with patch("sentinel.app.get_signer") as get_signer:
            resp = client.get("/address", headers={"Authorization": f"Bearer {OTHER_VALID_TOKEN}"})
    assert resp.status_code == 401
    assert VALID_TOKEN not in resp.text
    get_signer.assert_not_called()


def test_correct_token_returns_200_for_address(client):
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with patch("sentinel.app.get_signer", return_value=_FakeSigner()):
            resp = client.get("/address", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"address": "0xFAKE0000000000000000000000000000000000"}


def test_correct_token_returns_200_for_sign_transaction(client):
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with patch("sentinel.app.get_signer", return_value=_FakeSigner()):
            resp = client.post(
                "/sign_transaction",
                json={"tx": {"to": "0x1", "value": 0}},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"rawTransactionHex": "0xdeadbeef"}


def test_sign_transaction_without_auth_returns_401_before_signing(client):
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with patch("sentinel.app.get_signer") as get_signer:
            resp = client.post("/sign_transaction", json={"tx": {"to": "0x1", "value": 0}})
    assert resp.status_code == 401
    get_signer.assert_not_called()


def test_docs_and_openapi_routes_are_disabled(client):
    # /docs, /redoc, /openapi.json are FastAPI's auto-generated routes. They are mounted as
    # plain Starlette routes (Starlette.add_route), not through APIRouter.add_api_route, so
    # a Depends()-based auth check on the real routes would not cover them -- they must be
    # disabled outright (docs_url=None etc. in sentinel/app.py) rather than gated, so this
    # holds regardless of SENTINEL_AUTH_TOKEN.
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 404


def test_non_ascii_authorization_header_is_rejected_as_401_not_500():
    # Starlette decodes request headers latin-1 off the wire, so a header byte >= 0x80
    # reaches us as a non-ASCII str codepoint. hmac.compare_digest(str, str) raises
    # TypeError for non-ASCII operands; _require_auth must not let that escape as an
    # unhandled 500 -- it must still fail closed with 401. Exercised directly against the
    # dependency function so this does not depend on httpx's own header-encoding behavior.
    with patch.dict(os.environ, {"SENTINEL_AUTH_TOKEN": VALID_TOKEN}, clear=True):
        with pytest.raises(HTTPException) as exc_info:
            sentinel_app._require_auth(authorization="Bearer " + ("é" * 40))
    assert exc_info.value.status_code == 401
