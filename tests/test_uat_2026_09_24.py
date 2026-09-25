"""
Regression tests for the 2026-09-24 public-release UAT (uat/runs/2026-09-24-01). Each one fails on
the code before that run.

- BE-01  the Risk Guardian runs on every order (paper and live), not only in validate_trade_risk
- BE-02  paper fills at the market price; a limit fills only when marketable
- BE-03  paper swaps trade at the market rate (they filled at 1.0)
- BE-04  paper mode never reaches an exchange account
- BE-05  live replace_cex_order passes the approval gate, policy and Guardian
- BE-06  live refusals name the rule (kill switch, allowlist, size limit)
- BE-07  log lines carry the time of the event
- DATA-01 drawdown is the current fall from the peak; resting orders keep their value
- DATA-02 asset codes are case-insensitive
- CF-01  default data files live in the repo, whatever the working directory
- INT-01 a source that cannot answer is an error
- T5     proposals cross processes that share EXECUTION_SESSION_ID; approval is single-use across them
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app.tools.execution as ex
import app.tools.trading as tr
from app.core.settings import ApprovalMode, ExecutionMode
from paper_engine import PaperTradingEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
USER = "agent_zero"


def _set_mode(monkeypatch, **overrides):
    """Point both tool modules at one settings object (they each hold the object from first import)."""
    new = copy.copy(ex.settings)  # a copy, without re-running the (live-profile) validation
    for key, value in overrides.items():
        object.__setattr__(new, key, value)
    monkeypatch.setattr(ex, "settings", new)
    monkeypatch.setattr(tr, "settings", new)
    return new


def _live_mode(monkeypatch, *, halted=False, approval=ApprovalMode.AUTO):
    return _set_mode(
        monkeypatch,
        PAPER_MODE=False,
        LIVE_TRADING_ENABLED=True,
        TRADING_HALTED=halted,
        EXECUTION_MODE=ExecutionMode.CEX,
        EXECUTION_APPROVAL_MODE=approval,
    )


@pytest.fixture
def paper(monkeypatch, tmp_path):
    engine = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    _set_mode(monkeypatch, PAPER_MODE=True, EXECUTION_MODE=ExecutionMode.CEX)
    monkeypatch.setattr(ex.global_container, "paper_engine", engine)
    monkeypatch.setattr(tr.global_container, "paper_engine", engine)
    return engine


class Recorder:
    """Stands in for CexExecutor: records every call, sends nothing."""

    calls: list = []

    def __init__(self, *a, **k):
        pass

    def fetch_balance(self):
        Recorder.calls.append(("fetch_balance", {}))
        return {"total": {"USDT": 100_000.0, "BTC": 0.5}}

    def __getattr__(self, name):
        def call(*a, **k):
            Recorder.calls.append((name, k))
            return {"id": "stub", "status": "open"}

        return call

    def normalize_order(self, order):
        return order


@pytest.fixture
def live(monkeypatch):
    Recorder.calls = []
    _set_mode(
        monkeypatch,
        PAPER_MODE=False,
        LIVE_TRADING_ENABLED=True,
        TRADING_HALTED=False,
        EXECUTION_MODE=ExecutionMode.CEX,
        EXECUTION_APPROVAL_MODE=ApprovalMode.AUTO,
    )
    monkeypatch.setattr(ex, "CexExecutor", Recorder)
    monkeypatch.setattr(tr, "CexExecutor", Recorder)
    for name in ("ALLOW_EXCHANGES", "ALLOW_CEX_SYMBOLS", "MAX_CEX_ORDER_AMOUNT", "ALLOW_CEX_MARKET_TYPES"):
        monkeypatch.delenv(name, raising=False)
    return Recorder


def _j(out: str) -> dict:
    return json.loads(out)


# --------------------------------------------------------------------------- BE-01


def test_paper_order_is_refused_for_the_same_reason_validate_trade_risk_gives(paper):
    paper.deposit(USER, "USDT", 10_000.0)
    advice = _j(tr.validate_trade_risk("buy", "BTC/USDT", 5_000.0, 10_000.0))["data"]["result"]
    assert advice["allowed"] is False and "Position size too large" in advice["reason"]
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 0.1))  # 0.1 x 50,000 = 5,000 = 50%
    assert out["ok"] is False and out["error"]["code"] == "risk_blocked", out
    assert "Position size too large" in out["error"]["message"]
    assert paper.get_balances(USER) == {"USDT": 10_000.0}, "nothing filled"


def test_selling_a_holding_is_an_exit_and_passes_even_in_a_drawdown(paper, monkeypatch):
    paper.deposit(USER, "USDT", 1_000.0)
    paper.deposit(USER, "BTC", 1.0)
    monkeypatch.setattr(paper, "get_risk_metrics", lambda user: {"daily_pnl_pct": -0.2, "drawdown_pct": 0.3})
    buy = _j(ex.place_cex_order("BTC/USDT", "buy", 0.001))
    assert buy["ok"] is False and "Max Drawdown" in buy["error"]["message"]
    sell = _j(ex.place_cex_order("BTC/USDT", "sell", 1.0))  # 50,000: all of it, but it only reduces
    assert sell["ok"] is True, sell
    assert sell["data"]["risk"]["exposure_added_units"] == 0.0


def test_live_order_that_cannot_be_sized_fails_closed(live, monkeypatch):
    monkeypatch.setattr(tr, "_live_totals", lambda exchange, market_type: None)
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 0.001, "limit", 50_000.0))
    assert out["ok"] is False and out["error"]["code"] == "risk_blocked"
    assert "account's value" in out["error"]["message"]
    assert not [c for c in live.calls if c[0] == "place_order"]


def test_an_account_with_no_value_does_not_skip_the_size_rule(paper, live, monkeypatch):
    """0 equity used to skip the 5% rule ("if portfolio_value > 0"), so any size passed."""
    monkeypatch.setattr(tr, "_live_totals", lambda exchange, market_type: {"XYZ": 5.0})  # nothing priceable
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 10.0, "limit", 50_000.0))
    assert out["error"]["code"] == "risk_blocked" and "no value" in out["error"]["message"]


def test_live_order_is_sized_against_the_exchange_account(live):
    # Account: 100,000 USDT + 0.5 BTC (25,000) = 125,000; 5% is 6,250.
    big = _j(ex.place_cex_order("BTC/USDT", "buy", 0.2, "limit", 50_000.0))  # 10,000
    assert big["ok"] is False and big["error"]["code"] == "risk_blocked"
    ok = _j(ex.place_cex_order("BTC/USDT", "buy", 0.1, "limit", 50_000.0))  # 5,000
    assert ok["ok"] is True, ok
    exit_ = _j(ex.place_cex_order("BTC/USDT", "sell", 0.5, "limit", 50_000.0))  # sells what is held
    assert exit_["ok"] is True, exit_


def test_a_proposal_is_made_only_for_an_order_the_policy_allows(live, monkeypatch):
    _live_mode(monkeypatch, approval=ApprovalMode.APPROVE_EACH)
    monkeypatch.setenv("ALLOW_CEX_SYMBOLS", "ETH/USDT")
    create = MagicMock()
    monkeypatch.setattr(ex.global_container.execution_store, "create", create)
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 0.001, "limit", 50_000.0))
    assert out["error"]["code"] == "symbol_not_allowed"
    create.assert_not_called()


def test_live_proposal_is_checked_before_it_is_made(live, monkeypatch):
    _live_mode(monkeypatch, approval=ApprovalMode.APPROVE_EACH)
    create = MagicMock()
    monkeypatch.setattr(ex.global_container.execution_store, "create", create)
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 1.0, "limit", 50_000.0))
    assert out["error"]["code"] == "risk_blocked"
    create.assert_not_called()


# --------------------------------------------------------------------------- BE-02


def test_paper_limit_below_market_is_not_filled(paper):
    paper.deposit(USER, "USDT", 100_000.0)
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 0.01, "limit", 40_000.0))
    assert out["ok"] is False and out["error"]["code"] == "limit_not_marketable"
    assert paper.get_balances(USER) == {"USDT": 100_000.0}


def test_paper_market_order_ignores_an_invented_price_and_a_marketable_limit_fills_at_market(paper):
    paper.deposit(USER, "USDT", 100_000.0)
    buy = _j(ex.place_cex_order("BTC/USDT", "buy", 0.01, "limit", 55_000.0))
    assert buy["data"]["fill"]["price"] == 50_000.0
    sell = _j(ex.place_cex_order("BTC/USDT", "sell", 0.01, "market", 200_000.0))
    assert sell["data"]["fill"]["price"] == 50_000.0
    assert paper.get_balance(USER, "USDT") == pytest.approx(100_000.0), "a round trip at market makes nothing"


# --------------------------------------------------------------------------- BE-03


def test_paper_swap_trades_at_the_market_rate(paper):
    paper.deposit(USER, "ETH", 1.0)
    paper.deposit(USER, "USDC", 100_000.0)
    out = _j(ex.swap_tokens("ETH", "USDC", 1.0))
    assert out["ok"] is True, out
    assert paper.get_balance(USER, "USDC") == pytest.approx(102_500.0)
    back = _j(ex.swap_tokens("USDC", "ETH", 100.0))
    assert back["ok"] is True, back
    assert paper.get_balance(USER, "ETH") == pytest.approx(100.0 / 2_500.0)


def test_paper_swap_without_a_rate_is_refused(paper):
    paper.deposit(USER, "ETH", 1.0)
    out = _j(ex.swap_tokens("ETH", "NOPE", 1.0))
    assert out["ok"] is False and out["error"]["code"] == "paper_price_required"
    assert paper.get_balances(USER) == {"ETH": 1.0}


# --------------------------------------------------------------------------- BE-04


@pytest.mark.parametrize(
    "call",
    [
        lambda: ex.get_cex_order("1", "BTC/USDT"),
        lambda: ex.cancel_cex_order("1", "BTC/USDT"),
        lambda: ex.cancel_all_cex_orders(),
        lambda: ex.list_cex_open_orders(),
        lambda: ex.list_cex_orders(),
        lambda: ex.get_cex_my_trades(),
        lambda: ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 5.0, "limit", 90_000.0),
        lambda: ex.wait_for_cex_order("binance", "1", "BTC/USDT", timeout_sec=1),
    ],
)
def test_paper_mode_never_reaches_an_exchange_account(paper, monkeypatch, call):
    Recorder.calls = []
    monkeypatch.setattr(ex, "CexExecutor", Recorder)
    out = _j(call())
    assert out["ok"] is False and out["error"]["code"] == "paper_mode_not_supported"
    assert Recorder.calls == []


# --------------------------------------------------------------------------- BE-05


def test_live_replace_needs_approval_in_approve_each(live, monkeypatch):
    _live_mode(monkeypatch, approval=ApprovalMode.APPROVE_EACH)
    out = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 0.01, "limit", 50_000.0))
    assert out["error"]["code"] == "approval_required"
    assert not [c for c in live.calls if c[0] == "replace_order"]


def test_live_replace_passes_policy_and_the_guardian(live, monkeypatch):
    monkeypatch.setenv("ALLOW_CEX_SYMBOLS", "ETH/USDT")
    out = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 0.01, "limit", 50_000.0))
    assert out["error"]["code"] == "symbol_not_allowed"
    monkeypatch.delenv("ALLOW_CEX_SYMBOLS")
    out = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 5.0, "limit", 50_000.0))
    assert out["error"]["code"] == "risk_blocked"
    assert not [c for c in live.calls if c[0] == "replace_order"]
    ok = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 0.01, "limit", 50_000.0))
    assert ok["ok"] is True and [c for c in live.calls if c[0] == "replace_order"]


# --------------------------------------------------------------------------- BE-06


def test_live_refusals_name_the_rule(live, monkeypatch):
    _live_mode(monkeypatch, halted=True)
    assert _j(ex.place_cex_order("ETH/USDT", "buy", 0.05, "limit", 2_500.0))["error"]["code"] == "trading_halted"
    _live_mode(monkeypatch)
    monkeypatch.setenv("ALLOW_CEX_SYMBOLS", "ETH/USDT")
    monkeypatch.setenv("MAX_CEX_ORDER_AMOUNT", "0.1")
    refused = _j(ex.place_cex_order("BTC/USDT", "buy", 0.01, "limit", 50_000.0))["error"]
    assert refused["code"] == "symbol_not_allowed" and refused["data"]["allow_cex_symbols"] == ["eth/usdt"]
    assert _j(ex.place_cex_order("ETH/USDT", "buy", 0.5, "limit", 2_500.0))["error"]["code"] == "order_amount_too_large"


# --------------------------------------------------------------------------- BE-07


def test_log_lines_carry_the_time_of_the_event(capsys):
    from observability.logging import build_log_context, log_event

    ctx = build_log_context(tool="api_server")
    ctx["ts_ms"] = 1  # a context built long ago
    log_event("x", ctx=ctx)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert abs(line["ts_ms"] - time.time() * 1000) < 60_000


# --------------------------------------------------------------------------- DATA-01 / DATA-02


def test_drawdown_is_current_and_recovers(tmp_path):
    e = PaperTradingEngine(db_path=str(tmp_path / "p.db"))
    e.deposit("u", "USDT", 10_000.0)
    e.execute_trade("u", "buy", "BTC/USDT", 0.05, 84_000.0, "t")
    e.execute_trade("u", "sell", "BTC/USDT", 0.05, 60_000.0, "t")
    assert e.get_risk_metrics("u")["drawdown_pct"] == pytest.approx(0.12)
    e.execute_trade("u", "buy", "ETH/USDT", 1.0, 2_000.0, "t")
    e.execute_trade("u", "sell", "ETH/USDT", 1.0, 3_300.0, "t")
    m = e.get_risk_metrics("u")
    assert m["drawdown_pct"] == 0.0 and m["max_drawdown_pct"] == pytest.approx(0.12)


def test_a_resting_order_keeps_its_value(tmp_path):
    e = PaperTradingEngine(db_path=str(tmp_path / "p.db"))
    e.deposit("u", "USDT", 10_000.0)
    e.place_limit_order("u", "buy", "ETH/USDT", 1.0, 2_000.0)
    assert e.get_portfolio_value_usd("u") == pytest.approx(10_000.0)
    assert e.get_risk_metrics("u")["drawdown_pct"] == 0.0


def test_asset_codes_are_case_insensitive(paper):
    assert _j(tr.deposit_paper_funds("usdt", 100_000.0))["data"]["asset"] == "USDT"
    assert _j(ex.place_cex_order("BTC/USDT", "buy", 0.01))["ok"] is True
    assert _j(ex.place_cex_order("btc/usdt", "buy", 0.01))["ok"] is True
    assert set(paper.get_balances(USER)) == {"USDT", "BTC"}
    assert paper.get_balance(USER, "btc") == pytest.approx(0.02)


# --------------------------------------------------------------------------- CF-01


def test_default_data_files_live_in_the_repo(monkeypatch):
    import storage_paths

    monkeypatch.delenv("READYTRADER_DATA_DIR", raising=False)
    assert Path(storage_paths.data_path("paper.db")) == REPO_ROOT / "data" / "paper.db"
    monkeypatch.setenv("READYTRADER_DATA_DIR", "/srv/rt")
    assert storage_paths.data_path("paper.db") == "/srv/rt/paper.db"


def test_server_started_from_another_folder_keeps_its_data_out_of_it(tmp_path):
    client_cwd, data_dir = tmp_path / "client", tmp_path / "data"
    client_cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_PATH")}
    env.update({"PAPER_MODE": "true", "SIGNER_TYPE": "null", "DEV_MODE": "false", "READYTRADER_DATA_DIR": str(data_dir)})
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "server.py")], cwd=client_cwd, env=env, input=b"", capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    assert list(client_cwd.iterdir()) == [], "nothing is written to the client's working directory"
    assert (data_dir / "paper.db").exists()


# --------------------------------------------------------------------------- INT-01


def test_unconfigured_sources_are_errors(monkeypatch):
    from fastmcp import FastMCP

    import app.tools.research as research

    for name in ("NEWSAPI_KEY", "CRYPTOPANIC_API_KEY", "TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    from app.tools.market_data import register_market_tools

    mcp = FastMCP("t")
    research.register_research_tools(mcp)
    register_market_tools(mcp)
    import asyncio

    async def call(name, args):
        tool = await mcp.get_tool(name)
        return json.loads(tool.fn(**args))

    calls = (("get_financial_news", {"symbol": "BTC"}), ("get_news", {}), ("get_social_sentiment", {"symbol": "BTC"}))
    for name, args in calls:
        out = asyncio.run(call(name, args))
        assert out["ok"] is False and out["error"]["code"] == "not_configured", (name, out)


# --------------------------------------------------------------------------- T5


def test_proposals_cross_processes_that_share_a_session(monkeypatch, tmp_path):
    from execution_store import ExecutionStore, ProposalError

    monkeypatch.setenv("EXECUTION_DB_PATH", str(tmp_path / "exec.db"))
    monkeypatch.setenv("EXECUTION_SESSION_ID", "desk-1")
    mcp_side, api_side, api_worker2 = ExecutionStore(), ExecutionStore(), ExecutionStore()
    prop = mcp_side.create(kind="place_cex_order", payload={"symbol": "BTC/USDT", "paper_mode": False})
    assert [p["request_id"] for p in api_side.list_pending()["pending"]] == [prop.request_id]

    api_side.confirm(prop.request_id, prop.confirm_token)
    with pytest.raises(ProposalError):
        api_worker2.confirm(prop.request_id, prop.confirm_token)  # approval is single-use across processes
    assert api_worker2.cancel(prop.request_id) is False
    assert api_worker2.list_pending()["pending"] == []

    monkeypatch.setenv("EXECUTION_SESSION_ID", "desk-2")
    assert ExecutionStore().get(prop.request_id) is None, "another session never sees it"
    monkeypatch.delenv("EXECUTION_SESSION_ID")
    assert ExecutionStore().list_pending()["pending"] == [], "without a shared id each process is its own session"


# --------------------------------------------------------------------------- CF-03


def test_env_example_starts_from_a_signer_the_live_profile_accepts():
    values = dict(line.split("=", 1) for line in (REPO_ROOT / "env.example").read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    assert values["SIGNER_TYPE"] == "null", "env_private_key is development-only and refused outside paper mode"
    env = {
        **{k: v for k, v in os.environ.items() if k not in values},
        **values,
        "PAPER_MODE": "false",
        "LIVE_TRADING_ENABLED": "true",
        "TRADING_HALTED": "true",
        "DEV_MODE": "false",
        "API_AUTH_REQUIRED": "true",
        "API_JWT_SECRET": "0123456789abcdef0123456789abcdef",
        "CORS_ORIGINS": "http://localhost:3000",
    }
    proc = subprocess.run([sys.executable, "-c", "import app.core.settings"], cwd=REPO_ROOT, env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[-1500:]


# --------------------------------------------------------------------------- BE-12


def test_production_login_with_a_bcrypt_hash(tmp_path):
    """DEV_MODE=false + API_ADMIN_PASSWORD_HASH: the right password gets a token. passlib could not
    drive bcrypt 5, so every production login answered 401 (and the image had no passlib: 500)."""
    code = r"""
