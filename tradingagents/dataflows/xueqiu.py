"""Xueqiu (雪球) social discussion fetcher for Chinese/HK equities.

Xueqiu is a major Chinese investment community with active discussions on
Hong Kong and mainland China stocks. This module fetches recent posts from
the Xueqiu platform.

Fetch strategy, in priority order:
  1. Optional Playwright browser flow — opens the symbol page in Chromium so
     Xueqiu's Aliyun WAF JavaScript challenge can run, then fetches the API from
     that browser context.
  2. ``XUEQIU_COOKIE`` env var with urllib — a cookie string copied from a
     logged-in browser session.
  3. Guest CookieJar flow — visits the homepage to collect guest cookies, then
     reuses them for the API call.

Follows the same pattern as stocktwits.py and reddit.py:
- Graceful degradation on any HTTP or parse failure
- Returns a formatted plaintext block ready for prompt injection
- Never raises; returns placeholder string on any error
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from .browser_fetch import fetch_json_via_browser
from .symbol_utils import to_xueqiu_symbol

logger = logging.getLogger(__name__)

# Xueqiu API endpoints
_XUEQIU_HOST = "https://xueqiu.com"
_XUEQIU_SEARCH_API = "https://xueqiu.com/query/v1/symbol/search/status.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

_HOME_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_LAST_FAILURE = ""


def _get_manual_cookie() -> str | None:
    """Return a user-supplied cookie string from ``XUEQIU_COOKIE``, or None."""
    raw = os.getenv("XUEQIU_COOKIE", "").strip()
    return raw or None


def _build_api_url(xq_symbol: str, limit: int) -> str:
    """Build the Xueqiu search/status API URL for a symbol."""
    params = {
        "symbol": xq_symbol,
        "count": str(limit),
        "source": "all",
        "sort": "time",
        "page": "1",
    }
    return f"{_XUEQIU_SEARCH_API}?{urlencode(params)}"


def _api_request(api_url: str, xq_symbol: str, cookie: str | None = None) -> Request:
    """Build the API Request, optionally with an explicit Cookie header."""
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": _XUEQIU_HOST,
        "Referer": f"{_XUEQIU_HOST}/S/{xq_symbol}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "X-Requested-With": "XMLHttpRequest",
    }
    if cookie:
        headers["Cookie"] = cookie
    return Request(api_url, headers=headers)


def _page_request(xq_symbol: str, cookie: str | None = None) -> Request:
    """Build the warm-up symbol-page request used by urllib fallbacks."""
    headers = dict(_HOME_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    return Request(f"{_XUEQIU_HOST}/S/{xq_symbol}", headers=headers)


def _is_waf_response(text: str) -> bool:
    """Return True when Xueqiu returned an Aliyun WAF challenge page."""
    lowered = text.lower()
    return "_waf_" in lowered or "aliyun_waf" in lowered or "acw_sc__v2" in lowered


def _loads_json_response(body: bytes, xq_symbol: str, path: str) -> object | None:
    """Decode a response body, detecting WAF pages before JSON parsing."""
    global _LAST_FAILURE
    text = body.decode("utf-8", "replace")
    if _is_waf_response(text):
        _LAST_FAILURE = "waf"
        logger.warning("Xueqiu %s blocked by Aliyun WAF for %s", path, xq_symbol)
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.debug("Xueqiu %s returned non-JSON for %s: %s", path, xq_symbol, exc)
        return None


def _extract_posts(data: object) -> list[dict]:
    """Pull the list of post dicts out of the API response payload."""
    if not isinstance(data, dict):
        return []
    posts = data.get("data")
    if posts is None:
        posts = data.get("list", [])
    if not isinstance(posts, list):
        return []
    return posts


def _fetch_posts_with_playwright(
    xq_symbol: str,
    limit: int = 20,
    timeout: float = 30.0,
    cookie: str | None = None,
) -> list[dict]:
    """Fetch posts through the shared Playwright browser layer."""
    data = fetch_json_via_browser(
        page_url=f"{_XUEQIU_HOST}/S/{xq_symbol}",
        api_url=_build_api_url(xq_symbol, limit),
        api_url_substring="search/status.json",
        cookie_string=cookie,
        cookie_domain=".xueqiu.com",
        user_agent=_UA,
        timeout=timeout,
    )
    return _extract_posts(data)


def _fetch_posts_with_cookie(
    xq_symbol: str, limit: int, cookie: str, timeout: float
) -> list[dict]:
    """Fetch posts using an explicit Cookie header (XUEQIU_COOKIE path)."""
    # Warm the symbol page first so browser-copied WAF cookies get a chance to
    # match the same navigation sequence a real browser performs.
    try:
        with urlopen(_page_request(xq_symbol, cookie=cookie), timeout=timeout) as resp:
            resp.read()
    except (OSError, HTTPError, http.client.HTTPException) as exc:
        logger.debug("Xueqiu page warm-up failed for %s: %s", xq_symbol, exc)

    req = _api_request(_build_api_url(xq_symbol, limit), xq_symbol, cookie=cookie)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = _loads_json_response(resp.read(), xq_symbol, "API fetch")
    except (OSError, HTTPError, http.client.HTTPException) as exc:
        logger.debug("Xueqiu API fetch (manual cookie) failed for %s: %s", xq_symbol, exc)
        return []
    return _extract_posts(data)


def _fetch_posts_with_jar(xq_symbol: str, limit: int, timeout: float) -> list[dict]:
    """Fetch posts via the guest CookieJar flow.

    Visits the homepage to collect guest cookies, then reuses the same opener
    (cookies auto-sent) for the API call. CookieJar correctly captures every
    Set-Cookie header, unlike the old dict()-based parsing.
    """
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    # Step 1: prime guest cookies from the homepage.
    try:
        with opener.open(Request(_XUEQIU_HOST, headers=_HOME_HEADERS), timeout=timeout) as resp:
            resp.read()
    except (OSError, HTTPError, http.client.HTTPException) as exc:
        logger.debug("Xueqiu homepage fetch failed: %s", exc)
        return []

    if not list(jar):
        logger.debug("Xueqiu homepage returned no cookies")
        return []

    # Step 2: call the API with the same opener (jar cookies auto-applied).
    try:
        with opener.open(
            _api_request(_build_api_url(xq_symbol, limit), xq_symbol), timeout=timeout
        ) as resp:
            data = _loads_json_response(resp.read(), xq_symbol, "guest API fetch")
    except (OSError, HTTPError, http.client.HTTPException) as exc:
        logger.debug("Xueqiu API fetch (guest) failed for %s: %s", xq_symbol, exc)
        return []
    return _extract_posts(data)


def _format_timestamp(ts: int | None) -> str:
    """Format Xueqiu timestamp (ms since epoch) to readable string."""
    if not ts:
        return "unknown"
    from datetime import datetime
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return "unknown"


def _format_post(post: dict) -> str:
    """Format a single Xueqiu post to plaintext line."""
    user = post.get("user", {}) or {}
    username = user.get("screen_name", "?") if isinstance(user, dict) else "?"
    desc = post.get("description", "") or ""
    # Clean HTML tags and normalize whitespace
    desc = re.sub(r"<[^>]+>", " ", desc).replace("&nbsp;", " ")
    desc = " ".join(desc.split())  # normalize whitespace
    if len(desc) > 200:
        desc = desc[:200] + "..."
    ts = _format_timestamp(post.get("created_at"))
    # Optional sentiment indicators in text (common patterns in Chinese discussion)
    sentiment_tags = []
    desc_lower = desc.lower()
    if any(kw in desc_lower for kw in ["看涨", "买入", "加仓", "突破", "利好", "牛", "涨"]):
        sentiment_tags.append("Bullish")
    if any(kw in desc_lower for kw in ["看跌", "卖出", "减仓", "暴跌", "利空", "熊", "跌"]):
        sentiment_tags.append("Bearish")
    tag_str = f" · {', '.join(sentiment_tags)}" if sentiment_tags else ""
    return f"[{ts} · @{username}{tag_str}] {desc}"


def fetch_xueqiu_posts(ticker: str, limit: int = 20, timeout: float = 10.0) -> str:
    """Fetch recent Xueqiu (雪球) discussion posts for ``ticker``.

    Automatically converts broker ticker (e.g., "0700.HK") to Xueqiu symbol
    format ("HK00700"). Uses ``XUEQIU_COOKIE`` env var when set (most reliable,
    bypasses anti-bot), otherwise falls back to the anonymous guest cookie flow.

    Degrades gracefully on any failure — network errors, unexpected response
    formats, missing cookies, or invalid tickers — returning a placeholder
    string rather than raising exceptions.

    Args:
        ticker: Broker-style ticker (e.g., "0700.HK", "600519.SS", "AAPL")
        limit: Maximum number of posts to fetch (default 20)
        timeout: HTTP request timeout in seconds

    Returns:
        Formatted plaintext block of recent Xueqiu posts, or a placeholder
        string explaining why data is unavailable.
    """
    xq_symbol = to_xueqiu_symbol(ticker)
    if xq_symbol is None:
        return f"<Xueqiu not applicable for {ticker}: not a Chinese/HK market symbol>"

    global _LAST_FAILURE
    _LAST_FAILURE = ""

    manual_cookie = _get_manual_cookie()
    posts = _fetch_posts_with_playwright(
        xq_symbol, limit=limit, timeout=max(timeout, 30.0), cookie=manual_cookie
    )
    if not posts and manual_cookie:
        posts = _fetch_posts_with_cookie(xq_symbol, limit, manual_cookie, timeout)
    if not posts:
        posts = _fetch_posts_with_jar(xq_symbol, limit, timeout)

    if not posts:
        if _LAST_FAILURE == "waf":
            return (
                f"<Xueqiu blocked by WAF for {ticker} ({xq_symbol}); "
                "install Playwright with `pip install -e \".[browser]\"` and "
                "`playwright install chromium`, or refresh XUEQIU_COOKIE>"
            )
        return (
            f"<no Xueqiu posts found for {ticker} ({xq_symbol}); "
            "set XUEQIU_COOKIE in .env or enable Playwright browser fetching if this persists>"
        )

    lines = [_format_post(p) for p in posts[:limit] if isinstance(p, dict)]
    total = len(lines)

    summary = f"Xueqiu (雪球) discussion posts for {ticker} ({xq_symbol}) · {total} recent posts"
    return f"{summary}\n\n" + "\n".join(lines)
