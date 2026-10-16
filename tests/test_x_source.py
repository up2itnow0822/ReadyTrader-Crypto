"""Official X recent search uses bounded HTTP and fails closed on unusable responses."""

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import intelligence.core as core

TOKEN = "x-test-bearer-do-not-echo"
ENDPOINT = "https://api.x.com/2/tweets/search/recent"


@pytest.fixture
def x_http(monkeypatch):
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", TOKEN)
    response = MagicMock(spec=requests.Response)
    response.json.return_value = {"data": [{"text": "BTC is bullish"}], "meta": {"result_count": 1}}
    session = MagicMock(spec=requests.Session)
    session.__enter__.return_value = session
    session.get.return_value = response
    # A stale SDK call must fail locally, never make a real HTTP request.
    session.request.side_effect = AssertionError("X must use the direct bounded GET")
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(core, "_BoundedSession", factory)
    return factory, session, response


def test_recent_search_uses_official_bounded_transport_and_header_auth(x_http):
    factory, session, response = x_http

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == ["BTC is bullish"]
    assert status == "ok"
    assert "Found 1" in notice
    factory.assert_called_once_with()
    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once()
    session.get.assert_called_once_with(
        ENDPOINT,
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"query": "BTC -is:retweet lang:en", "max_results": 10},
    )
    response.raise_for_status.assert_called_once_with()
    response.json.assert_called_once_with()
    prepared = requests.Request("GET", session.get.call_args.args[0], **session.get.call_args.kwargs).prepare()
    assert TOKEN not in prepared.url
    assert "Authorization" not in prepared.url
    assert parse_qs(urlsplit(prepared.url).query) == {"query": ["BTC -is:retweet lang:en"], "max_results": ["10"]}
    assert prepared.headers["Authorization"] == f"Bearer {TOKEN}"


def test_recent_search_returns_at_most_ten_valid_texts(x_http):
    _, _, response = x_http
    texts = [f"BTC market update {index}" for index in range(10)]
    response.json.return_value = {"data": [{"text": text} for text in texts], "meta": {"result_count": 10}}

    actual, notice, status = core._recent_tweets("BTC")

    assert actual == texts
    assert status == "ok"
    assert "Found 10" in notice


@pytest.mark.parametrize(
    "payload",
    [{"meta": {"result_count": 0}}, {"data": [], "meta": {"result_count": 0}}],
    ids=["data-absent", "data-empty"],
)
def test_explicit_zero_results_is_a_successful_empty_source(x_http, payload):
    _, _, response = x_http
    response.json.return_value = payload

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "ok"
    assert "No recent tweets" in notice


def test_blank_text_is_not_a_source_contribution(x_http):
    _, _, response = x_http
    response.json.return_value = {"data": [{"text": ""}, {"text": " \t\n"}, {"text": "BTC is bullish"}], "meta": {"result_count": 3}}

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == ["BTC is bullish"]
    assert status == "ok"
    assert "Found 1" in notice


def test_only_blank_text_is_a_successful_noncontributing_source(x_http):
    _, _, response = x_http
    response.json.return_value = {"data": [{"text": " "}], "meta": {"result_count": 1}}

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "ok"
    assert "No recent tweets" in notice


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "not an object",
        {},
        {"meta": {}},
        {"meta": None},
        {"meta": []},
        {"meta": {"result_count": 1}},
        {"meta": {"result_count": "0"}},
        {"data": []},
        {"data": [], "meta": {"result_count": 1}},
        {"data": None, "meta": {"result_count": 0}},
        {"data": {}, "meta": {"result_count": 0}},
        {"data": "BTC is bullish", "meta": {"result_count": 1}},
        {"data": [None]},
        {"data": ["BTC is bullish"]},
        {"data": [{}]},
        {"data": [{"text": None}]},
        {"data": [{"text": 42}]},
        {"data": [{"text": False}]},
        {"data": [{"text": ["BTC is bullish"]}]},
        {"data": [{"text": "BTC is bullish"}, {"text": None}]},
        {"data": [{"text": str(index)} for index in range(11)], "meta": {"result_count": 11}},
    ],
)
def test_malformed_payload_is_not_an_empty_or_partial_success(x_http, payload):
    _, _, response = x_http
    response.json.return_value = payload

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice in {"Twitter Error: ValueError", "Twitter Error: TypeError"}


@pytest.mark.parametrize("with_data", [False, True], ids=["error-only", "partial-results"])
def test_upstream_errors_reject_even_otherwise_usable_data(x_http, with_data):
    _, _, response = x_http
    payload = {"errors": [{"detail": f"provider-secret {TOKEN} {ENDPOINT}"}], "meta": {"result_count": int(with_data)}}
    if with_data:
        payload["data"] = [{"text": "BTC is bullish"}]
    response.json.return_value = payload

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice == "Twitter Error: ValueError"
    assert TOKEN not in notice
    assert ENDPOINT not in notice
    assert "provider-secret" not in notice


def test_empty_errors_list_does_not_reject_valid_results(x_http):
    _, _, response = x_http
    response.json.return_value["errors"] = []

    texts, _, status = core._recent_tweets("BTC")

    assert texts == ["BTC is bullish"]
    assert status == "ok"


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500, 503])
def test_non_success_status_is_sanitized_and_never_parsed(x_http, status_code):
    _, _, response = x_http
    response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}: {ENDPOINT}?secret={TOKEN}")

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice == "Twitter Error: HTTPError"
    response.json.assert_not_called()


@pytest.mark.parametrize("exception_type", [requests.Timeout, requests.ConnectionError, core.SourceError])
def test_transport_failures_are_sanitized(x_http, exception_type):
    _, session, response = x_http
    message = f"private provider response {TOKEN} {ENDPOINT}"
    failure = core.SourceError("source_unavailable", message) if exception_type is core.SourceError else exception_type(message)
    session.get.side_effect = failure

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice == f"Twitter Error: {exception_type.__name__}"
    response.json.assert_not_called()
    session.__exit__.assert_called_once()


def test_invalid_json_is_sanitized(x_http):
    _, _, response = x_http
    response.json.side_effect = ValueError(f"private response {TOKEN} {ENDPOINT}")

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice == "Twitter Error: ValueError"


def test_context_entry_failures_are_sanitized(x_http):
    _, session, response = x_http
    session.__enter__.side_effect = RuntimeError(f"private transport failure {TOKEN} {ENDPOINT}")

    texts, notice, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "error"
    assert notice == "Twitter Error: RuntimeError"
    session.get.assert_not_called()
    response.json.assert_not_called()


@pytest.mark.parametrize("token", [None, "", " ", "\t\n"])
def test_missing_or_blank_token_is_unconfigured_without_io(monkeypatch, x_http, token):
    factory, session, _ = x_http
    if token is None:
        monkeypatch.delenv("TWITTER_BEARER_TOKEN")
    else:
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", token)

    texts, _, status = core._recent_tweets("BTC")

    assert texts == []
    assert status == "not_configured"
    factory.assert_not_called()
    session.get.assert_not_called()
