"""
Approval gate over HTTP: who may approve, what an approver sees, and that a proposal executes once.

`POST /api/approve-trade` executes a (possibly live) order and previously had no test at all; any
failure inside it surfaced as a bare 500. Most tests here count invocations of the execution
function (the property under test is "exactly once / never"); one test runs the real paper engine
end to end so the path is not only exercised against a stub.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("httpx")

ORDER = {"symbol": "BTC/USDT", "side": "buy", "amount": 0.01, "order_type": "limit", "price": 50000.0, "exchange": "binance", "market_type": "spot"}
# What a proposal made in paper mode records (app.tools.execution._maybe_propose adds paper_mode).
PROPOSED = {**ORDER, "paper_mode": True}


def _boot(tmp_path, monkeypatch, *, auth: bool):
    from fastapi.testclient import TestClient

    env = {
        "PAPER_MODE": "true",
        "SIGNER_TYPE": "null",
        "RATE_LIMIT_ENABLED": "false",
        "DEV_MODE": "true",
        "API_AUTH_REQUIRED": "true" if auth else "false",
        "EXECUTION_MODE": "cex",  # tests/conftest.py pins "dex" for the whole session
        "API_JWT_SECRET": "unit-test-secret-not-a-real-one",
        "API_ADMIN_USERNAME": "admin",
        "API_ADMIN_PASSWORD": "pw-for-tests",
        "READYTRADER_EXECUTION_DB_PATH": str(tmp_path / "execution.db"),
    }
    ctx = patch.dict(os.environ, env)
    ctx.start()
    import app.core.settings

    importlib.reload(app.core.settings)
    import api_server

    importlib.reload(api_server)
    from execution_store import ExecutionStore

    store = ExecutionStore()
    monkeypatch.setattr(api_server.global_container, "execution_store", store)
    calls: list[dict] = []

    def fake_place_cex_order(**kwargs):
        calls.append(kwargs)
        return json.dumps({"ok": True, "data": {"venue": "cex", "mode": "paper", "stub": True}})

    monkeypatch.setattr(api_server, "place_cex_order", fake_place_cex_order)
    return SimpleNamespace(client=TestClient(api_server.app), mod=api_server, store=store, calls=calls, stop=ctx.stop)


@pytest.fixture
def open_api(tmp_path, monkeypatch):
    """Auth off, paper mode: the local-development profile."""
    api = _boot(tmp_path, monkeypatch, auth=False)
    yield api
    api.stop()


@pytest.fixture
def secured_api(tmp_path, monkeypatch):
    """Auth on: every call needs a JWT; token-less approval needs the admin role."""
    api = _boot(tmp_path, monkeypatch, auth=True)
    login = api.client.post("/api/auth/login", json={"username": "admin", "password": "pw-for-tests"})
    assert login.status_code == 200, login.text
    api.admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    api.user = {"Authorization": f"Bearer {api.mod.create_access_token('bob', {'role': 'user'})}"}
    yield api
    api.stop()


def _approve(api, request_id, *, token=None, approve=True, headers=None):
    body = {"request_id": request_id, "approve": approve}
    if token is not None:
        body["confirm_token"] = token
    return api.client.post("/api/approve-trade", json=body, headers=headers or {})


# --------------------------------------------------------------------------- what the approver sees


def test_pending_list_shows_the_trade_and_never_the_token(open_api):
    prop = open_api.store.create(kind="place_cex_order", payload={**ORDER, "idempotency_key": "k1", "api_secret": "MUST-NOT-APPEAR"})
    res = open_api.client.get("/api/pending-approvals")
    assert res.status_code == 200
    (item,) = res.json()["pending"]
    assert item["summary"] == {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in ORDER.items()}
    assert prop.confirm_token not in res.text, "the confirm token must never reach the dashboard"
    assert "MUST-NOT-APPEAR" not in res.text and "idempotency_key" not in res.text, "summary is a whitelist"


def test_summary_is_empty_for_an_unreviewed_kind_and_truncates_long_text(open_api):
    open_api.store.create(kind="future_kind", payload={"anything": "hidden"})
    open_api.store.create(kind="swap_tokens", payload={"from_token": "USDC", "to_token": "ETH", "amount": 5, "chain": "base", "rationale": "x" * 5000})
    by_kind = {i["kind"]: i["summary"] for i in open_api.client.get("/api/pending-approvals").json()["pending"]}
    assert by_kind["future_kind"] == {}
    assert len(by_kind["swap_tokens"]["rationale"]) == 280 and by_kind["swap_tokens"]["amount"] == 5.0


def test_html_in_a_rationale_round_trips_as_inert_text(open_api):
    open_api.store.create(kind="swap_tokens", payload={"from_token": "USDC", "to_token": "ETH", "amount": 1, "rationale": "<img src=x onerror=alert(1)>"})
    res = open_api.client.get("/api/pending-approvals")
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["pending"][0]["summary"]["rationale"] == "<img src=x onerror=alert(1)>"


# --------------------------------------------------------------------------- approving


def test_operator_approves_without_a_token_in_paper_mode_and_it_executes_once(open_api):
    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    first = _approve(open_api, prop.request_id)
    assert first.status_code == 200 and first.json()["ok"] is True, first.text
    assert len(open_api.calls) == 1
    assert open_api.calls[0]["symbol"] == "BTC/USDT" and open_api.calls[0]["amount"] == 0.01 and open_api.calls[0]["price"] == 50000.0
    assert open_api.calls[0]["idempotency_key"] == prop.request_id, "falls back to the request id so a retry cannot double-fill"

    again = _approve(open_api, prop.request_id)
    assert again.status_code == 409 and again.json()["error"]["code"] == "EXEC_308", again.text
    assert len(open_api.calls) == 1, "a second click must not execute again"
    assert open_api.client.get("/api/pending-approvals").json()["pending"] == []


def test_the_confirm_token_path_still_works(open_api):
    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(open_api, prop.request_id, token=prop.confirm_token)
    assert res.status_code == 200 and len(open_api.calls) == 1


def test_wrong_token_is_403_executes_nothing_and_leaves_the_proposal_pending(open_api):
    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(open_api, prop.request_id, token="0" * 32)
    assert res.status_code == 403 and res.json()["error"]["code"] == "AUTH_604", res.text
    assert open_api.calls == []
    assert len(open_api.client.get("/api/pending-approvals").json()["pending"]) == 1
    assert _approve(open_api, prop.request_id, token=prop.confirm_token).status_code == 200


@pytest.mark.parametrize(
    "setup,status,code",
    [
        ("unknown", 404, "EXEC_309"),
        ("expired", 410, "EXEC_310"),
        ("cancelled", 409, "EXEC_311"),
    ],
)
def test_bad_proposal_states_are_4xx_with_a_code_never_500(open_api, setup, status, code):
    if setup == "unknown":
        request_id = "f" * 24
    else:
        prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED), ttl_seconds=-1 if setup == "expired" else 120)
        request_id = prop.request_id
        if setup == "cancelled":
            assert _approve(open_api, request_id, approve=False).json() == {"ok": True}
    res = _approve(open_api, request_id)
    assert res.status_code == status and res.json()["error"]["code"] == code, res.text
    assert res.json()["error"]["data"]["reason"] == setup
    assert "Traceback" not in res.text and ".py" not in res.text
    assert open_api.calls == []


def test_malformed_bodies_are_422_not_500(open_api):
    for body in ({}, {"request_id": 5}, {"request_id": "x", "approve": "maybe"}, {"approve": True}):
        res = open_api.client.post("/api/approve-trade", json=body)
        assert res.status_code == 422, (body, res.status_code, res.text)


def test_an_order_the_engine_refuses_is_an_error_and_is_not_recorded_as_executed(open_api, monkeypatch):
    """Tool functions return {"ok": false} instead of raising; that used to come back as HTTP 200 + executed."""
    refusal = {"ok": False, "error": {"code": "policy_blocked", "message": "symbol not allowed", "data": {}}}
    monkeypatch.setattr(open_api.mod, "place_cex_order", lambda **kw: json.dumps(refusal))
    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(open_api, prop.request_id)
    assert res.status_code == 422 and res.json() == refusal, res.text
    assert open_api.store.is_executed(prop.request_id) is False
    again = _approve(open_api, prop.request_id)
    assert again.status_code == 409 and again.json()["error"]["data"]["reason"] == "already_confirmed", "single-use: no silent retry"


# --------------------------------------------------------------------------- who may approve


def test_secured_api_requires_a_jwt_at_all(secured_api):
    prop = secured_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    assert secured_api.client.get("/api/pending-approvals").status_code == 401
    assert _approve(secured_api, prop.request_id).status_code == 401
    assert _approve(secured_api, prop.request_id, token=prop.confirm_token).status_code == 401, "the token alone is not a login"
    assert secured_api.calls == []


def test_admin_jwt_approves_without_a_token(secured_api):
    prop = secured_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(secured_api, prop.request_id, headers=secured_api.admin)
    assert res.status_code == 200 and len(secured_api.calls) == 1, res.text


def test_non_admin_jwt_cannot_approve_without_the_token(secured_api):
    prop = secured_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(secured_api, prop.request_id, headers=secured_api.user)
    assert res.status_code == 403 and res.json()["error"]["code"] == "AUTH_604", res.text
    assert secured_api.calls == []
    assert len(secured_api.client.get("/api/pending-approvals", headers=secured_api.admin).json()["pending"]) == 1, (
        "a denied attempt must not consume the proposal"
    )


def test_tokenless_approval_is_refused_when_auth_is_off_outside_paper_mode(open_api, monkeypatch):
    """Settings validation already forbids live trading without auth; this is the second lock on that door."""
    monkeypatch.setattr(open_api.mod, "settings", SimpleNamespace(API_AUTH_REQUIRED=False, PAPER_MODE=False))
    assert open_api.mod._operator_may_confirm_without_token({"sub": "anonymous", "role": "user"}) is False
    monkeypatch.setattr(open_api.mod, "settings", SimpleNamespace(API_AUTH_REQUIRED=True, PAPER_MODE=False))
    assert open_api.mod._operator_may_confirm_without_token({"sub": "bob", "role": "user"}) is False
    assert open_api.mod._operator_may_confirm_without_token({"sub": "admin", "role": "admin"}) is True


def test_no_mcp_tool_can_reach_the_operator_path():
    """The agent that creates a proposal must never be able to confirm it without the human."""
    root = Path(__file__).resolve().parents[1]
    offenders = [str(p.relative_to(root)) for p in (root / "app" / "tools").glob("*.py") if "confirm_as_operator" in p.read_text()]
    assert offenders == []
    assert "confirm_as_operator" not in (root / "server.py").read_text()


def test_store_level_contract():
    from execution_store import ExecutionStore, ProposalError

    store = ExecutionStore()
    prop = store.create(kind="place_cex_order", payload=dict(PROPOSED))
    with pytest.raises(ValueError):
        store.confirm_as_operator(prop.request_id, operator="  ")
    with pytest.raises(ProposalError) as exc:
        store.confirm(prop.request_id, None)  # type: ignore[arg-type]
    assert exc.value.reason == "invalid_token" and isinstance(exc.value, ValueError)
    assert store.confirm_as_operator(prop.request_id, operator="admin").confirmed_at is not None
    with pytest.raises(ProposalError) as exc:
        store.confirm_as_operator(prop.request_id, operator="admin")
    assert exc.value.reason == "already_confirmed"


# --------------------------------------------------------------------------- red-team findings, pinned


def test_rejecting_needs_the_same_authority_as_approving(secured_api):
    prop = secured_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    denied = _approve(secured_api, prop.request_id, approve=False, headers=secured_api.user)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "AUTH_604", denied.text
    wrong = _approve(secured_api, prop.request_id, approve=False, token="0" * 32, headers=secured_api.user)
    assert wrong.status_code == 403
    assert len(secured_api.client.get("/api/pending-approvals", headers=secured_api.admin).json()["pending"]) == 1, "still pending"
    assert _approve(secured_api, prop.request_id, approve=False, token=prop.confirm_token, headers=secured_api.user).json() == {"ok": True}

    other = secured_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    assert _approve(secured_api, other.request_id, approve=False, headers=secured_api.admin).json() == {"ok": True}
    assert secured_api.calls == []


def test_a_jwt_without_an_expiry_is_not_a_credential(secured_api):
    import jwt

    forever = jwt.encode({"sub": "ghost", "role": "admin"}, secured_api.mod.JWT_SECRET, algorithm="HS256")
    res = secured_api.client.get("/api/pending-approvals", headers={"Authorization": f"Bearer {forever}"})
    assert res.status_code == 401
    unnamed = jwt.encode({"role": "admin", "exp": 4102444800}, secured_api.mod.JWT_SECRET, algorithm="HS256")
    assert secured_api.client.get("/api/pending-approvals", headers={"Authorization": f"Bearer {unnamed}"}).status_code == 401


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("place_cex_order", {"side": "buy", "amount": 1, "paper_mode": True}),
        ("place_cex_order", {"symbol": "BTC/USDT", "side": "buy", "amount": "lots", "paper_mode": True}),
        ("transfer_eth", {"amount": 1, "paper_mode": True}),
        ("kind_from_the_future", {"x": 1, "paper_mode": True}),
    ],
)
def test_a_malformed_proposal_is_422_never_500(open_api, kind, payload):
    prop = open_api.store.create(kind=kind, payload=payload)  # must not raise, must not orphan
    res = _approve(open_api, prop.request_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "EXEC_312", res.text
    assert open_api.calls == []


def test_the_approval_gate_is_never_switched_off_for_other_callers(monkeypatch):
    """
    The endpoint used to set the process-wide EXECUTION_APPROVAL_MODE to "auto" while an approved order was
    in flight, so any other caller in the process executed without approval for the whole exchange round-trip.
    """
    import threading

    import app.tools.execution as tools
    from execution_store import ExecutionStore

    monkeypatch.setattr(tools, "settings", SimpleNamespace(PAPER_MODE=False, EXECUTION_APPROVAL_MODE="approve_each"))
    monkeypatch.setattr(tools.global_container, "execution_store", ExecutionStore())
    seen = {}

    def other_caller():
        seen["other"] = tools._maybe_propose("place_cex_order", dict(ORDER))

    assert tools._maybe_propose("place_cex_order", dict(ORDER)) is not None, "gate on before"
    with tools.approved_execution():
        assert tools._maybe_propose("place_cex_order", dict(ORDER)) is None, "the approved call itself is not re-proposed"
        worker = threading.Thread(target=other_caller)
        worker.start()
        worker.join()
    assert seen["other"] is not None and json.loads(seen["other"])["data"]["approval_required"] is True, "another thread still needs approval"
    assert tools._maybe_propose("place_cex_order", dict(ORDER)) is not None, "gate on after"


def test_the_api_never_mutates_the_global_approval_mode_and_only_it_may_mark_a_call_approved():
    root = Path(__file__).resolve().parents[1]
    assert "set_execution_approval_mode" not in (root / "api_server.py").read_text()
    users = [
        str(p.relative_to(root)) for p in root.rglob("*.py") if "vendor" not in p.parts and "tests" not in p.parts and "approved_execution(" in p.read_text()
    ]
    assert sorted(users) == ["api_server.py", "app/tools/execution.py"], users


def test_trade_history_survives_a_non_finite_row_in_an_old_ledger(open_api, tmp_path, monkeypatch):
    import sqlite3

    from paper_engine import PaperTradingEngine

    engine = PaperTradingEngine(db_path=str(tmp_path / "old-ledger.db"))
    with sqlite3.connect(engine.db_path) as conn:
        conn.execute(
            "INSERT INTO orders (user_id, side, symbol, amount, price, total_value, rationale) VALUES ('agent_zero','sell','BTC/USDT',1.0,?,?,'legacy')",
            (float("inf"), float("inf")),
        )
    monkeypatch.setattr(open_api.mod.global_container, "paper_engine", engine)
    res = open_api.client.get("/api/trades/history")
    assert res.status_code == 200, res.text
    assert res.json()["trades"][0]["price"] is None and "Infinity" not in res.text


# --------------------------------------------------------------------------- the real thing, once


def test_end_to_end_with_the_real_paper_engine(open_api, tmp_path, monkeypatch):
    from paper_engine import PaperTradingEngine

    monkeypatch.undo()  # drop the execution stub installed by the fixture...
    engine = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    monkeypatch.setattr(open_api.mod.global_container, "execution_store", open_api.store)  # ...but keep the isolated store
    monkeypatch.setattr(open_api.mod.global_container, "paper_engine", engine)
    # The tool module keeps the settings object from its FIRST import, which in a full run happened under
    # tests/conftest.py's EXECUTION_MODE=dex; reloading app.core.settings does not reach it. Pin the mode
    # on the object the tool actually reads, so this test does not depend on test order.
    import dataclasses

    import app.tools.execution as execution_tools
    from app.core.settings import ExecutionMode

    monkeypatch.setattr(execution_tools, "settings", dataclasses.replace(execution_tools.settings, EXECUTION_MODE=ExecutionMode.CEX, PAPER_MODE=True))
    # Same staleness applies to the container: fill on the engine the tool module actually holds.
    monkeypatch.setattr(execution_tools.global_container, "paper_engine", engine)
    engine.deposit("agent_zero", "USDT", 20_000.0)  # 0.01 BTC at 50,000 is 2.5%: inside the 5% size rule

    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(open_api, prop.request_id)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True and res.json()["data"]["mode"] == "paper", res.text
    assert engine.get_balance("agent_zero", "BTC") == pytest.approx(0.01)
    assert engine.get_balance("agent_zero", "USDT") == pytest.approx(20_000.0 - 0.01 * 50_000.0, abs=1.0)

    assert _approve(open_api, prop.request_id).status_code == 409
    assert engine.get_balance("agent_zero", "BTC") == pytest.approx(0.01), "second approval must not fill again"


# --------------------------------------------------------------------------- Codex review, PR #13


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_one_non_finite_proposal_cannot_500_the_whole_approvals_list(open_api, bad):
    """
    A proposal is stored BEFORE policy validation, so a non-finite amount can reach the summary.
    Starlette serializes with allow_nan=False, so one such proposal used to make
    /api/pending-approvals return 500 for every operator - hiding every other valid approval.
    """
    open_api.store.create(kind="place_cex_order", payload={**ORDER, "amount": bad})
    good = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))

    res = open_api.client.get("/api/pending-approvals")
    assert res.status_code == 200, res.text
    assert "NaN" not in res.text and "Infinity" not in res.text

    by_id = {item["request_id"]: item for item in res.json()["pending"]}
    assert by_id[good.request_id]["summary"]["amount"] == 0.01, "the valid proposal is still visible"
    assert len(by_id) == 2
    assert [v for k, v in by_id.items() if k != good.request_id][0]["summary"]["amount"] is None


def test_summarize_payload_drops_non_finite_numbers():
    from execution_store import summarize_payload

    out = summarize_payload("place_cex_order", {"symbol": "BTC/USDT", "amount": float("inf"), "price": 5.0})
    assert out["amount"] is None and out["price"] == 5.0


# --------------------------------------------------------------------------- UAT 2026-09-24: modes


@pytest.mark.parametrize("made_in", [False, None])
def test_a_proposal_from_the_other_mode_is_409_and_stays_pending(open_api, made_in):
    """A live proposal approved on a paper API server used to "execute" as a paper fill and be marked
    done. Refused before confirming (409 mode_mismatch), so an API server in the right mode can still
    approve it. A proposal with no recorded mode is refused too (fail closed)."""
    payload = dict(ORDER) if made_in is None else {**ORDER, "paper_mode": made_in}
    prop = open_api.store.create(kind="place_cex_order", payload=payload)
    res = _approve(open_api, prop.request_id, token=prop.confirm_token)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "EXEC_313" and res.json()["error"]["data"]["reason"] == "mode_mismatch"
    assert open_api.calls == [], "nothing executes"
    assert prop.request_id in {p["request_id"] for p in open_api.client.get("/api/pending-approvals").json()["pending"]}


def test_the_guardian_refusal_at_approval_time_is_a_422_with_its_reason(open_api, monkeypatch, tmp_path):
    """The approval API re-runs place_cex_order, and with it the Risk Guardian: an order that no
    longer fits the account when it is approved is refused, not executed."""
    import dataclasses

    import app.tools.execution as execution_tools
    from app.core.settings import ExecutionMode
    from paper_engine import PaperTradingEngine

    engine = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    engine.deposit("agent_zero", "USDT", 1_000.0)  # 0.01 BTC at 50,000 is half of this account
    monkeypatch.setattr(open_api.mod, "place_cex_order", execution_tools.place_cex_order)
    monkeypatch.setattr(execution_tools, "settings", dataclasses.replace(execution_tools.settings, EXECUTION_MODE=ExecutionMode.CEX, PAPER_MODE=True))
    monkeypatch.setattr(execution_tools.global_container, "paper_engine", engine)

    prop = open_api.store.create(kind="place_cex_order", payload=dict(PROPOSED))
    res = _approve(open_api, prop.request_id)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "risk_blocked" and "Position size too large" in res.json()["error"]["message"]
    assert engine.get_balance("agent_zero", "BTC") == 0.0
