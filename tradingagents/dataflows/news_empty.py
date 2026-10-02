"""Ticker-news emptiness.

Yahoo often returns the sentence "No news found" instead of raising. That
string is not an article. Callers treat it as a miss so the next configured
vendor can run. Only after the chain is exhausted do we emit ``NEWS_EMPTY``.

The marker is a flag, not a headline. Nothing in this module invents a story.
"""

from __future__ import annotations

import json

# Default ticker-news order. ``default_config`` keeps the same sequence:
# Yahoo, then Alpha Vantage, then Eastmoney via akshare (CN/HK only).
NEWS_VENDOR_ORDER: tuple[str, ...] = ("yfinance", "alpha_vantage", "akshare")

NEWS_EMPTY_PREFIX = "NEWS_EMPTY:"

# Phrases that mean "this vendor has no article", not "here is the article".
_EMPTY_MARKERS = (
    "no news found",
    "error fetching news",
    "error fetching global news",
    "eastmoney news not applicable",
    "eastmoney news unavailable",
    "eastmoney news fetch failed",
    "no eastmoney news",
    "not a chinese/hk market symbol",
    "akshare library not installed",
)


def news_vendor_chain() -> str:
    """Comma-separated vendor chain matching ``NEWS_VENDOR_ORDER``."""
    return ",".join(NEWS_VENDOR_ORDER)


def format_news_empty(ticker: str, vendors: list[str] | tuple[str, ...]) -> str:
    """One line the graph can flag. It does not contain a fabricated headline."""
    chain = ", ".join(vendors) if vendors else "none"
    symbol = ticker or "the requested ticker"
    return (
        f"{NEWS_EMPTY_PREFIX} No news found for {symbol} after trying {chain}. "
        "Do not invent headlines."
    )


def news_payload_is_empty(payload) -> bool:
    """True when a vendor result has no usable article.

    A formatted Yahoo/Eastmoney hit starts with a markdown heading or a feed
    of articles. Placeholders, errors, and Alpha Vantage ``"feed": []`` do not.
    """
    if payload is None:
        return True
    if isinstance(payload, dict):
        if "feed" in payload:
            feed = payload.get("feed")
            return not isinstance(feed, list) or len(feed) == 0
        return False
    if not isinstance(payload, str):
        payload = str(payload)
    text = payload.strip()
    if not text:
        return True
    if text.startswith(NEWS_EMPTY_PREFIX):
        return True
    if text[0] in "{[":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and "feed" in parsed:
            return news_payload_is_empty(parsed)
    low = text.lower()
    has_article = text.startswith("## ") or "\n### " in text or text.startswith("### ")
    return any(marker in low for marker in _EMPTY_MARKERS) and not has_article


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                chunks.append(str(block.get("text") or ""))
        return "\n".join(chunks)
    return str(content or "")


def detect_news_empty(messages, report: str = "") -> bool:
    """True when ticker ``get_news`` results are empty or already ``NEWS_EMPTY``.

    A later non-empty ``get_news`` result clears the flag. Global news and
    other tools do not, by themselves, set it.
    """
    saw_ticker_news = False
    for message in messages or []:
        name = getattr(message, "name", None)
        text = _message_text(message)
        if name != "get_news" and not text.startswith(NEWS_EMPTY_PREFIX):
            continue
        if name == "get_news":
            saw_ticker_news = True
            if not news_payload_is_empty(text):
                return False
        else:
            saw_ticker_news = True
    if saw_ticker_news:
        return True
    return isinstance(report, str) and report.strip().startswith(NEWS_EMPTY_PREFIX)
