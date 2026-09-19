"""
Contract tests for GET /api/health (B1): the frontend dashboard needs to know
whether the API requires auth *before* it has a token, so /api/health must stay
unauthenticated and must expose `auth_required` alongside the existing fields.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytest.importorskip("httpx")

EXPECTED_HEALTH_KEYS = {
    "status",
    "mode",
    "timestamp",
    "version",
    "trading_halted",
    "live_enabled",
    "auth_required",
}


def _fresh_client():
    """Reload settings + api_server against the current os.environ, like test_api_server.py does."""
    import importlib

    import app.core.settings

    importlib.reload(app.core.settings)

    import api_server

    importlib.reload(api_server)

    from fastapi.testclient import TestClient

    return TestClient(api_server.app)


class TestHealthAuthRequiredField:
    def test_auth_required_false_when_api_auth_required_false(self):
        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "false",
                "DEV_MODE": "true",
            },
        ):
            client = _fresh_client()
            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["auth_required"] is False

    def test_auth_required_true_when_api_auth_required_true(self):
        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "test-secret-for-health-contract-32ch",
                "DEV_MODE": "true",
                "CORS_ORIGINS": "http://localhost:3000",
            },
        ):
            client = _fresh_client()
            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["auth_required"] is True

    def test_health_requires_no_authentication_even_when_auth_required(self):
        """The whole point of the field is that the dashboard can read it before login."""
        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "test-secret-for-health-contract-32ch",
                "DEV_MODE": "true",
                "CORS_ORIGINS": "http://localhost:3000",
            },
        ):
            client = _fresh_client()
            # No Authorization header at all.
            response = client.get("/api/health")

            assert response.status_code == 200

    def test_health_payload_has_no_new_leaked_fields(self):
        """Only the documented fields should be present -- no secrets, no extra internals."""
        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "test-secret-for-health-contract-32ch",
                "DEV_MODE": "true",
                "CORS_ORIGINS": "http://localhost:3000",
            },
        ):
            client = _fresh_client()
            response = client.get("/api/health")

            data = response.json()
            assert set(data.keys()) == EXPECTED_HEALTH_KEYS