import sys, bcrypt
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
import api_server
c = TestClient(api_server.app)
ok = c.post("/api/auth/login", json={"username": "admin", "password": "right-pw"})
bad = c.post("/api/auth/login", json={"username": "admin", "password": "wrong-pw"})
long = c.post("/api/auth/login", json={"username": "admin", "password": "x" * 100})
print(ok.status_code, bool(ok.json().get("access_token")), bad.status_code, long.status_code)
"""
    import bcrypt

    env = {
        **os.environ,
        "PAPER_MODE": "true",
        "DEV_MODE": "false",
        "SIGNER_TYPE": "null",
        "API_AUTH_REQUIRED": "true",
        "API_JWT_SECRET": "unit-test-secret-0123456789abcdef-0123",
        "API_ADMIN_USERNAME": "admin",
        "API_ADMIN_PASSWORD_HASH": bcrypt.hashpw(b"right-pw", bcrypt.gensalt()).decode(),
        "CORS_ORIGINS": "http://localhost:3000",
        "READYTRADER_DATA_DIR": str(tmp_path),
        "RATE_LIMIT_ENABLED": "false",
    }
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    assert proc.stdout.decode().split()[-4:] == ["200", "True", "401", "401"]


def test_api_auth_libraries_are_runtime_requirements():
    runtime = (REPO_ROOT / "requirements.txt").read_text().lower()
    assert "bcrypt==" in runtime and "pyjwt==" in runtime, "the API image installs only requirements.txt"
    assert "passlib" not in runtime


# --------------------------------------------------------------------------- review round (REV-*)
# Findings of the adversarial review of this run; each test fails on the code before its fix.


def test_live_market_order_is_sized_at_the_market_not_the_callers_price(live):
    # REV-01: a market order fills at the market (50,000), whatever price it carries.
    out = _j(ex.place_cex_order("BTC/USDT", "buy", 1.0, "market", 1.0))
    assert out["ok"] is False and out["error"]["code"] == "risk_blocked", out
    assert out["error"]["data"]["risk"]["reference_price"] == 50_000.0
    assert not [c for c in live.calls if c[0] == "place_order"]
    check = tr.pre_trade_check("BTC/USDT", "buy", 1.0, 1.0, order_type="market")
    assert check["allowed"] is False and check["exposure_added_usd"] == pytest.approx(50_000.0)


def test_live_limit_order_is_sized_at_the_higher_of_limit_and_market(live):
    # REV-01: a marketable limit fills at the market; a resting one at its limit.
    below = tr.pre_trade_check("BTC/USDT", "sell", 10.0, 1.0, market_type="future", order_type="limit")
    assert below["reference_price"] == 50_000.0 and below["allowed"] is False
    above = tr.pre_trade_check("BTC/USDT", "buy", 0.01, 60_000.0, order_type="limit")
    assert above["reference_price"] == 60_000.0 and above["exposure_added_usd"] == pytest.approx(600.0)
    out = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", 5.0, "limit", 1.0))
    assert out["ok"] is False and out["error"]["code"] == "risk_blocked", out
    assert not [c for c in live.calls if c[0] == "replace_order"]


def test_without_a_market_price_only_exits_pass(live):
    # REV-01: the Guardian never falls back to the caller's price.
    buy = tr.pre_trade_check("DOGE/USDT", "buy", 1.0, 0.1, order_type="limit")
    assert buy["allowed"] is False and "No market price" in buy["reason"]
    Recorder.calls = []
    exit_ = tr.pre_trade_check("BTC/USDT", "sell", 0.5, None)  # the account holds 0.5 BTC
    assert exit_["allowed"] is True and exit_["exposure_added_units"] == 0.0


def test_kill_switch_stops_new_orders_but_not_cancels_or_reads(live, monkeypatch):
    # REV-02: with TRADING_HALTED=true an operator can still see and cancel resting orders.
    _live_mode(monkeypatch, halted=True)
    monkeypatch.setattr(ex, "CexExecutor", Recorder)
    monkeypatch.setattr(tr, "CexExecutor", Recorder)
    assert _j(ex.place_cex_order("BTC/USDT", "buy", 0.001))["error"]["code"] == "trading_halted"
    for out in (ex.cancel_all_cex_orders(), ex.cancel_cex_order("1", "BTC/USDT"), ex.list_cex_open_orders(), ex.get_cex_balance()):
        assert _j(out)["ok"] is True, out
    assert {c[0] for c in live.calls} >= {"cancel_all_orders", "cancel_order", "fetch_open_orders"}


def test_a_deposit_does_not_end_a_drawdown_halt(paper, offline_market_prices, monkeypatch):
    # REV-03: the drawdown rule reads trading results (deposits excluded) and the account's value now.
    tr.deposit_paper_funds("USDT", 10_000.0)
    for _ in range(4):
        assert _j(ex.place_cex_order("BTC/USDT", "buy", 0.009))["ok"] is True  # 450 USD each
    monkeypatch.setitem(offline_market_prices, "BTC/USDT", 25_000.0)  # 1,800 -> 900: 9% down
    monkeypatch.setitem(offline_market_prices, "BTC/USDT", 20_000.0)  # 1,800 -> 720: 10.8% down
    first = _j(ex.place_cex_order("BTC/USDT", "buy", 0.001))
    assert first["ok"] is False and "Max Drawdown" in first["error"]["message"], "the price move counts before the next trade"
    tr.deposit_paper_funds("USDT", 50_000.0)
    after = _j(ex.place_cex_order("BTC/USDT", "buy", 0.001))
    assert after["ok"] is False and "Max Drawdown" in after["error"]["message"], after
    assert paper.get_risk_metrics(USER)["drawdown_pct"] == pytest.approx(0.108, abs=1e-3)


def test_deposits_are_not_daily_gains(tmp_path):
    e = PaperTradingEngine(db_path=str(tmp_path / "p.db"))
    e.deposit("u", "USDT", 10_000.0)
    e.execute_trade("u", "buy", "BTC/USDT", 0.1, 50_000.0, "t")
    e.execute_trade("u", "sell", "BTC/USDT", 0.1, 45_000.0, "t")  # -500
    e.deposit("u", "USDT", 90_000.0)
    m = e.get_risk_metrics("u")
    assert m["daily_pnl_pct"] == pytest.approx(-0.05) and m["drawdown_pct"] == pytest.approx(0.05)


def test_selling_into_a_crypto_quote_sizes_what_it_buys(paper, offline_market_prices, monkeypatch):
    # REV-04: SELL ETH on ETH/BTC buys BTC; only a sell into cash is an exit.
    paper.deposit(USER, "USDT", 100_000.0)
    paper.deposit(USER, "ETH", 40.0)
    tr.global_container.paper_engine.mark_price_usd("ETH", 2_500.0)
    check = tr.pre_trade_check("ETH/USDT", "sell", 40.0)
    assert check["allowed"] is True and check["exposure_added_usd"] == 0.0
    monkeypatch.setitem(offline_market_prices, "ETH/BTC", 0.05)
    check = tr.pre_trade_check("ETH/BTC", "sell", 40.0)
    assert check["allowed"] is False and check["acquired_quote_usd"] == pytest.approx(100_000.0), check
    out = _j(ex.place_cex_order("ETH/BTC", "sell", 40.0))
    assert out["ok"] is False and out["error"]["code"] == "risk_blocked"
    assert paper.get_balance(USER, "BTC") == 0.0


def test_nan_amounts_never_reach_the_exchange_or_a_proposal(live, monkeypatch):
    # REV-09 / REV-10
    out = _j(ex.replace_cex_order("binance", "1", "BTC/USDT", "buy", float("nan"), "limit", 50_000.0))
    assert out["ok"] is False and out["error"]["code"] == "invalid_amount"
    assert not [c for c in live.calls if c[0] == "replace_order"]
    assert tr.pre_trade_check("BTC/USDT", "buy", float("nan"))["allowed"] is False
    _live_mode(monkeypatch, approval=ApprovalMode.APPROVE_EACH)
    object.__setattr__(ex.settings, "EXECUTION_MODE", ExecutionMode.HYBRID)
    before = len(ex.global_container.execution_store.list_pending()["pending"])
    for amount in (float("nan"), -3.0, 0.0):
        d = _j(ex.transfer_eth("0x000000000000000000000000000000000000dEaD", amount))
        assert d["ok"] is False and d["error"]["code"] == "invalid_amount", d
    assert len(ex.global_container.execution_store.list_pending()["pending"]) == before


def test_every_usd_stablecoin_counts_at_one_dollar_in_the_paper_account(tmp_path):
    # REV-11: the paper account and the Guardian use one list.
    e = PaperTradingEngine(db_path=str(tmp_path / "p.db"))
    for asset in sorted(tr.USD_STABLES):
        e.deposit("u", asset, 100.0)
    assert e.get_portfolio_value_usd("u") == pytest.approx(100.0 * len(tr.USD_STABLES))


def test_nested_secrets_stay_out_of_the_docker_build_context():
    # REV-05: a bare .dockerignore pattern matches only at the context root.
    rules = {line.strip() for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()}
    assert {"**/.env*", "**/*.pem", "**/*.key", "**/keystore*.json", "**/*.db"} <= rules


def test_docker_mcp_configs_keep_the_paper_account():
    # REV-07: without a volume every MCP session started from an empty paper wallet.
    import yaml

    desktop = json.loads((REPO_ROOT / "configs/claude_desktop.mcp-server-config.json").read_text())
    agent_zero = yaml.safe_load((REPO_ROOT / "configs/agent_zero.mcp.yaml").read_text())
    for args in (desktop["mcpServers"]["readytrader_crypto"]["args"], agent_zero["mcp_servers"]["readytrader_crypto"]["args"]):
        assert args[args.index("-v") + 1].endswith(":/app/data"), args
    assert "-v readytrader-crypto-data:/app/data" in (REPO_ROOT / "README.md").read_text()


def test_sentinel_stack_runs_the_api_server():
    # REV-17: `build: .` gets the default (stdio MCP) stage, which exits with no client.
    import yaml

    stack = yaml.safe_load((REPO_ROOT / "docker-compose.sentinel.yml").read_text())
    assert stack["services"]["readytrader"]["build"]["target"] == "api"


def _call_tool(register, name, args):
    import asyncio

    from fastmcp import FastMCP

    mcp = FastMCP("t")
    register(mcp)
    res = asyncio.run(mcp.call_tool(name, args))
    content = res.content if hasattr(res, "content") else res
    return json.loads(content[0].text)


def test_social_sentiment_says_when_every_configured_source_failed(monkeypatch):
    # REV-12: a configured X source failing came back ok:true with the error inside the text.
    import intelligence.core as core
    from app.tools.research import register_research_tools

    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")
    for var in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    tweepy = MagicMock()
    tweepy.Client.return_value.search_recent_tweets.side_effect = RuntimeError("401 Unauthorized")
    monkeypatch.setattr(core, "tweepy", tweepy)
    try:
        out = _call_tool(register_research_tools, "get_social_sentiment", {"symbol": "BTC"})
    finally:
        core._sentiment_cache.cache.clear()
    assert out["ok"] is False and out["error"]["code"] == "source_unavailable", out
    assert out["error"]["data"]["sources"] == {"twitter": "error", "reddit": "not_configured"}


_API_PROBE = """
import io, json, contextlib
import api_server
from fastapi.testclient import TestClient
calls = []
real = api_server.verify_password
api_server.verify_password = lambda p, h: calls.append(1) or real(p, h)
c = TestClient(api_server.app)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    a = c.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    b = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
ids = [json.loads(l)["request_id"] for l in buf.getvalue().splitlines() if '"auth_failed"' in l]
headers = [a.headers.get("x-request-id"), b.headers.get("x-request-id")]
tok = c.post("/api/auth/login", json={"username": "admin", "password": "right-pw"}).json()["access_token"]
def boom(*args, **kwargs):
    raise RuntimeError("disk I/O error")
