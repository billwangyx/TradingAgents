"""Xueqiu (雪球) fetch degrades gracefully on all transport and parse errors.

Covers the fetcher chain:
  - Playwright browser path     -> shared browser_fetch layer
  - XUEQIU_COOKIE env var path  -> uses urllib.request.urlopen directly
  - guest CookieJar path        -> uses a build_opener() session

All network/browser calls are mocked; tests never touch a real cookie or Xueqiu.
"""

from __future__ import annotations

import http.client
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from tradingagents.dataflows import xueqiu


class _Resp:
    """Minimal response context manager; reads ``body`` or raises ``exc``."""

    def __init__(self, body: bytes = b"", exc: Exception | None = None):
        self._body = body
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self._exc is not None:
            raise self._exc
        return self._body


class _FakeOpener:
    """Stand-in for build_opener() result; pops queued responses/exceptions."""

    def __init__(self, items):
        self._items = list(items)

    def open(self, req, timeout=None):
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def manual_cookie(monkeypatch):
    """Force the XUEQIU_COOKIE (manual) path so urlopen is the single seam."""
    monkeypatch.setenv("XUEQIU_COOKIE", "xq_a_token=test123; u=1")


@pytest.fixture(autouse=True)
def _no_ambient_cookie(monkeypatch):
    """Ensure tests don't inherit a real XUEQIU_COOKIE from the environment."""
    monkeypatch.delenv("XUEQIU_COOKIE", raising=False)


@pytest.mark.unit
class TestXueqiuResilience:
    """fetch_xueqiu_posts never raises and always returns a string placeholder."""

    def test_invalid_ticker_returns_not_applicable(self):
        for sym in ("NVDA", "AAPL"):
            out = xueqiu.fetch_xueqiu_posts(sym)
            assert "not applicable" in out.lower()

    def test_playwright_path_valid_response_parsed(self):
        api_response = {
            "data": [
                {
                    "id": 12345,
                    "description": "This is a browser-fetched post",
                    "created_at": 1704067200000,
                    "user": {"screen_name": "browseruser"},
                }
            ]
        }
        with patch.object(xueqiu, "fetch_json_via_browser", return_value=api_response):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "Xueqiu" in out or "雪球" in out
        assert "browseruser" in out or "browser-fetched post" in out

    def test_playwright_path_accepts_xueqiu_list_shape(self):
        api_response = {
            "list": [
                {
                    "id": 67890,
                    "description": "This is the real Xueqiu list response shape",
                    "created_at": 1704067200000,
                    "user": {"screen_name": "listuser"},
                }
            ]
        }
        with patch.object(xueqiu, "fetch_json_via_browser", return_value=api_response):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "Xueqiu" in out or "雪球" in out
        assert "listuser" in out or "list response" in out

    @pytest.mark.parametrize(
        "exc",
        [
            http.client.IncompleteRead(b""),
            HTTPError("url", 503, "down", {}, None),
            TimeoutError("slow"),
            OSError("network unreachable"),
        ],
    )
    def test_manual_path_api_failure_returns_placeholder(self, manual_cookie, exc):
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(xueqiu, "urlopen", side_effect=[_Resp(b"<html></html>"), _Resp(exc=exc)]),
            patch.object(xueqiu, "_fetch_posts_with_jar", return_value=[]),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "no xueqiu posts" in out.lower()

    def test_manual_path_valid_response_parsed(self, manual_cookie):
        api_response = {
            "data": [
                {
                    "id": 12345,
                    "description": "This is a test post about the stock",
                    "created_at": 1704067200000,  # 2024-01-01
                    "user": {"screen_name": "testuser"},
                }
            ]
        }
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(
                xueqiu,
                "urlopen",
                side_effect=[_Resp(b"<html></html>"), _Resp(json.dumps(api_response).encode())],
            ),
            patch.object(xueqiu, "_fetch_posts_with_jar", return_value=[]),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "Xueqiu" in out or "雪球" in out
        assert "testuser" in out or "test post" in out

    def test_manual_path_empty_posts_returns_placeholder(self, manual_cookie):
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(
                xueqiu,
                "urlopen",
                side_effect=[_Resp(b"<html></html>"), _Resp(json.dumps({"data": []}).encode())],
            ),
            patch.object(xueqiu, "_fetch_posts_with_jar", return_value=[]),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "no xueqiu posts" in out.lower()

    def test_manual_path_malformed_json_returns_placeholder(self, manual_cookie):
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(
                xueqiu, "urlopen", side_effect=[_Resp(b"<html></html>"), _Resp(b"not json {{{")]
            ),
            patch.object(xueqiu, "_fetch_posts_with_jar", return_value=[]),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "no xueqiu posts" in out.lower()

    def test_manual_path_waf_response_returns_actionable_placeholder(self, manual_cookie):
        waf = b'<textarea id="renderData">{"_waf_bd8ce2ce37":"challenge"}</textarea>'
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(xueqiu, "urlopen", side_effect=[_Resp(b"<html></html>"), _Resp(waf)]),
            patch.object(xueqiu, "_fetch_posts_with_jar", return_value=[]),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "waf" in out.lower()
        assert "playwright" in out.lower()

    def test_guest_path_no_cookies_returns_placeholder(self):
        """Guest path: homepage returns no cookies (empty jar) -> placeholder."""
        fake = _FakeOpener([_Resp(b"<html></html>")])
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(xueqiu, "build_opener", return_value=fake),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "no xueqiu posts" in out.lower()

    @pytest.mark.parametrize(
        "exc",
        [
            HTTPError("url", 500, "err", {}, None),
            TimeoutError("slow"),
            OSError("unreachable"),
        ],
    )
    def test_guest_path_homepage_failure_returns_placeholder(self, exc):
        fake = _FakeOpener([exc])
        with (
            patch.object(xueqiu, "fetch_json_via_browser", return_value=None),
            patch.object(xueqiu, "build_opener", return_value=fake),
        ):
            out = xueqiu.fetch_xueqiu_posts("0700.HK")
        assert "no xueqiu posts" in out.lower()
