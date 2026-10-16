"""Behavioral regressions for aggregate strategy, insight, and source budgets."""

import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from fastmcp import FastMCP

import app.tools.research as research
import intelligence.core as core
import intelligence.insights as insights
import strategy_sandbox as sandbox
from app.tools.market_data import register_market_tools
from rate_limiter import FixedWindowRateLimiter

HOLD = "def on_candle(p, r, s):\n    return 'hold'\n"


@pytest.fixture
def store(tmp_path):
    return insights.InsightStore(str(tmp_path / "insights.db"))


def post(store, **overrides):
    values = dict(symbol="BTC/USDT", agent_id="agent", signal="bullish", confidence=0.8, reasoning="Evidence", ttl_seconds=3600)
    values.update(overrides)
    return store.post_insight(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "é" * 40),
        ("agent_id", "é" * 80),
        ("reasoning", "é" * 5000),
        ("signal", "arbitrary"),
        ("confidence", float("inf")),
        ("confidence", -0.1),
        ("confidence", 1.1),
        ("confidence", True),
        ("ttl_seconds", -1),
        ("ttl_seconds", 86401),
        ("ttl_seconds", True),
        ("ttl_seconds", 1.5),
        ("meta", {"blob": "é" * 3000}),
    ],
    ids=lambda value: str(value)[:30],
)
def test_insights_reject_invalid_fields_without_writes(store, field, value):
    # Removing a field/range guard would persist this value and fail the assertion.
    with pytest.raises(ValueError):
        post(store, **{field: value})
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == 0


def test_insights_reject_nan_without_touching_sqlite(store):
    with pytest.raises(ValueError):
        post(store, confidence=float("nan"))


def test_insights_prune_expired_records_on_read(store):
    saved = post(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE insights SET expires_at_ms=0")
    assert store.get_latest_insights() == []
    assert store.get_insight(saved.insight_id) is None
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == 0


def test_insight_agent_and_total_quotas_are_atomic(store, monkeypatch):
    monkeypatch.setattr(insights, "MAX_AGENT_INSIGHTS", 2, raising=False)
    monkeypatch.setattr(insights, "MAX_TOTAL_INSIGHTS", 3, raising=False)

    def attempt(_):
        try:
            return post(store).insight_id
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(attempt, range(4)))
    assert len([value for value in accepted if value]) == 2
    post(store, agent_id="other")
    with pytest.raises(ValueError):
        post(store, agent_id="new-agent")
    assert len(store.get_latest_insights(limit=100)) == 3


def test_insight_limit_cannot_disable_read_bound(store):
    with pytest.raises(ValueError):
        store.get_latest_insights(limit=-1)


def test_sandbox_rejects_excess_global_concurrency_and_recovers(monkeypatch):
    entered = threading.Barrier(3)
    release = threading.Event()
    calls = 0
    lock = threading.Lock()

    def child(*args):
        nonlocal calls
        with lock:
            calls += 1
            call = calls
        if call <= 2:
            entered.wait(timeout=5)
            release.wait(timeout=5)
        return 0, b'{"ok":true,"actions":[["hold"]],"params":{}}', "ok"

    monkeypatch.setattr(sandbox, "_run_child", child)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(sandbox.run_strategy, HOLD, [[(1.0, 50.0)]]) for _ in range(2)]
        try:
            entered.wait(timeout=5)
            with pytest.raises(sandbox.StrategyError) as err:
                sandbox.run_strategy(HOLD, [[(1.0, 50.0)]])
            assert err.value.kind == "resource"
            assert calls == 2
        finally:
            release.set()
        assert all(job.result().actions == [["hold"]] for job in jobs)
    assert sandbox.run_strategy(HOLD, [[(1.0, 50.0)]]).actions == [["hold"]]


@pytest.fixture
def tool_functions(monkeypatch, store):
    monkeypatch.setattr(research.global_container, "rate_limiter", FixedWindowRateLimiter())
    monkeypatch.setattr(research.global_container, "insight_store", store)
    mcp = FastMCP("resource-repair-tests")
    research.register_research_tools(mcp)
    register_market_tools(mcp)

    def resolve(name):
        return asyncio.run(mcp.get_tool(name)).fn

    return resolve


def test_backtest_tool_has_session_quota(tool_functions, monkeypatch):
    monkeypatch.setattr(research.global_container.backtest_engine, "run", lambda *args: {"result": "safe"})
    run = tool_functions("run_backtest_simulation")
    results = [json.loads(run(HOLD, "BTC/USDT")) for _ in range(7)]
    assert all(result["ok"] for result in results[:6])
    assert results[-1]["error"]["code"] == "rate_limited"


def test_insight_validation_returns_error_envelope(tool_functions):
    out = json.loads(tool_functions("post_market_insight")("BTC/USDT", "agent", "bullish", 2.0, "Evidence"))
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_insight"


