"""Shared browser-backed fetch helpers for JS/WAF-protected data sources.

Some data providers return useful JSON only after a real browser has loaded the
site, executed any JavaScript challenges, and established a same-origin session.
This module centralizes the optional Playwright integration so individual
fetchers can reuse the same cookie parsing and browser lifecycle code while
keeping Playwright out of the core dependency set.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_playwright():
    """Return ``sync_playwright`` when Playwright is installed, else ``None``."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright not installed; browser-backed fetch unavailable")
        return None
    return sync_playwright


def parse_cookie_string(
    cookie_string: str | None,
    *,
    domain: str,
    path: str = "/",
) -> list[dict[str, str]]:
    """Convert a raw ``Cookie`` header string into Playwright cookie dicts."""
    if not cookie_string:
        return []

    cookies: list[dict[str, str]] = []
    for part in cookie_string.split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value.strip(),
                "domain": domain,
                "path": path,
            }
        )
    return cookies


@dataclass
class BrowserSession:
    """Context manager for one short-lived Chromium session."""

    user_agent: str
    cookie_string: str | None = None
    cookie_domain: str = ".xueqiu.com"
    locale: str = "zh-CN"
    headless: bool = True
    timeout: float = 30.0
    channel: str | None = None
    user_data_dir: str | None = None

    def __post_init__(self) -> None:
        self._playwright_cm = None
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self):
        sync_playwright = _get_playwright()
        if sync_playwright is None:
            return None

        self._playwright_cm = sync_playwright()
        self._playwright = self._playwright_cm.__enter__()
        launch_kwargs = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        context_kwargs = {
            "user_agent": self.user_agent,
            "locale": self.locale,
            "timezone_id": "Asia/Shanghai",
            "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        }
        if self.user_data_dir:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(Path(self.user_data_dir)),
                **launch_kwargs,
                **context_kwargs,
            )
        else:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            self._context = self._browser.new_context(**context_kwargs)

        self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        cookies = parse_cookie_string(self.cookie_string, domain=self.cookie_domain)
        if cookies:
            self._context.add_cookies(cookies)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.page.set_default_timeout(int(self.timeout * 1000))
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        for obj in (self._context, self._browser):
            if obj is not None:
                try:
                    obj.close()
                except Exception as close_exc:  # pragma: no cover - defensive cleanup
                    logger.debug("Playwright cleanup failed: %s", close_exc)
        if self._playwright_cm is not None:
            self._playwright_cm.__exit__(exc_type, exc, tb)
        return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def fetch_json_via_browser(
    *,
    page_url: str,
    api_url: str,
    api_url_substring: str,
    cookie_string: str | None,
    cookie_domain: str,
    user_agent: str,
    timeout: float = 30.0,
    headless: bool | None = None,
    response_filter: Callable[[Any], bool] | None = None,
) -> dict | None:
    """Load ``page_url`` in Chromium, then retrieve ``api_url`` in that page.

    The page load lets the browser execute WAF JavaScript and establish any
    challenge/session cookies. We first listen for a matching network response;
    if the page does not naturally request the API, we issue a same-origin
    ``fetch`` from inside the browser context.
    """
    sync_playwright = _get_playwright()
    if sync_playwright is None:
        return None

    browser_headless = (
        _env_bool("XUEQIU_BROWSER_HEADLESS", True) if headless is None else headless
    )
    browser_timeout = float(os.getenv("XUEQIU_BROWSER_TIMEOUT", timeout))
    browser_channel = os.getenv("XUEQIU_BROWSER_CHANNEL", "").strip() or None
    user_data_dir = os.getenv("XUEQIU_BROWSER_USER_DATA_DIR", "").strip() or None

    try:
        with BrowserSession(
            user_agent=user_agent,
            cookie_string=cookie_string,
            cookie_domain=cookie_domain,
            headless=browser_headless,
            timeout=browser_timeout,
            channel=browser_channel,
            user_data_dir=user_data_dir,
        ) as session:
            if session is None or session.page is None:
                return None
            page = session.page
            captured: list[dict] = []

            def on_response(response) -> None:
                try:
                    if api_url_substring not in response.url or response.status != 200:
                        return
                    if response_filter is not None and not response_filter(response):
                        return
                    captured.append(response.json())
                except Exception as exc:
                    logger.debug("Browser response parse failed for %s: %s", response.url, exc)

            page.on("response", on_response)
            # WAF/analytics-heavy pages often keep long-polling requests open,
            # so ``networkidle`` can time out even when the page is usable.
            page.goto(page_url, wait_until="domcontentloaded", timeout=int(browser_timeout * 1000))
            page.wait_for_timeout(int(float(os.getenv("XUEQIU_BROWSER_SETTLE_MS", "3000"))))
            if captured:
                return captured[0]

            result = page.evaluate(
                """async (url) => {
                    const response = await fetch(url, {
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json, text/plain, */*',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });
                    const text = await response.text();
                    return {
                        status: response.status,
                        contentType: response.headers.get('content-type') || '',
                        text
                    };
                }""",
                api_url,
            )
            text = result.get("text", "") if isinstance(result, dict) else ""
            if not text.lstrip().startswith("{"):
                logger.warning("Browser fetch returned non-JSON response for %s", api_url)
                return None

            import json

            return json.loads(text)
    except Exception as exc:
        logger.warning("Browser-backed fetch failed for %s: %s", page_url, exc)
        return None
