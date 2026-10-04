"""yfinance-based news data fetching functions."""

import contextlib
import http.client
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yfinance as yf
from dateutil.relativedelta import relativedelta

from .config import get_config
from .stockstats_utils import yf_retry
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

# Yahoo Finance headline RSS. Used only after Ticker.get_news comes back empty.
# A .HK symbol uses the HK feed; every other symbol uses the US feed.
# Not Google News, and not the Eastmoney search API.
_YAHOO_HEADLINE_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_RSS_UA = "tradingagents-research/1.0"
_RSS_TIMEOUT = 10.0


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure. Parse the epoch publish time so flat
        # articles are date-filterable too (otherwise they bypass the
        # historical window and leak future news, #992/#1007).
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts)
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": pub_date,
        }


def yahoo_headline_rss_url(symbol: str) -> str:
    """Yahoo headline RSS for ``symbol``. ``.HK`` selects the HK feed."""
    ticker = (symbol or "").strip().upper()
    if ticker.endswith(".HK"):
        region, lang = "HK", "zh-Hant"
    else:
        region, lang = "US", "en-US"
    query = urlencode({"s": ticker, "region": region, "lang": lang})
    return f"{_YAHOO_HEADLINE_RSS}?{query}"


def _parse_yahoo_rss(payload: bytes) -> list[dict]:
    """Turn a Yahoo headline RSS document into the article dicts the formatter uses."""
    root = ET.fromstring(payload)
    items: list[dict] = []
    for node in root.iter():
        if _xml_local(node.tag) != "item":
            continue
        fields = {_xml_local(child.tag): child for child in list(node)}
        title = _xml_text(fields.get("title"))
        if not title:
            continue
        pub_date = None
        pub_raw = _xml_text(fields.get("pubDate"))
        if pub_raw:
            with contextlib.suppress(ValueError, TypeError, IndexError):
                pub_date = parsedate_to_datetime(pub_raw)
        source = _xml_text(fields.get("source"))
        items.append({
            "title": title,
            "summary": _xml_text(fields.get("description")),
            "publisher": source or "Yahoo Finance",
            "link": _xml_text(fields.get("link")),
            "pub_date": pub_date,
        })
    return items


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _xml_text(node) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _fetch_yahoo_headline_rss(symbol: str) -> list[dict]:
    """Read Yahoo headline RSS. Failures are an empty list, not invented headlines."""
    url = yahoo_headline_rss_url(symbol)
    req = Request(url, headers={"User-Agent": _RSS_UA})
    try:
        with urlopen(req, timeout=_RSS_TIMEOUT) as resp:
            payload = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        logger.warning("Yahoo headline RSS failed for %s: %s", symbol, exc)
        return []
    try:
        return _parse_yahoo_rss(payload)
    except ET.ParseError as exc:
        logger.warning("Yahoo headline RSS parse failed for %s: %s", symbol, exc)
        return []


def _render_windowed_news(
    ticker: str,
    resolved: str,
    start_date: str,
    end_date: str,
    start_dt: datetime,
    end_dt: datetime,
    items: list[dict],
) -> str | None:
    """Existing ticker-news markdown, or None when nothing falls in the window."""
    news_str = ""
    filtered_count = 0
    for data in items:
        if not _in_news_window(data.get("pub_date"), start_dt, end_dt):
            continue
        news_str += f"### {data.get('title') or 'No title'} (source: {data.get('publisher') or 'Unknown'})\n"
        if data.get("summary"):
            news_str += f"{data['summary']}\n"
        if data.get("link"):
            news_str += f"Link: {data['link']}\n"
        news_str += "\n"
        filtered_count += 1
    if filtered_count == 0:
        return None
    return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_str}"


def _in_news_window(pub_date, start_dt, end_dt) -> bool:
    """Whether an article belongs in the [start_dt, end_dt] window.

    Dated articles are kept only if they fall in the window. An undated article
    is kept only when the window reaches the present (live run) — in a
    historical/backtest window it's excluded, since we can't prove it isn't
    future news (look-ahead safety, #992/#1007).
    """
    if pub_date is not None:
        naive = pub_date.replace(tzinfo=None) if hasattr(pub_date, "replace") else pub_date
        return start_dt <= naive <= end_dt + relativedelta(days=1)
    return end_dt >= datetime.now() - relativedelta(days=1)


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    # Query Yahoo with the canonical symbol, like every other yfinance path —
    # a raw broker/forex/crypto alias (XAUUSD, BTCUSD) otherwise silently
    # returns no news. Keep the user's ticker in the report header.
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = yf.Ticker(canonical)
        news = yf_retry(lambda: stock.get_news(count=article_limit))
    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"

    # Parse date range for filtering
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    extracted = [_extract_article_data(article) for article in (news or [])]
    rendered = _render_windowed_news(
        ticker, resolved, start_date, end_date, start_dt, end_dt, extracted
    )
    if rendered:
        return rendered

    # Ticker.get_news was empty, or nothing in it fell inside the window.
    # Read Yahoo's own headline RSS before this vendor counts as a miss.
    rss_items = _fetch_yahoo_headline_rss(canonical)[:article_limit]
    rendered = _render_windowed_news(
        ticker, resolved, start_date, end_date, start_dt, end_dt, rss_items
    )
    if rendered:
        return rendered

    if not news:
        return f"No news found for {ticker}{resolved}"
    return f"No news found for {ticker}{resolved} between {start_date} and {end_date}"


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    all_news = []
    seen_titles = set()

    try:
        for query in search_queries:
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))

            if search.news:
                for article in search.news:
                    # Handle both flat and nested structures
                    if "content" in article:
                        data = _extract_article_data(article)
                        title = data["title"]
                    else:
                        title = article.get("title", "")

                    # Deduplicate by title
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(article)

            if len(all_news) >= limit:
                break

        if not all_news:
            return f"No global news found for {curr_date}"

        # Calculate date range
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        news_str = ""
        kept = 0
        for article in all_news[:limit]:
            # Extract uniformly (flat + nested) and apply the same look-ahead-safe
            # window filter, so flat articles can't leak future news (#1007).
            data = _extract_article_data(article)
            if not _in_news_window(data["pub_date"], start_dt, curr_dt):
                continue
            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            kept += 1

        # All candidates fell outside the window -> say so rather than return an
        # empty-bodied report (#993).
        if kept == 0:
            return f"No global news found between {start_date} and {curr_date}"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching global news: {str(e)}"
