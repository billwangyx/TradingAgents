"""Tests for shared Playwright browser-fetch helpers."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tradingagents.dataflows import browser_fetch


class _Response:
    url = "https://xueqiu.com/query/v1/symbol/search/status.json"
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Page:
    def __init__(self, response_payload=None, evaluate_payload=None):
        self._handler = None
        self._response_payload = response_payload
        self._evaluate_payload = evaluate_payload

    def on(self, event, handler):
        assert event == "response"
        self._handler = handler

    def goto(self, page_url, wait_until=None, timeout=None):
        if self._handler is not None and self._response_payload is not None:
            self._handler(_Response(self._response_payload))

    def wait_for_timeout(self, timeout):
        return None

    def evaluate(self, script, api_url):
        return {"status": 200, "contentType": "application/json", "text": json.dumps(self._evaluate_payload)}


class _Session:
    def __init__(self, *args, page=None, **kwargs):
        self.page = page or _Page(evaluate_payload={"data": []})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.unit
class TestBrowserFetch:
    def test_parse_cookie_string_preserves_values_with_equals(self):
        cookies = browser_fetch.parse_cookie_string(
            "xq_a_token=abc; xq_id_token=header.payload==; u=7545",
            domain=".xueqiu.com",
        )
        assert cookies == [
            {"name": "xq_a_token", "value": "abc", "domain": ".xueqiu.com", "path": "/"},
            {
                "name": "xq_id_token",
                "value": "header.payload==",
                "domain": ".xueqiu.com",
                "path": "/",
            },
            {"name": "u", "value": "7545", "domain": ".xueqiu.com", "path": "/"},
        ]

    def test_parse_cookie_string_ignores_empty_and_malformed_parts(self):
        cookies = browser_fetch.parse_cookie_string(" ; noequals ; a=1; =bad", domain=".xueqiu.com")
        assert cookies == [{"name": "a", "value": "1", "domain": ".xueqiu.com", "path": "/"}]

    def test_fetch_json_uses_captured_response(self):
        page = _Page(response_payload={"data": [{"id": 1}]}, evaluate_payload={"data": []})
        with (
            patch.object(browser_fetch, "_get_playwright", return_value=object()),
            patch.object(browser_fetch, "BrowserSession", return_value=_Session(page=page)),
        ):
            out = browser_fetch.fetch_json_via_browser(
                page_url="https://xueqiu.com/S/HK00700",
                api_url="https://xueqiu.com/query/v1/symbol/search/status.json",
                api_url_substring="search/status.json",
                cookie_string="xq_a_token=abc",
                cookie_domain=".xueqiu.com",
                user_agent="UA",
            )
        assert out == {"data": [{"id": 1}]}

    def test_fetch_json_falls_back_to_browser_context_fetch(self):
        page = _Page(response_payload=None, evaluate_payload={"data": [{"id": 2}]})
        with (
            patch.object(browser_fetch, "_get_playwright", return_value=object()),
            patch.object(browser_fetch, "BrowserSession", return_value=_Session(page=page)),
        ):
            out = browser_fetch.fetch_json_via_browser(
                page_url="https://xueqiu.com/S/HK00700",
                api_url="https://xueqiu.com/query/v1/symbol/search/status.json",
                api_url_substring="search/status.json",
                cookie_string=None,
                cookie_domain=".xueqiu.com",
                user_agent="UA",
            )
        assert out == {"data": [{"id": 2}]}

    def test_fetch_json_returns_none_when_playwright_missing(self):
        with patch.object(browser_fetch, "_get_playwright", return_value=None):
            out = browser_fetch.fetch_json_via_browser(
                page_url="https://xueqiu.com/S/HK00700",
                api_url="https://xueqiu.com/query/v1/symbol/search/status.json",
                api_url_substring="search/status.json",
                cookie_string=None,
                cookie_domain=".xueqiu.com",
                user_agent="UA",
            )
        assert out is None