api_server.global_container.paper_engine.get_balances = boom
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    e = c.get("/api/portfolio", headers={"Authorization": "Bearer " + tok})
error = {"code": e.status_code, "request_id": e.headers.get("x-request-id"), "frame": e.headers.get("x-frame-options"), "body": e.text[:200]}
print(json.dumps({"codes": [a.status_code, b.status_code], "bcrypt_calls": len(calls) - 1, "headers": headers, "log_ids": ids, "error": error}))
"""


@pytest.fixture(scope="module")
def api_probe(tmp_path_factory):
    import bcrypt

    env = {
        **os.environ,
        "PAPER_MODE": "true",
        "DEV_MODE": "false",
        "SIGNER_TYPE": "null",
        "API_AUTH_REQUIRED": "true",
        "API_JWT_SECRET": "unit-test-secret-0123456789abcdef-0123",
        "API_ADMIN_USERNAME": "admin",
        "API_ADMIN_PASSWORD_HASH": bcrypt.hashpw(b"right-pw", bcrypt.gensalt(4)).decode(),
        "CORS_ORIGINS": "http://localhost:3000",
        "READYTRADER_DATA_DIR": str(tmp_path_factory.mktemp("api")),
        "RATE_LIMIT_ENABLED": "false",
    }
    proc = subprocess.run([sys.executable, "-c", _API_PROBE], cwd=REPO_ROOT, env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    return json.loads(proc.stdout.decode().strip().splitlines()[-1])


def test_login_checks_the_password_whatever_the_username(api_probe):
    # REV-13: an unknown username answered at once, so timing told which usernames exist.
    assert api_probe["codes"] == [401, 401]
    assert api_probe["bcrypt_calls"] == 2


def test_an_unhandled_api_error_keeps_its_request_id_and_headers(api_probe):
    # REV2-08: the 500 used to come from Starlette's outer handler, past every middleware.
    error = api_probe["error"]
    assert error["code"] == 500 and error["request_id"] and error["frame"] == "DENY", error
    assert "SYS_803" in error["body"] and "disk I/O" not in error["body"]


def test_each_api_request_logs_its_own_request_id(api_probe):
    # REV-14: the API logged one request_id for the life of the process.
    assert len(set(api_probe["log_ids"])) == 2 and set(api_probe["log_ids"]) == set(api_probe["headers"])


# --------------------------------------------------------------------------- review round 2 (REV2-*)


def test_contract_symbol_is_never_a_spot_exit(live):
    # REV2-01: ccxt routes BTC/USDT:USDT to the derivatives account whatever market_type says.
    out = _j(ex.place_cex_order("BTC/USDT:USDT", "sell", 0.5))
    assert out["ok"] is False and out["error"]["code"] == "invalid_symbol", out
    assert not [c for c in live.calls if c[0] == "place_order"]
    assert tr.pre_trade_check("BTC/USDT:USDT", "sell", 0.5, market_type="spot")["position_units"] is None


def test_daily_loss_is_measured_from_the_start_of_the_day(paper, offline_market_prices, monkeypatch):
    # REV2-02: a week-old snapshot is not the start of today.
    import sqlite3

    tr.deposit_paper_funds("USDT", 1_000.0)
    tr.deposit_paper_funds("BTC", 1.0)
    conn = sqlite3.connect(paper.db_path)
    conn.execute("UPDATE equity_snapshots SET timestamp='2026-09-17T12:00:00+00:00'")
    conn.commit()
    conn.close()
    monkeypatch.setitem(offline_market_prices, "BTC/USDT", 47_000.0)  # -6% over the week, flat today
    for day in ("2026-09-24", "2026-09-25"):
        monkeypatch.setattr(paper, "_now_iso", lambda d=day: f"{d}T12:00:00+00:00")
        out = _j(ex.place_cex_order("SOL/USDT", "buy", 1.0))
        assert out["ok"] is True, out
        assert paper.get_risk_metrics(USER)["daily_pnl_pct"] == pytest.approx(0.0, abs=1e-9)


def test_loss_limits_measure_against_the_capital_in_the_account_now(tmp_path):
    # REV2-03: a top-up enlarges the base; a 0.1% loss is 0.1%, not 10%.
    e = PaperTradingEngine(db_path=str(tmp_path / "p.db"))
    e.deposit("u", "USDT", 1_000.0)
    e.execute_trade("u", "buy", "BTC/USDT", 0.01, 50_000.0, "t")
    e.mark_price_usd("BTC", 49_800.0)  # -2 USD
    e.deposit("u", "USDT", 100_000.0)
    e.execute_trade("u", "buy", "BTC/USDT", 0.1, 49_800.0, "t")
    e.mark_price_usd("BTC", 48_800.0)  # -110 USD more
    m = e.get_risk_metrics("u")
    assert m["drawdown_pct"] < 0.005 and m["daily_pnl_pct"] > -0.005, m


def test_a_paper_deposit_that_cannot_be_valued_is_refused(paper):
    # REV2-05: booked at 0 it would later read as a gain and end a drawdown halt.
    out = _j(tr.deposit_paper_funds("DOGE", 10.0))  # no test price for DOGE
    assert out["ok"] is False and out["error"]["code"] == "paper_price_required"
    assert paper.get_balances(USER) == {}


def test_falling_knife_judges_the_asset_a_crypto_quoted_sell_buys(paper, offline_market_prices, monkeypatch):
    # REV2-06: SELL ETH/BTC buys BTC, so BTC's sentiment applies.
    monkeypatch.setitem(offline_market_prices, "ETH/BTC", 0.05)
    bearish = {"score": -0.9, "status": "ok", "texts": 40, "bullish": 0, "bearish": 40, "age_seconds": 5}
    monkeypatch.setattr(tr, "_sentiment_context", lambda s: bearish if str(s).upper().split("/")[0] == "BTC" else {**bearish, "score": 0.0})
    tr.deposit_paper_funds("USDT", 100_000.0)
    tr.deposit_paper_funds("ETH", 1.0)
    out = _j(ex.place_cex_order("ETH/BTC", "sell", 1.0))
    assert out["ok"] is False and "Falling Knife" in out["error"]["message"], out
    assert out["error"]["data"]["risk"]["sentiment_asset"] == "BTC"


def test_paper_refuses_contract_symbols_and_live_sends_normalised_orders(paper, live, monkeypatch):
    # REV2-07
    assert paper.execute_trade_result(USER, "sell", "BTC/USDT:USDT", 0.01, 50_000.0)["code"] == "invalid_symbol"
    out = _j(ex.place_cex_order("BTC/USDT", " SELL ", 0.5, "LIMIT", 50_000.0))
    assert out["ok"] is True, out
    sent = [c[1] for c in live.calls if c[0] == "place_order"][-1]
    assert (sent["side"], sent["order_type"]) == ("sell", "limit")


def test_smithery_listing_passes_its_settings_and_stays_paper():
    # REV2-10: configSchema belongs under startCommand, with a commandFunction that sets the env.
    import yaml

    start = yaml.safe_load((REPO_ROOT / "smithery.yaml").read_text())["startCommand"]
    assert start["type"] == "stdio" and "configSchema" in start
    fn = start["commandFunction"]
    assert "PAPER_MODE: 'true'" in fn and "SIGNER_TYPE: 'null'" in fn
    assert "PAPER_MODE" not in start["configSchema"]["properties"]


# ------------------------------------------------------------------------------ AR-01 / AR-02
# Cross-check of the classes the FOREX and Stocks reviews found.


def test_every_numeric_tool_parameter_refuses_true():
    import asyncio

    from fastmcp import Client

    from server import mcp

    def kinds(spec):
        return {spec.get("type"), *(a.get("type") for a in spec.get("anyOf", []))}

    async def run():
        async with Client(mcp) as client:
            outcomes = []
            for tool in await client.list_tools():
                props, required = tool.inputSchema.get("properties", {}), tool.inputSchema.get("required", [])
                for target in [k for k, v in props.items() if kinds(v) & {"number", "integer"}]:
                    args = {k: (1 if kinds(props[k]) & {"number", "integer"} else "x") for k in required}
                    args[target] = True
                    r = await client.call_tool(tool.name, args, raise_on_error=False)
                    outcomes.append((f"{tool.name}.{target}", r.is_error and "true/false" in (r.content[0].text if r.content else "")))
            return outcomes

    outcomes = asyncio.run(run())
    assert len(outcomes) >= 18 and [name for name, refused in outcomes if not refused] == []


def test_the_outer_middlewares_answers_carry_cors_headers(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    import app.core.settings

    for key, value in dict(
        DEV_MODE="false",
        API_AUTH_REQUIRED="true",
        API_JWT_SECRET="test-secret-for-cors",
        CORS_ORIGINS="http://localhost:3000",
        RATE_LIMIT_ENABLED="true",
        RATE_LIMIT_DEFAULT_PER_MIN="2",
    ).items():
        monkeypatch.setenv(key, value)
    importlib.reload(app.core.settings)
    import api_server

    importlib.reload(api_server)
    try:
        client = TestClient(api_server.app)
        answers = [client.get("/api/health", headers={"Origin": "http://localhost:3000"}) for _ in range(4)]
        assert answers[-1].status_code == 429  # written by the rate-limit middleware itself
        assert all(r.headers.get("access-control-allow-origin") == "http://localhost:3000" for r in answers)
    finally:
        monkeypatch.undo()
        importlib.reload(app.core.settings)  # later tests reload api_server with their own env