def test_get_latest_insights_returns_invalid_insight_for_whitespace_symbol(tool_functions):
    out = json.loads(tool_functions("get_latest_insights")("   "))
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_insight"
    assert "symbol" in out["error"]["message"]


def test_get_latest_insights_returns_invalid_insight_for_oversized_symbol(tool_functions):
    out = json.loads(tool_functions("get_latest_insights")("B" * 65))
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_insight"
    assert "symbol" in out["error"]["message"]


@pytest.fixture
def source_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if self.path == "/headers":
                    time.sleep(2)
                self.send_response(200)
                if self.path == "/rateheaders":
                    self.send_header("x-ratelimit-reset", "99999999")
                    self.send_header("x-ratelimit-remaining", "1")
                    self.send_header("x-ratelimit-used", "100")
                if self.path == "/length":
                    self.send_header("Content-Length", "10000000")
                self.end_headers()
                if self.path == "/drip":
                    for _ in range(100):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.03)
                elif self.path == "/large":
                    self.wfile.write(b"x" * 10000)
                elif self.path == "/news":
                    self.wfile.write(b'{"status":"ok","articles":[{"title":"BTC grows","source":{"name":"News"}}]}')
                elif self.path == "/twitter":
                    self.wfile.write(b'{"data":[{"id":"123","text":"BTC grows","edit_history_tweet_ids":["123"]}],"meta":{"result_count":1}}')
                elif self.path == "/token":
                    self.wfile.write(b'{"access_token":"fixture-only-token","token_type":"bearer","expires_in":3600,"scope":"*"}')
                elif self.path == "/reddit":
                    listing = {
                        "kind": "Listing",
                        "data": {
                            "after": None,
                            "before": None,
                            "children": [
                                {"kind": "t3", "data": {"id": "abc", "name": "t3_abc", "title": "BTC grows"}},
                            ],
                        },
                    }
                    self.wfile.write(json.dumps(listing).encode())
                else:
                    self.wfile.write(b'{"data":[{"value":"50","value_classification":"Neutral"}]}')
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_POST = do_GET

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("path", ["/length", "/large"])
def test_sources_reject_excess_streamed_and_declared_bytes(source_server, monkeypatch, path):
    monkeypatch.setattr(core, "MAX_SOURCE_BYTES", 1024, raising=False)
    with pytest.raises(core.SourceError):
        core._fetch_bytes(source_server + path)


@pytest.mark.parametrize("path", ["/drip", "/headers"])
def test_sources_enforce_absolute_deadline_even_before_headers(source_server, monkeypatch, path):
    monkeypatch.setattr(core, "MAX_SOURCE_SECONDS", 0.4, raising=False)
    started = time.monotonic()
    with pytest.raises(core.SourceError):
        core._fetch_bytes(source_server + path)
    assert time.monotonic() - started < 1.5


def test_normal_source_still_downloads_and_parses(source_server):
    assert json.loads(core._fetch_bytes(source_server + "/normal"))["data"][0]["value"] == "50"


def test_rss_parser_only_receives_bounded_downloaded_bytes(monkeypatch):
    rss = b"<rss version='2.0'><channel><title>News</title><item><title>BTC grows</title></item></channel></rss>"
    fetched = []
    original_parse = core.feedparser.parse

    def fetch(url):
        fetched.append(url)
        return rss

    def parse(data):
        assert isinstance(data, bytes), "feedparser must never open a network URL"
        return original_parse(data)

    monkeypatch.setattr(core, "_fetch_bytes", fetch, raising=False)
    monkeypatch.setattr(core.feedparser, "parse", parse)
    assert "BTC grows" in core.rss_news()
    assert len(fetched) == 2


def test_sdk_rate_limit_headers_cannot_schedule_unbounded_sleep(source_server, monkeypatch):
    # Headers from a hostile source must not become SDK sleep instructions outside the deadline.
    from requests import Request

    request = Request("GET", source_server + "/rateheaders").prepare()
    with core._BoundedSession() as session:
        response = session.send(request)
    assert "x-ratelimit-reset" not in response.headers
    assert "x-ratelimit-used" not in response.headers
    assert "x-ratelimit-remaining" not in response.headers


def test_database_connections_close_after_operations(store, monkeypatch):
    opened = []
    connect = sqlite3.connect

    def track(*args, **kwargs):
        conn = connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(insights.sqlite3, "connect", track)
    saved = post(store)
    assert store.get_insight(saved.insight_id).insight_id == saved.insight_id
    assert len(store.get_latest_insights()) == 1
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_sandbox_refuses_large_parent_payload_before_conversion(monkeypatch):
    class Point:
        def __float__(self):
            raise AssertionError("over-budget payload must not allocate converted points")

    series = [[(Point(), None)] * 1000] * 501
    with pytest.raises(sandbox.StrategyError) as err:
        sandbox.run_strategy(HOLD, series)
    assert err.value.kind == "too_large"


