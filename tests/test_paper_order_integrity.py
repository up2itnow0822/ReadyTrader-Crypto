"""
The paper ledger must not lie: a paper order either happens and says so in data, or does not happen,
changes nothing, and is reported as an error. Before this, `buy -1 BTC` reported ok and minted
50,000 USDT, `side="hodl"` logged an executed order, NaN escaped as a sqlite traceback, and an
unfunded order returned {"ok": true} with "Insufficient fund" buried in a prose field.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from paper_engine import PaperTradingEngine

USER = "agent_zero"


@pytest.fixture
def engine(tmp_path):
    eng = PaperTradingEngine(db_path=str(tmp_path / "paper.db"))
    eng.deposit(USER, "USDT", 1_000.0)
    return eng


def _balances(eng):
    return {a: eng.get_balance(USER, a) for a in ("USDT", "BTC")}


def _order_count(eng):
    import sqlite3

    with sqlite3.connect(eng.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def test_a_funded_buy_fills_and_reports_numbers(engine):
    res = engine.execute_trade_result(USER, "buy", "BTC/USDT", 0.01, 50_000.0, "test")
    assert res["ok"] is True
    assert res["fill"] == {"side": "buy", "symbol": "BTC/USDT", "amount": 0.01, "price": 50_000.0, "total_value": 500.0, "quote": "USDT"}
    assert _balances(engine) == {"USDT": pytest.approx(500.0), "BTC": pytest.approx(0.01)}
    assert _order_count(engine) == 1


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"side": "buy", "amount": -1.0}, "invalid_amount"),
        ({"side": "sell", "amount": -1.0}, "invalid_amount"),
        ({"side": "buy", "amount": 0.0}, "invalid_amount"),
        ({"side": "buy", "amount": float("nan")}, "invalid_amount"),
        ({"side": "buy", "amount": float("inf")}, "invalid_amount"),
        ({"side": "buy", "amount": "lots"}, "invalid_amount"),
        ({"side": "buy", "amount": 0.01, "price": -5.0}, "invalid_price"),
        ({"side": "buy", "amount": 0.01, "price": float("nan")}, "invalid_price"),
        ({"side": "hodl", "amount": 0.01}, "invalid_side"),
        ({"side": "", "amount": 0.01}, "invalid_side"),
        ({"side": "buy", "amount": 0.01, "symbol": "BTCUSDT"}, "invalid_symbol"),
        ({"side": "buy", "amount": 0.01, "symbol": "BTC/"}, "invalid_symbol"),
        ({"side": "buy", "amount": 1.0}, "insufficient_funds"),
        ({"side": "sell", "amount": 0.01}, "insufficient_funds"),
    ],
)
def test_a_refused_order_changes_nothing(engine, kwargs, code):
    before = _balances(engine)
    args = {"symbol": "BTC/USDT", "price": 50_000.0, **kwargs}
    res = engine.execute_trade_result(USER, args["side"], args["symbol"], args["amount"], args["price"], "test")
    assert res["ok"] is False and res["code"] == code, res
    assert _balances(engine) == before, "a refused order must not move balances"
    assert _order_count(engine) == 0, "a refused order must not be logged as an order"


def test_string_api_is_unchanged_for_existing_callers(engine):
    assert engine.execute_trade(USER, "buy", "BTC/USDT", 0.01, 50_000.0).startswith("Paper Trade Executed: BUY 0.01 BTC/USDT @ 50000.0")
    assert "Insufficient fund" in engine.execute_trade(USER, "buy", "BTC/USDT", 100.0, 50_000.0)


@pytest.fixture
def cex_tool(engine, monkeypatch):
    """The real place_cex_order tool function, on an isolated engine, independent of test order."""
    import app.tools.execution as tools
    from app.core.settings import ExecutionMode

    monkeypatch.setattr(tools, "settings", dataclasses.replace(tools.settings, EXECUTION_MODE=ExecutionMode.CEX, PAPER_MODE=True))
    monkeypatch.setattr(tools.global_container, "paper_engine", engine)
    return lambda **kw: json.loads(tools.place_cex_order(symbol="BTC/USDT", order_type="limit", price=50_000.0, **kw))


def test_tool_reports_a_fill_with_numbers(cex_tool, engine):
    out = cex_tool(side="buy", amount=0.01)
    assert out["ok"] is True and out["data"]["mode"] == "paper"
    assert out["data"]["fill"]["total_value"] == 500.0 and isinstance(out["data"]["result"], str)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"side": "buy", "amount": 1.0}, "insufficient_funds"),
        ({"side": "buy", "amount": -1.0}, "invalid_amount"),
        ({"side": "hodl", "amount": 0.01}, "invalid_side"),
        ({"side": "buy", "amount": float("nan")}, "invalid_amount"),
    ],
)
def test_tool_reports_a_refused_paper_order_as_an_error_not_ok(cex_tool, engine, kwargs, code):
    before = _balances(engine)
    out = cex_tool(**kwargs)
    assert out["ok"] is False and out["error"]["code"] == code, out
    assert _balances(engine) == before


# --------------------------------------------------------------------------- red-team findings, pinned


def test_concurrent_orders_cannot_overdraw_or_lose_updates(tmp_path):
    """Separate read and write connections let 32 parallel buys fill 7 times from a balance that funds one."""
    import threading

    for round_no in range(8):
        eng = PaperTradingEngine(db_path=str(tmp_path / f"race{round_no}.db"))
        eng.deposit(USER, "USDT", 100.0)
        barrier, results = threading.Barrier(24), []

        def buy():
            barrier.wait()
            results.append(eng.execute_trade_result(USER, "buy", "BTC/USDT", 0.002, 50_000.0)["ok"])

        threads = [threading.Thread(target=buy) for _ in range(24)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        assert sum(results) == 1, f"round {round_no}: {sum(results)} fills from a balance that funds exactly one"
        assert eng.get_balance(USER, "USDT") == pytest.approx(0.0) and eng.get_balance(USER, "BTC") == pytest.approx(0.002)
        assert _order_count(eng) == 1


def test_concurrent_deposits_are_not_lost(tmp_path):
    import threading

    eng = PaperTradingEngine(db_path=str(tmp_path / "dep.db"))
    threads = [threading.Thread(target=lambda: eng.deposit(USER, "USDT", 1.0)) for _ in range(40)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert eng.get_balance(USER, "USDT") == pytest.approx(40.0)


def test_nothing_can_be_bought_for_free_through_float_absorption(tmp_path):
    from paper_engine import MAX_MAGNITUDE

    eng = PaperTradingEngine(db_path=str(tmp_path / "big.db"))
    assert "refused" in eng.deposit(USER, "USDT", 1e20).lower() and eng.get_balance(USER, "USDT") == 0.0
    eng.deposit(USER, "USDT", MAX_MAGNITUDE)
    before = eng.get_balance(USER, "USDT")
    res = eng.execute_trade_result(USER, "buy", "BTC/USDT", 1.0, 1_000.0)
    assert res["ok"] is True and eng.get_balance(USER, "USDT") == before - 1_000.0, "at the cap a normal order is still exact"
    tiny = eng.execute_trade_result(USER, "buy", "DUST/USDT", 1e-9, 1e-9)
    assert tiny["ok"] is False and eng.get_balance(USER, "DUST") == 0.0, "an order the ledger cannot represent is refused, not half-applied"


@pytest.mark.parametrize("amount,price", [(1e308, 1e308), (1e13, 1.0), (1.0, 1e13), (float("inf"), 1.0)])
def test_out_of_range_orders_never_put_infinity_in_the_ledger(engine, amount, price):
    engine.deposit(USER, "BTC", 1_000.0)
    before = _balances(engine)
    res = engine.execute_trade_result(USER, "sell", "BTC/USDT", amount, price)
    assert res["ok"] is False and res["code"] in {"invalid_amount", "invalid_price"}
    assert _balances(engine) == before


def test_symbol_is_normalised_so_the_order_log_matches_the_balances(engine):
    res = engine.execute_trade_result(USER, "buy", " BTC / USDT ", 0.01, 50_000.0)
    assert res["ok"] is True and res["fill"]["symbol"] == "BTC/USDT"
    import sqlite3

    with sqlite3.connect(engine.db_path) as conn:
        assert conn.execute("SELECT symbol FROM orders").fetchone()[0] == "BTC/USDT"
    assert engine.execute_trade_result(USER, "buy", "USDT/USDT", 1.0, 1.0)["code"] == "invalid_symbol"


def test_a_placeholder_priced_swap_cannot_rewrite_mark_to_market(engine):
    engine.execute_trade_result(USER, "buy", "BTC/USDT", 0.01, 50_000.0)
    value_before = engine.get_portfolio_value_usd(USER)
    engine.deposit(USER, "BTC", 0.0)  # no-op; keeps the snapshot path exercised
    res = engine.execute_trade_result(USER, "sell", "BTC/USDC", 0.000001, 1.0, "swap", update_price_cache=False)
    assert res["ok"] is True
    assert engine.get_portfolio_value_usd(USER) == pytest.approx(value_before, rel=1e-3), "BTC must still be valued at ~50,000, not 1.0"


@pytest.mark.parametrize("price", [-5.0, float("nan"), "cheap"])
def test_tool_refuses_a_bad_explicit_price_instead_of_substituting_the_market_price(engine, monkeypatch, price):
    import app.tools.execution as tools
    from app.core.settings import ExecutionMode

    monkeypatch.setattr(tools, "settings", dataclasses.replace(tools.settings, EXECUTION_MODE=ExecutionMode.CEX, PAPER_MODE=True))
    monkeypatch.setattr(tools.global_container, "paper_engine", engine)
    monkeypatch.setattr(tools, "_paper_reference_price", lambda symbol: 81_342.0)
    before = _balances(engine)
    out = json.loads(tools.place_cex_order(symbol="BTC/USDT", side="buy", amount=0.001, order_type="limit", price=price))
    assert out["ok"] is False and out["error"]["code"] == "invalid_price", out
    assert _balances(engine) == before


@pytest.mark.parametrize(
    "asset,amount,code",
    [
        ("USDT", 1e20, "invalid_amount"),
        ("USDT", -5, "invalid_amount"),
        ("USDT", float("nan"), "invalid_amount"),
        ("", 5, "invalid_asset"),
        ("BTC/USDT", 5, "invalid_asset"),
    ],
)
def test_deposit_tool_validates_its_input(engine, monkeypatch, asset, amount, code):
    import app.tools.trading as trading

    monkeypatch.setattr(trading, "settings", dataclasses.replace(trading.settings, PAPER_MODE=True))
    monkeypatch.setattr(trading.global_container, "paper_engine", engine)
    before = _balances(engine)
    out = json.loads(trading.deposit_paper_funds(asset, amount))
    assert out["ok"] is False and out["error"]["code"] == code, out
    assert _balances(engine) == before


def test_tool_envelopes_never_contain_infinity_or_nan():
    from app.core.jsonio import json_ok

    text = json_ok({"a": float("inf"), "b": float("-inf"), "c": float("nan"), "d": [1.5, float("inf")]})
    assert "Infinity" not in text and "NaN" not in text
    assert json.loads(text)["data"] == {"a": None, "b": None, "c": None, "d": [1.5, None]}


# --------------------------------------------------------------------------- red-team round 2: the limit-order path


def test_a_limit_order_reserves_funds_or_does_not_exist(engine):
    msg = engine.place_limit_order(USER, "buy", "BTC/USDT", 0.01, 50_000.0)
    assert msg.startswith("Order Placed") and engine.get_balance(USER, "USDT") == pytest.approx(500.0)
    before = _balances(engine)
    for bad in [
        ("buy", "BTC/USDT", 1.5, 1e12),
        ("sell", "BTC/USDT", 1.0, float("inf")),
        ("sell", "BTC/USDT", 1.0, float("nan")),
        ("buy", "A/B/C", 1.0, 1.0),
        ("hodl", "BTC/USDT", 1.0, 1.0),
    ]:
        out = engine.place_limit_order(USER, *bad)
        assert out.startswith(("Order refused", "Insufficient fund")), (bad, out)
    assert _balances(engine) == before and _order_count(engine) == 1


def test_a_limit_fill_credits_exactly_once_and_only_what_was_reserved(engine):
    engine.place_limit_order(USER, "buy", "BTC/USDT", 0.01, 50_000.0)
    assert engine.check_open_orders("BTC/USDT", 60_000.0) == [], "price has not crossed"
    assert len(engine.check_open_orders("BTC/USDT", 49_000.0)) == 1
    assert engine.check_open_orders("BTC/USDT", 49_000.0) == [], "already filled"
    assert _balances(engine) == {"USDT": pytest.approx(500.0), "BTC": pytest.approx(0.01)}
    assert engine.check_open_orders("BTC/USDT", float("nan")) == [] and engine.check_open_orders("nonsense", 1.0) == []


def test_concurrent_limit_orders_cannot_reserve_the_same_funds(tmp_path):
    import threading

    eng = PaperTradingEngine(db_path=str(tmp_path / "limit-race.db"))
    eng.deposit(USER, "USDT", 100.0)
    barrier, placed = threading.Barrier(32), []

    def place():
        barrier.wait()
        placed.append(eng.place_limit_order(USER, "buy", "BTC/USDT", 0.002, 50_000.0).startswith("Order Placed"))

    threads = [threading.Thread(target=place) for _ in range(32)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert sum(placed) == 1 and eng.get_balance(USER, "USDT") == pytest.approx(0.0)


def test_repeated_deposits_cannot_grow_a_balance_past_the_ledger_limit(tmp_path):
    from paper_engine import MAX_BALANCE, MAX_MAGNITUDE

    eng = PaperTradingEngine(db_path=str(tmp_path / "cap.db"))
    results = [eng.deposit(USER, "USDT", MAX_MAGNITUDE) for _ in range(1_002)]
    assert eng.get_balance(USER, "USDT") <= MAX_BALANCE
    assert any("refused" in r.lower() for r in results[-2:])
