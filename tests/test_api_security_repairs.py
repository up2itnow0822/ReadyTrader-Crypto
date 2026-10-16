"""Security regressions for login work, WebSocket capabilities, and limiter storage."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bcrypt
import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from rate_limiter import FixedWindowRateLimiter, RateLimitError

ORIGIN = "https://dashboard.example"


@pytest.fixture
def api(monkeypatch):
    import api_server

    for name, value in {
        "API_AUTH_REQUIRED": True,
        "API_ADMIN_USERNAME": "admin",
        "API_ADMIN_PASSWORD_HASH": bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode(),
        "RATE_LIMIT_ENABLED": False,
        "CORS_ORIGINS": frozenset({ORIGIN}),
        "CORS_ALLOW_ALL": False,
        "DEV_MODE": False,
    }.items():
        monkeypatch.setattr(api_server.settings, name, value)
    monkeypatch.setattr(api_server, "JWT_SECRET", "test-security-repairs-secret-long-enough")
    if hasattr(api_server, "login_rate_limiter"):
        monkeypatch.setattr(api_server, "login_rate_limiter", FixedWindowRateLimiter())
    if hasattr(api_server, "websocket_tickets"):
        monkeypatch.setattr(api_server, "websocket_tickets", api_server.WebSocketTicketStore())
    return api_server


def auth_headers(api, origin=ORIGIN):
    token = api.create_access_token("admin", {"role": "admin"})
    return {"Authorization": f"Bearer {token}", "Origin": origin}


def mint_ticket(api, client, origin=ORIGIN):
    response = client.post("/api/auth/ws-ticket", headers=auth_headers(api, origin))
    assert response.status_code == 200, response.text
    assert 0 < response.json()["expires_in"] <= 30
    assert response.headers["cache-control"] == "no-store"
    return response.json()["ticket"]


def test_login_low_budget_cannot_be_bypassed_by_username_or_forwarded_ip(api):
    with TestClient(api.app) as client:
        responses = [
            client.post(
                "/api/auth/login",
                json={"username": f"user-{attempt}", "password": "wrong"},
                headers={"X-Forwarded-For": f"192.0.2.{attempt}", "Origin": ORIGIN},
            )
            for attempt in range(6)
        ]
    assert [response.status_code for response in responses] == [401] * 5 + [429]
    assert responses[-1].json()["ok"] is False
    assert responses[-1].headers["retry-after"] == "60"
    assert responses[-1].headers.get("access-control-allow-origin") in {ORIGIN, "*"}


def test_login_username_budget_survives_peer_and_case_changes(api):
    responses = []
    for attempt, username in enumerate(["ADMIN", "Admin", " admin", "admin ", "aDmIn", "admin"]):
        with TestClient(api.app, client=(f"192.0.2.{attempt}", 1234)) as client:
            responses.append(client.post("/api/auth/login", json={"username": username, "password": "wrong"}))
    assert [response.status_code for response in responses] == [401] * 5 + [429]


def test_login_aggregate_budget_survives_both_peer_and_username_rotation(api):
    responses = []
    for attempt in range(21):
        with TestClient(api.app, client=(f"192.0.2.{attempt}", 1234)) as client:
            responses.append(client.post("/api/auth/login", json={"username": f"user-{attempt}", "password": "wrong"}))
    assert [response.status_code for response in responses] == [401] * 20 + [429]


def test_login_ipv6_budget_groups_the_same_subnet(api):
    responses = []
    for attempt in range(6):
        with TestClient(api.app, client=(f"2001:db8::a{attempt}", 1234)) as client:
            responses.append(client.post("/api/auth/login", json={"username": f"user-{attempt}", "password": "wrong"}))
    assert [response.status_code for response in responses] == [401] * 5 + [429]


def test_login_lockout_expires_and_password_verification_can_resume(api, monkeypatch):
    now = [120.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    with TestClient(api.app) as client:
        for _ in range(5):
            assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"}).status_code == 429
        now[0] += 60
        assert client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"}).status_code == 200


@pytest.mark.asyncio
async def test_bcrypt_login_runs_outside_the_asgi_event_loop(api, monkeypatch):
    event_loop_thread = threading.get_ident()
    password_threads = []
    real_verify = api.verify_password

    def record_thread(password, hashed):
        password_threads.append(threading.get_ident())
        return real_verify(password, hashed)

    monkeypatch.setattr(api, "verify_password", record_thread)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        response = await client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert response.status_code == 200
    assert password_threads and event_loop_thread not in password_threads


def test_websocket_never_accepts_the_legacy_query_admin_jwt(api):
    token = api.create_access_token("admin", {"role": "admin"})
    with TestClient(api.app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(f"/ws?token={token}", headers={"Origin": ORIGIN}):
                pass
    assert rejected.value.code == 1008


def test_websocket_ticket_is_single_use_and_not_an_http_credential(api):
    with TestClient(api.app) as client:
        ticket = mint_ticket(api, client)
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ticket}"})
        assert response.status_code == 401
        protocols = ["readytrader", f"ticket.{ticket}"]
        with client.websocket_connect("/ws", headers={"Origin": ORIGIN}, subprotocols=protocols) as ws:
            assert ws.accepted_subprotocol == "readytrader"
            ws.send_text("ping")
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws", headers={"Origin": ORIGIN}, subprotocols=protocols):
                pass
        assert rejected.value.code == 1008


def test_websocket_ticket_mint_requires_authentication(api):
    with TestClient(api.app) as client:
        response = client.post("/api/auth/ws-ticket", headers={"Origin": ORIGIN})
    assert response.status_code == 401


def test_ticket_issuance_rejects_untrusted_origin(api):
    with TestClient(api.app) as client:
        response = client.post("/api/auth/ws-ticket", headers=auth_headers(api, "https://attacker.example"))
    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", None])
def test_browser_ticket_rejects_untrusted_or_missing_upgrade_origin(api, origin):
    with TestClient(api.app) as client:
        ticket = mint_ticket(api, client)
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws", headers={} if origin is None else {"Origin": origin}, subprotocols=["readytrader", f"ticket.{ticket}"]):
                pass
        assert rejected.value.code == 1008


def test_ticket_cannot_cross_between_two_allowed_origins(api, monkeypatch):
    second_origin = "https://other-dashboard.example"
    monkeypatch.setattr(api.settings, "CORS_ORIGINS", frozenset({ORIGIN, second_origin}))
    with TestClient(api.app) as client:
        ticket = mint_ticket(api, client)
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws", headers={"Origin": second_origin}, subprotocols=["readytrader", f"ticket.{ticket}"]):
                pass
        assert rejected.value.code == 1008


def test_non_browser_header_jwt_still_connects_without_query_credentials(api):
    token = api.create_access_token("admin", {"role": "admin"})
    with TestClient(api.app) as client:
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.send_text("ping")


def test_expired_websocket_ticket_is_rejected(api, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    with TestClient(api.app) as client:
        ticket = mint_ticket(api, client)
        now[0] += 31
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws", headers={"Origin": ORIGIN}, subprotocols=["readytrader", f"ticket.{ticket}"]):
                pass
        assert rejected.value.code == 1008


def test_websocket_ticket_consumption_is_atomic(api):
    with TestClient(api.app) as client:
        ticket = mint_ticket(api, client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda _: api.websocket_tickets.consume(ticket, origin=ORIGIN), range(32)))
    assert sum(accepted) == 1


def test_websocket_ticket_storage_is_bounded_and_reclaims_expired_entries(api, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    with TestClient(api.app) as client:
        responses = [client.post("/api/auth/ws-ticket", headers=auth_headers(api)) for _ in range(1025)]
        assert responses[0].status_code == 200
        assert responses[-1].status_code == 429
        now[0] += 31
        assert client.post("/api/auth/ws-ticket", headers=auth_headers(api)).status_code == 200


@pytest.mark.asyncio
async def test_login_bcrypt_concurrency_is_bounded_without_blocking_health(api, monkeypatch):
    entered = 0
    both_running = threading.Event()
    release = threading.Event()
    lock = threading.Lock()

    def blocked_verify(password, hashed):
        nonlocal entered
        with lock:
            entered += 1
            if entered == 2:
                both_running.set()
        assert release.wait(3), "bcrypt work blocked the event loop or never released"
        return False

    monkeypatch.setattr(api, "verify_password", blocked_verify)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        requests = [asyncio.create_task(client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})) for _ in range(2)]
        try:
            ready = await asyncio.to_thread(both_running.wait, 1)
            assert ready, "both password checks should enter worker threads"
            response = await asyncio.wait_for(client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}), 1)
            assert response.status_code == 429
            assert (await asyncio.wait_for(client.get("/api/health"), 1)).status_code == 200
        finally:
            release.set()
            await asyncio.gather(*requests)


def test_rate_limiter_reclaims_expired_keys(monkeypatch):
    import rate_limiter

    now = [120.0]
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: now[0])
    limiter = FixedWindowRateLimiter()
    for key in range(30):
        limiter.check(key=f"old-{key}", limit=1, window_seconds=60)
    now[0] += 60
    limiter.check(key="new", limit=1, window_seconds=60)
    assert len(limiter._state) == 1


def test_rate_limiter_bounds_cardinality_without_evicting_active_budgets():
    limiter = FixedWindowRateLimiter()
    limiter.check(key="protected", limit=1, window_seconds=60)
    for key in range(5000):
        try:
            limiter.check(key=f"attacker-{key}", limit=1, window_seconds=60)
        except RateLimitError:
            pass
    assert len(limiter._state) <= 4096
    with pytest.raises(RateLimitError):
        limiter.check(key="protected", limit=1, window_seconds=60)


def test_rate_limiter_refuses_oversized_keys_without_storing_them():
    limiter = FixedWindowRateLimiter()
    with pytest.raises(RateLimitError):
        limiter.check(key="x" * 10000, limit=1, window_seconds=60)
    assert not limiter._state


def test_rate_limiter_prunes_mixed_duration_windows_independently(monkeypatch):
    import rate_limiter

    now = [120.0]
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: now[0])
    limiter = FixedWindowRateLimiter()
    limiter.check(key="short", limit=1, window_seconds=1)
    limiter.check(key="long", limit=1, window_seconds=60)
    now[0] += 1
    limiter.check(key="short", limit=1, window_seconds=1)
    with pytest.raises(RateLimitError):
        limiter.check(key="long", limit=1, window_seconds=60)


def test_rate_limiter_recovers_capacity_after_expiry(monkeypatch):
    import rate_limiter

    now = [120.0]
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: now[0])
    limiter = FixedWindowRateLimiter(max_keys=2)
    limiter.check(key="first", limit=1, window_seconds=60)
    limiter.check(key="second", limit=1, window_seconds=60)
    with pytest.raises(RateLimitError):
        limiter.check(key="third", limit=1, window_seconds=60)
    now[0] += 60
    limiter.check(key="third", limit=1, window_seconds=60)
    assert len(limiter._state) == 1


def test_test_harness_resets_login_budget_between_journeys(tmp_path):
    source = """
import json, os, runpy, sys
from pathlib import Path
from fastapi.testclient import TestClient
os.environ.pop("API_ADMIN_PASSWORD_HASH", None)
harness = runpy.run_path("frontend/e2e/api_harness.py")
app = harness["create_app"](True, Path(sys.argv[1]))
with TestClient(app) as client:
    body = {"username": "admin", "password": "wrong"}
    attempts = [client.post("/api/auth/login", json=body).status_code for _ in range(6)]
    reset = client.post("/__test/reset-login-budget").status_code
    after = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password-123"}).status_code
print(json.dumps([attempts, reset, after]))
"""
    process = subprocess.run(
        [sys.executable, "-c", source, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "READYTRADER_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout.strip().splitlines()[-1]) == [[401] * 5 + [429], 200, 200]


def test_production_app_has_no_login_budget_reset_route(api):
    with TestClient(api.app) as client:
        assert client.post("/__test/reset-login-budget").status_code == 404