def test_busy_source_budget_refuses_without_spawning_then_recovers(source_server, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(core, "_SOURCE_SLOTS", slots)
    slots.acquire()
    try:
        started = time.monotonic()
        with pytest.raises(core.SourceError, match="concurrency"):
            core._fetch_bytes(source_server + "/normal")
        assert time.monotonic() - started < 0.2
    finally:
        slots.release()
    assert b"Neutral" in core._fetch_bytes(source_server + "/normal")


def test_source_timeout_kills_workers_and_releases_admission(source_server, monkeypatch):
    processes = []
    popen = core.subprocess.Popen

    def track(*args, **kwargs):
        proc = popen(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(core.subprocess, "Popen", track)
    monkeypatch.setattr(core, "MAX_SOURCE_SECONDS", 0.4)
    for _ in range(2):
        with pytest.raises(core.SourceError):
            core._fetch_bytes(source_server + "/headers")
    assert all(proc.poll() is not None for proc in processes)
    assert b"Neutral" in core._fetch_bytes(source_server + "/normal")


def test_news_tools_share_concurrency_budget_and_recover(tool_functions, monkeypatch):
    entered = threading.Barrier(5)
    release = threading.Event()

    def news(symbol):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        return "BTC grows"

    monkeypatch.setattr(research, "financial_news", news)
    fetch = tool_functions("get_financial_news")
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(fetch, "BTC") for _ in range(4)]
        try:
            entered.wait(timeout=5)
            out = json.loads(fetch("BTC"))
            assert out["error"]["code"] == "resource_busy"
        finally:
            release.set()
        assert all(json.loads(job.result())["ok"] for job in jobs)
    monkeypatch.setattr(research, "financial_news", lambda symbol: "BTC grows")
    assert json.loads(fetch("BTC"))["ok"]


def test_market_news_tool_rate_limit_is_enforced(tool_functions, monkeypatch):
    import intelligence

    monkeypatch.setattr(intelligence, "market_news", lambda: "BTC grows")
    fetch = tool_functions("get_news")
    assert all(json.loads(fetch())["ok"] for _ in range(12))
    assert json.loads(fetch())["error"]["code"] == "rate_limited"


def test_insight_file_growth_is_capped_and_failed_insert_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(insights, "MAX_DATABASE_BYTES", 32768)
    store = insights.InsightStore(str(tmp_path / "bounded.db"))
    written = 0
    with pytest.raises(sqlite3.DatabaseError, match="full"):
        for _ in range(20):
            post(store, reasoning="x" * 8192)
            written += 1
    assert (tmp_path / "bounded.db").stat().st_size <= 32768
    assert len(store.get_latest_insights()) == written


def test_real_news_and_social_sources_use_bounded_transport(monkeypatch, source_server):
    real_send = core._BoundedSession.send

    def local_send(self, request, **kwargs):
        if "newsapi.org" in request.url:
            endpoint = "/news"
        elif urlsplit(request.url).hostname == "api.x.com":
            endpoint = "/twitter"
        elif "access_token" in request.url:
            endpoint = "/token"
        elif "reddit.com" in request.url:
            endpoint = "/reddit"
        else:
            raise AssertionError("unexpected source")
        request.url = source_server + endpoint
        return real_send(self, request, **kwargs)

    monkeypatch.setattr(core._BoundedSession, "send", local_send)
    for key in ("NEWSAPI_KEY", "TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.setenv(key, "fixture-only-key")
    assert "BTC grows (News)" in core.financial_news("BTC")
    assert core._recent_tweets("BTC")[0] == ["BTC grows"]
    assert core._recent_reddit_titles("BTC")[0] == ["BTC grows"]


@pytest.mark.parametrize("name", ["financial_news", "_recent_tweets", "_recent_reddit_titles"])
def test_real_sources_do_not_retry_past_source_deadline(name, monkeypatch, source_server):
    real_send = core._BoundedSession.send

    def local_send(self, request, **kwargs):
        request.url = source_server + "/headers"
        return real_send(self, request, **kwargs)

    monkeypatch.setattr(core._BoundedSession, "send", local_send)
    monkeypatch.setattr(core, "MAX_SOURCE_SECONDS", 0.4)
    for key in ("NEWSAPI_KEY", "TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.setenv(key, "fixture-only-key")
    started = time.monotonic()
    if name == "financial_news":
        with pytest.raises(core.SourceError):
            core.financial_news("BTC")
    else:
        assert getattr(core, name)("BTC")[2] == "error"
    assert time.monotonic() - started < 1.5
