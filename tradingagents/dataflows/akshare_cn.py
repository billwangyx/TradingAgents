"""AKShare-based Chinese financial data fetcher for Eastmoney news.

This module provides access to Eastmoney (东方财富) Chinese financial news
through the AKShare library. It uses lazy importing so AKShare remains an
optional dependency — if not installed, the fetcher degrades gracefully.

Data sources:
    - stock_news_em: Individual stock news from Eastmoney
      (supports A-shares and HK stocks like "00700")

Follows the same patterns as other dataflows modules:
    - Graceful degradation on import errors or network failures
    - Returns formatted plaintext blocks ready for prompt injection
    - No exceptions raised; placeholder strings on any error
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .symbol_utils import to_eastmoney_code

logger = logging.getLogger(__name__)

# Lazy import handle for akshare
_akshare = None


def _get_akshare():
    """Lazy importer for akshare — returns module or None if unavailable."""
    global _akshare
    if _akshare is None:
        try:
            import akshare as ak
            _akshare = ak
        except ImportError:
            logger.debug("AKShare not installed; Chinese news sources unavailable")
            _akshare = False  # Mark as unavailable
    return _akshare if _akshare is not False else None


def _clean_html(text: str) -> str:
    """Remove common HTML tags and entities from news content."""
    import re
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Replace common entities
    replacements = {
        "&nbsp;": " ",
        "&quot;": '"',
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Normalize whitespace
    return " ".join(text.split())


def fetch_eastmoney_news(ticker: str, limit: int = 20) -> str:
    """Fetch Eastmoney (东方财富) Chinese news for ``ticker``.

    Uses AKShare's stock_news_em interface to retrieve recent news articles
    about the specified stock. Supports Hong Kong stocks (e.g., "0700.HK" ->
    "00700") and mainland A-shares.

    This function degrades gracefully:
        - If AKShare is not installed, returns placeholder
        - If the ticker is not a Chinese/HK market symbol, returns placeholder
        - On any network/parsing error, returns placeholder

    Args:
        ticker: Broker-style ticker (e.g., "0700.HK", "600519.SS", "AAPL")
        limit: Maximum number of news articles to return (default 20)

    Returns:
        Formatted plaintext block of Chinese news articles, or a placeholder
        string explaining why data is unavailable.
    """
    # Check AKShare availability
    ak = _get_akshare()
    if ak is None:
        return f"<Eastmoney news unavailable: AKShare library not installed (pip install akshare)>"

    # Convert ticker to Eastmoney code format
    em_code = to_eastmoney_code(ticker)
    if em_code is None:
        return f"<Eastmoney news not applicable for {ticker}: not a Chinese/HK market symbol>"

    # Fetch news
    try:
        df = ak.stock_news_em(symbol=em_code)
    except Exception as exc:
        logger.debug("AKShare stock_news_em failed for %s: %s", em_code, exc)
        return f"<Eastmoney news fetch failed for {ticker} ({em_code}): {type(exc).__name__}>"

    if df is None or df.empty:
        return f"<no Eastmoney news found for {ticker} ({em_code})>"

    # Format output (limit rows)
    df = df.head(limit)

    lines = []
    for _, row in df.iterrows():
        # AKShare column names (Chinese):
        # 关键词, 新闻标题, 新闻内容, 发布时间, 文章来源, 新闻链接
        title = _clean_html(str(row.get("新闻标题", "")))
        content = _clean_html(str(row.get("新闻内容", "")))
        time_str = str(row.get("发布时间", ""))
        source = str(row.get("文章来源", ""))
        url = str(row.get("新闻链接", ""))

        # Truncate content for brevity
        if len(content) > 300:
            content = content[:300] + "..."

        line = f"[{time_str} · {source}] {title}\n  {content}\n  {url}"
        lines.append(line)

    summary = f"Eastmoney (东方财富) Chinese news for {ticker} ({em_code}) · {len(lines)} articles"
    return f"{summary}\n\n" + "\n\n".join(lines)


def fetch_eastmoney_comment(ticker: str, limit: int = 20) -> str:
    """Fetch Eastmoney Guba (股吧) comments for ``ticker``.

    Uses AKShare's stock_comment_em to retrieve recent investor comments
    from Eastmoney's stock discussion forum (股吧). Provides retail
    sentiment signal for Chinese stocks.

    Args:
        ticker: Broker-style ticker (e.g., "000001.SZ", "600519.SS")
        limit: Maximum number of comments to return

    Returns:
        Formatted plaintext block of forum comments, or placeholder.
    """
    ak = _get_akshare()
    if ak is None:
        return f"<Eastmoney comments unavailable: AKShare library not installed>"

    em_code = to_eastmoney_code(ticker)
    if em_code is None:
        return f"<Eastmoney comments not applicable for {ticker}: not a Chinese market symbol>"

    try:
        df = ak.stock_comment_em(symbol=em_code)
    except Exception as exc:
        logger.debug("AKShare stock_comment_em failed for %s: %s", em_code, exc)
        return f"<Eastmoney comments fetch failed for {ticker}: {type(exc).__name__}>"

    if df is None or df.empty:
        return f"<no Eastmoney comments found for {ticker}>"

    df = df.head(limit)

    lines = []
    for _, row in df.iterrows():
        # AKShare column names vary; handle common ones
        content = _clean_html(str(row.get("评论内容", row.get("内容", ""))))
        time_str = str(row.get("发布时间", row.get("时间", "")))
        user = str(row.get("用户", row.get("用户名", "?")))

        if len(content) > 200:
            content = content[:200] + "..."

        lines.append(f"[{time_str} · @{user}] {content}")

    summary = f"Eastmoney Guba (股吧) comments for {ticker} · {len(lines)} comments"
    return f"{summary}\n\n" + "\n".join(lines)
