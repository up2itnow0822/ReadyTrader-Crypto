"""
Tests for the API server with rate limiting and authentication.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Skip tests if httpx not available
pytest.importorskip("httpx")


@pytest.fixture
def api_client():
    """Create a test client for the API server."""
    from fastapi.testclient import TestClient

    # Set up test environment
    with patch.dict(
        os.environ,
        {
            "PAPER_MODE": "true",
            "SIGNER_TYPE": "null",
            "RATE_LIMIT_ENABLED": "false",  # Disable for most tests
            "API_AUTH_REQUIRED": "false",  # Disable for most tests
            "DEV_MODE": "true",  # Allow test configuration
        },
    ):
        # Need to reimport to pick up env changes
        import importlib

        # Reload settings first to pick up new env vars
        import app.core.settings

        importlib.reload(app.core.settings)

        import api_server

        importlib.reload(api_server)

        yield TestClient(api_server.app)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_returns_ok(self, api_client):
        """Test health endpoint returns OK."""
        response = api_client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mode"] == "paper"
        assert "version" in data


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limit_allows_under_limit(self):
        """Test requests under limit are allowed."""
        from fastapi.testclient import TestClient

        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "true",
                "RATE_LIMIT_REQUESTS_PER_MIN": "100",
                "API_AUTH_REQUIRED": "false",
            },
        ):
            import importlib

            import api_server

            importlib.reload(api_server)

            client = TestClient(api_server.app)

            # Make a few requests
            for _ in range(5):
                response = client.get("/api/health")
                assert response.status_code == 200


class TestAuthentication:
    """Test authentication functionality."""

    def test_login_with_valid_credentials(self):
        """Test login with valid credentials."""
        from fastapi.testclient import TestClient

        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_ADMIN_USERNAME": "admin",
                "API_ADMIN_PASSWORD": "secret123",
                "DEV_MODE": "true",  # Allow plaintext password
            },
        ):
            import importlib

            # Reload settings first
            import app.core.settings

            importlib.reload(app.core.settings)

            import api_server

            importlib.reload(api_server)

            client = TestClient(api_server.app)

            response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "secret123",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"

    def test_login_with_invalid_credentials(self):
        """Test login with invalid credentials."""
        from fastapi.testclient import TestClient

        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_ADMIN_USERNAME": "admin",
                "API_ADMIN_PASSWORD": "secret123",
                "DEV_MODE": "true",  # Allow plaintext password
            },
        ):
            import importlib

            # Reload settings first
            import app.core.settings

            importlib.reload(app.core.settings)

            import api_server

            importlib.reload(api_server)

            client = TestClient(api_server.app)

            response = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "wrongpassword",
                },
            )

            assert response.status_code == 401

    def test_protected_endpoint_requires_auth_when_enabled(self):
        """Test protected endpoint requires auth when enabled."""
        from fastapi.testclient import TestClient

        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "DEV_MODE": "true",  # Allow running without JWT secret
            },
        ):
            import importlib

            # Need to reload settings module first, then api_server
            import app.core.settings

            importlib.reload(app.core.settings)

            import api_server

            importlib.reload(api_server)

            client = TestClient(api_server.app)

            response = client.get("/api/portfolio")

            assert response.status_code == 401


class TestPortfolioEndpoint:
    """Test portfolio endpoint."""

    def test_portfolio_paper_mode(self, api_client):
        """Test portfolio endpoint in paper mode."""
        response = api_client.get("/api/portfolio")

        assert response.status_code == 200
        data = response.json()
        assert "balances" in data
        assert "metrics" in data


class TestPendingApprovalsEndpoint:
    """Test pending approvals endpoint."""

    def test_list_pending_approvals(self, api_client):
        """Test listing pending approvals."""
        response = api_client.get("/api/pending-approvals")

        assert response.status_code == 200
        data = response.json()
        assert "pending" in data


class TestMetricsEndpoint:
    """Test metrics endpoint."""

    def test_get_metrics(self, api_client):
        """Test getting metrics."""
        response = api_client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert "uptime_sec" in data
        assert "counters" in data
        assert "timers" in data
        assert "gauges" in data


class TestStrategiesEndpoint:
    """Test strategies endpoint."""

    def test_list_strategies(self, api_client):
        """Test listing strategies."""
        response = api_client.get("/api/strategies")

        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data


class TestInsightsEndpoint:
    """Test insights endpoint."""

    def test_list_insights(self, api_client):
        """Test listing insights."""
        response = api_client.get("/api/insights")

        assert response.status_code == 200
        data = response.json()
        assert "insights" in data


class TestTradeHistoryEndpoint:
    """Test trade history endpoint."""

    def test_get_trade_history(self, api_client):
        """Test getting trade history."""
        response = api_client.get("/api/trades/history")

        assert response.status_code == 200
        data = response.json()
        assert "trades" in data
        assert "mode" in data


class TestWebSocketAuth:
    """WebSocket /ws must require JWT when API_AUTH_REQUIRED=true (SEC-001)."""

    def test_ws_rejects_without_token_when_auth_required(self):
        from fastapi.testclient import TestClient

        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": "test-secret-for-ws-auth-32chars!!",
                "DEV_MODE": "true",
                "CORS_ORIGINS": "http://localhost:3000",
            },
        ):
            import importlib

            import app.core.settings

            importlib.reload(app.core.settings)
            import api_server

            importlib.reload(api_server)

            client = TestClient(api_server.app)
            with pytest.raises(Exception):
                # Starlette TestClient raises on rejected WS close before accept
                with client.websocket_connect("/ws"):
                    pass

    def test_ws_accepts_with_query_token_when_auth_required(self):
        from datetime import datetime, timedelta, timezone

        from fastapi.testclient import TestClient

        secret = "test-secret-for-ws-auth-32chars!!"
        with patch.dict(
            os.environ,
            {
                "PAPER_MODE": "true",
                "SIGNER_TYPE": "null",
                "RATE_LIMIT_ENABLED": "false",
                "API_AUTH_REQUIRED": "true",
                "API_JWT_SECRET": secret,
                "DEV_MODE": "true",
                "CORS_ORIGINS": "http://localhost:3000",
            },
        ):
            import importlib

            import jwt as pyjwt

            import app.core.settings

            importlib.reload(app.core.settings)
            import api_server

            importlib.reload(api_server)

            now = datetime.now(timezone.utc)
            token = pyjwt.encode(
                {
                    "sub": "admin",
                    "role": "admin",
                    "iat": now,
                    "exp": now + timedelta(hours=1),
                },
                secret,
                algorithm="HS256",
            )
            client = TestClient(api_server.app)
            with client.websocket_connect(f"/ws?token={token}") as ws:
                ws.send_text("ping")
