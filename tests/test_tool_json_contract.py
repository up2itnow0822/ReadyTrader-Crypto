"""
Contract tests for the shared JSON envelope encoder (app/core/jsonio.py)
and for the two MCP tools it was introduced to fix:

- fetch_ohlcv (app/tools/market_data.py) used to fail on every call with
  "Object of type Timestamp is not JSON serializable".
- get_crypto_price (app/tools/market_data.py) gained price/source/timestamp
  fields.

These tests call the REAL registered tool functions (via FastMCP's own
tool registry, exactly as server.py wires them up), stubbing only the
underlying data sources -- never the JSON serializer itself.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastmcp import FastMCP

from app.core.container import global_container
from app.core.jsonio import json_err, json_ok
from app.tools.market_data import register_market_tools

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# (a) Unit tests for app/core/jsonio.py
# ---------------------------------------------------------------------------


class Color(Enum):
    RED = "red"


def test_json_ok_shape_and_defaults():
    out = json.loads(json_ok())
    assert out == {"ok": True, "data": {}}


def test_json_ok_indent_and_sort_keys():
    raw = json_ok({"b": 1, "a": 2})
    # sort_keys=True -> "a" (inside data) sorted before "b"; indent=2 -> multiline.
    assert raw.index('"a"') < raw.index('"b"')
    assert "\n" in raw


def test_json_err_shape():
    out = json.loads(json_err("some_code", "some message", {"x": 1}))
    assert out == {"ok": False, "error": {"code": "some_code", "message": "some message", "data": {"x": 1}}}


def test_json_err_default_data_is_empty_dict():
    out = json.loads(json_err("c", "m"))
    assert out["error"]["data"] == {}


def test_datetime_and_date_become_iso_strings():
    dt = datetime(2024, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    d = date(2024, 3, 4)
    out = json.loads(json_ok({"dt": dt, "d": d}))
    assert out["data"]["dt"] == dt.isoformat()
    assert out["data"]["d"] == "2024-03-04"


def test_pandas_timestamp_becomes_iso_string():
    ts = pd.Timestamp("2024-01-01T12:30:00Z")
    out = json.loads(json_ok({"ts": ts}))
    parsed = datetime.fromisoformat(out["data"]["ts"])
    assert parsed.year == 2024 and parsed.month == 1 and parsed.day == 1


def test_pandas_nat_becomes_null():
    out = json.loads(json_ok({"nat": pd.NaT}))
    assert out["data"]["nat"] is None


def test_nan_becomes_null():
    out = json.loads(json_ok({"a": float("nan"), "b": np.float64("nan")}))
    assert out["data"]["a"] is None
    assert out["data"]["b"] is None


def test_decimal_becomes_float():
    out = json.loads(json_ok({"amount": Decimal("12.50")}))
    assert out["data"]["amount"] == 12.5
    assert isinstance(out["data"]["amount"], float)


def test_numpy_scalars_become_native_python():
    out = json.loads(json_ok({"i": np.int64(7), "f": np.float64(1.5), "b": np.bool_(True)}))
    assert out["data"]["i"] == 7
    assert out["data"]["f"] == 1.5
    assert out["data"]["b"] is True


def test_numpy_array_becomes_list():
    out = json.loads(json_ok({"arr": np.array([1, 2, 3])}))
    assert out["data"]["arr"] == [1, 2, 3]


def test_set_becomes_sorted_list():
    out = json.loads(json_ok({"s": {3, 1, 2}}))
    assert out["data"]["s"] == [1, 2, 3]


def test_enum_becomes_its_value():
    out = json.loads(json_ok({"color": Color.RED}))
    assert out["data"]["color"] == "red"


def test_unknown_object_raises_type_error():
    @dataclass
    class Unknown:
        x: int = 1

    with pytest.raises(TypeError):
        json_ok({"bad": Unknown()})


def test_unknown_object_is_not_silently_stringified():
    class Weird:
        def __str__(self):
            return "should never appear"

    with pytest.raises(TypeError):
        json_err("code", "message", {"bad": Weird()})


def test_nested_containers_are_sanitized_recursively():
    out = json.loads(
        json_ok(
            {
                "list": [pd.Timestamp("2024-01-01T00:00:00Z"), Decimal("2.0"), float("nan")],
                "nested": {"inner": np.array([np.int64(1), np.int64(2)])},
            }
        )
    )
    assert out["data"]["list"][1] == 2.0
    assert out["data"]["list"][2] is None
    assert out["data"]["nested"]["inner"] == [1, 2]


# ---------------------------------------------------------------------------
# Helpers to obtain the REAL registered tool callables
# ---------------------------------------------------------------------------


class _FakeBacktestEngine:
    """Stands in for global_container.backtest_engine.

    Only the data source is stubbed; the tool's own conversion/serialization
    code (the thing under test) runs unmodified.
    """

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return pd.DataFrame(self._rows[:limit])


def _synthetic_ohlcv_rows(n: int = 3) -> list[dict[str, Any]]:
    base = pd.Timestamp("2024-06-01T00:00:00Z")
    rows = []
    for i in range(n):
        rows.append(
            {
                "timestamp": base + pd.Timedelta(hours=i),  # real pandas.Timestamp
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10.0 + i,
            }
        )
    return rows


async def _get_tool_fn(register_fn, name: str):
    mcp = FastMCP("test-contract")
    register_fn(mcp)
    tool = await mcp.get_tool(name)
    return tool.fn


# ---------------------------------------------------------------------------
# (b) fetch_ohlcv: real registered tool, stubbed data source only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_real_tool_is_json_serializable(monkeypatch):
    monkeypatch.setattr(global_container, "backtest_engine", _FakeBacktestEngine(_synthetic_ohlcv_rows(3)))

    fn = await _get_tool_fn(register_market_tools, "fetch_ohlcv")
    result = fn(symbol="BTC/USDT", timeframe="1h", limit=3)

    parsed = json.loads(result)
    assert parsed["ok"] is True

    records = parsed["data"]["data"]
    assert len(records) == 3
    for rec in records:
        # timestamp must be a real ISO-8601 string.
        datetime.fromisoformat(rec["timestamp"])
        # timestamp_ms must be an int (epoch milliseconds).
        assert isinstance(rec["timestamp_ms"], int)
        assert not isinstance(rec["timestamp_ms"], bool)
        for key in ("open", "high", "low", "close", "volume"):
            assert isinstance(rec[key], float)

    # First candle's timestamp_ms must match the synthetic base timestamp.
    assert records[0]["timestamp_ms"] == 1717200000000  # 2024-06-01T00:00:00Z


@pytest.mark.asyncio
async def test_fetch_ohlcv_real_tool_reports_engine_errors_via_json_err(monkeypatch):
    class _BrokenEngine:
        def fetch_ohlcv(self, symbol, timeframe, limit):
            raise ValueError("boom")

    monkeypatch.setattr(global_container, "backtest_engine", _BrokenEngine())
    fn = await _get_tool_fn(register_market_tools, "fetch_ohlcv")
    parsed = json.loads(fn(symbol="BTC/USDT", timeframe="1h", limit=3))
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "fetch_ohlcv_error"


# ---------------------------------------------------------------------------
# (c) get_crypto_price: real registered tool, stubbed ticker source only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeMarketDataResult:
    source: str
    data: dict


class _FakeMarketDataBus:
    def __init__(self, result: _FakeMarketDataResult):
        self._result = result

    def fetch_ticker(self, symbol: str) -> _FakeMarketDataResult:
        return self._result


@pytest.mark.asyncio
async def test_get_crypto_price_real_tool_adds_price_source_timestamp(monkeypatch):
    fake_result = _FakeMarketDataResult(
        source="ccxt_rest",
        data={"symbol": "BTC/USDT", "last": 65000.5, "timestamp_ms": 1717200000123},
    )
    monkeypatch.setattr(global_container, "marketdata_bus", _FakeMarketDataBus(fake_result))

    fn = await _get_tool_fn(register_market_tools, "get_crypto_price")
    parsed = json.loads(fn(symbol="BTC/USDT", exchange="binance"))

    assert parsed["ok"] is True
    data = parsed["data"]

    # Legacy fields must still be present, byte-for-byte sentence included.
    assert data["symbol"] == "BTC/USDT"
    assert data["exchange"] == "binance"
    assert data["result"] == "The current price of BTC/USDT is 65000.5 (Source: ccxt_rest)"

    # New fields.
    assert isinstance(data["price"], float)
    assert data["price"] == 65000.5
    assert data["source"] == "ccxt_rest"
    parsed_ts = datetime.fromisoformat(data["timestamp"])
    assert parsed_ts.tzinfo is not None


@pytest.mark.asyncio
async def test_get_crypto_price_real_tool_handles_missing_last_and_timestamp(monkeypatch):
    fake_result = _FakeMarketDataResult(source="ingest", data={"symbol": "ETH/USDT"})
    monkeypatch.setattr(global_container, "marketdata_bus", _FakeMarketDataBus(fake_result))

    fn = await _get_tool_fn(register_market_tools, "get_crypto_price")
    parsed = json.loads(fn(symbol="ETH/USDT", exchange="binance"))

    assert parsed["ok"] is True
    data = parsed["data"]
    assert data["price"] is None
    assert data["timestamp"] is None
    assert data["source"] == "ingest"


# ---------------------------------------------------------------------------
# (d) examples/paper_quick_demo.py end-to-end via subprocess
# ---------------------------------------------------------------------------


def test_paper_quick_demo_exits_zero_and_reports_no_failure():
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "PAPER_MODE": "true",
        "SIGNER_TYPE": "null",
        "DEV_MODE": "true",
        "LIVE_TRADING_ENABLED": "false",
        "TRADING_HALTED": "true",
    }
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "paper_quick_demo.py")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"exit code {proc.returncode}\n{combined}"
    assert "DEMO FAILED" not in combined, combined
    assert "nsufficient" not in combined, combined
