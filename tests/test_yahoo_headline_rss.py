"""Yahoo headline RSS fills an empty yfinance get_news result.

Recorded from feeds.finance.yahoo.com headline RSS. AAPL is the US feed
(English titles). 1318.HK is the HK feed (Chinese titles). Neither path calls
format_news_empty. Google News and the Eastmoney search API are not used.
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.dataflows.yfinance_news as ynews
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_empty import NEWS_VENDOR_ORDER, format_news_empty

_AAPL_RSS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0">
  <channel>
    <title>Yahoo! Finance: AAPL News</title>
    <item>
      <title>How Supreme Court Battles Involving Apple, Exxon, and Intel Could Hit Your Portfolio</title>
      <link>https://finance.yahoo.com/m/73cd22ed-bdb4-3144-b852-c95810d02024/how-supreme-court-battles.html</link>
      <pubDate>Sun, 04 Oct 2026 06:00:00 +0000</pubDate>
      <description>The court will begin hearing oral arguments on Monday.</description>
    </item>
    <item>
      <title>Dear Apple Stock Fans, Mark Your Calendars for October 13</title>
      <link>https://www.barchart.com/story/news/4945438/dear-apple-stock-fans</link>
      <pubDate>Sat, 03 Oct 2026 18:30:02 +0000</pubDate>
      <description>Apple is preparing a notable smart-home expansion for Oct. 13.</description>
    </item>
  </channel>
</rss>
"""

_HK_RSS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0">
  <channel>
    <title>Yahoo! Finance: 1318.HK News</title>
    <item>
      <title>毛戈平(01318)中期純利8.05億元人民幣升20.26% 派息62分</title>
      <link>https://hk.finance.yahoo.com/news/maogeping-interim</link>
      <pubDate>Thu, 27 Aug 2026 23:18:11 +0000</pubDate>
      <description>毛戈平化妝品股份有限公司公布中期業績。</description>
    </item>
    <item>
      <title>招商證券大削毛戈平化妝品(01318)目標價50% 維持「增持」</title>
      <link>https://hk.finance.yahoo.com/news/cms-maogeping</link>
      <pubDate>Tue, 01 Sep 2026 03:20:54 +0000</pubDate>
      <description>招商證券國際維持「增持」評級。</description>
    </item>
  </channel>
</rss>
"""

_US_URL = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US"
)
_HK_URL = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=1318.HK&region=HK&lang=zh-Hant"
)


class _Resp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _empty_ticker():
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def get_news(self, count):
            return []

    return FakeTicker


def _urlopen_for(body: str, seen: dict):
    def _open(req, timeout=10):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return _Resp(body)

    return _open


@pytest.mark.unit
def test_rss_url_uses_yahoo_us_or_hk_feed_only():
    assert ynews.yahoo_headline_rss_url("AAPL") == _US_URL
    assert ynews.yahoo_headline_rss_url("aapl") == _US_URL
    assert ynews.yahoo_headline_rss_url("1318.HK") == _HK_URL
    assert ynews.yahoo_headline_rss_url("1318.hk") == _HK_URL
    text = Path(ynews.__file__).read_text(encoding="utf-8")
    assert "news.google.com" not in text
    assert "search-api-web.eastmoney.com" not in text
    assert NEWS_VENDOR_ORDER == ("yfinance", "alpha_vantage", "akshare")
    assert default_config.DEFAULT_CONFIG["data_vendors"]["news_data"] == (
        "yfinance,alpha_vantage,akshare"
    )


@pytest.mark.unit
def test_recorded_aapl_rss_is_english_and_skips_news_empty(monkeypatch):
    seen = {}
    monkeypatch.setattr(ynews.yf, "Ticker", _empty_ticker())
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())
    monkeypatch.setattr(ynews, "urlopen", _urlopen_for(_AAPL_RSS, seen))
    _reset_config()
    try:
        set_config({"data_vendors": {"news_data": "yfinance,alpha_vantage,akshare"}})
        alpha = mock.Mock(return_value="## Should not run\n\n### No\n")
        eastmoney = mock.Mock(return_value="unused")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {
                "yfinance": ynews.get_news_yfinance,
                "alpha_vantage": alpha,
                "akshare": eastmoney,
            }},
        ), mock.patch.object(interface, "format_news_empty", wraps=format_news_empty) as empty:
            out = interface.route_to_vendor("get_news", "AAPL", "2026-10-01", "2026-10-04")
        empty.assert_not_called()
        alpha.assert_not_called()
        eastmoney.assert_not_called()
    finally:
        _reset_config()

    assert seen["url"] == _US_URL
    assert "news.google.com" not in seen["url"]
    assert "eastmoney" not in seen["url"]
    assert not out.startswith("NEWS_EMPTY")
    assert "No news found" not in out
    assert "How Supreme Court Battles Involving Apple, Exxon, and Intel Could Hit Your Portfolio" in out
    assert "Dear Apple Stock Fans, Mark Your Calendars for October 13" in out
    assert "### " in out
    assert "毛戈平" not in out


@pytest.mark.unit
def test_recorded_hk_rss_is_chinese_and_skips_news_empty(monkeypatch):
    seen = {}
    monkeypatch.setattr(ynews.yf, "Ticker", _empty_ticker())
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())
    monkeypatch.setattr(ynews, "urlopen", _urlopen_for(_HK_RSS, seen))
    _reset_config()
    try:
        set_config({"data_vendors": {"news_data": "yfinance"}})
        with mock.patch.object(interface, "format_news_empty", wraps=format_news_empty) as empty:
            out = interface.route_to_vendor("get_news", "1318.HK", "2026-08-01", "2026-10-04")
        empty.assert_not_called()
    finally:
        _reset_config()

    assert seen["url"] == _HK_URL
    assert not out.startswith("NEWS_EMPTY")
    assert "毛戈平(01318)中期純利8.05億元人民幣升20.26% 派息62分" in out
    assert "招商證券大削毛戈平化妝品(01318)目標價50% 維持「增持」" in out
    assert "How Supreme Court" not in out


@pytest.mark.unit
def test_get_news_hit_does_not_fetch_rss(monkeypatch):
    called = {"rss": False}

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def get_news(self, count):
            return [{
                "title": "API headline stays",
                "publisher": "Wire",
                "link": "https://example.test/story",
                "summary": "From get_news.",
                "providerPublishTime": int(datetime(2026, 10, 3, 15, 0).timestamp()),
            }]

    def _boom(symbol):
        called["rss"] = True
        raise AssertionError("RSS must not run when get_news already returned items")

    monkeypatch.setattr(ynews.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())
    monkeypatch.setattr(ynews, "_fetch_yahoo_headline_rss", _boom)
    out = ynews.get_news_yfinance("AAPL", "2026-10-01", "2026-10-04")
    assert "API headline stays" in out
    assert called["rss"] is False


@pytest.mark.unit
def test_empty_rss_still_reaches_format_news_empty(monkeypatch):
    monkeypatch.setattr(ynews.yf, "Ticker", _empty_ticker())
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())
    monkeypatch.setattr(ynews, "_fetch_yahoo_headline_rss", lambda symbol: [])
    _reset_config()
    try:
        set_config({"data_vendors": {"news_data": "yfinance"}})
        out = interface.route_to_vendor("get_news", "AAPL", "2026-10-01", "2026-10-04")
    finally:
        _reset_config()
    assert out.startswith("NEWS_EMPTY:")
    assert "Do not invent headlines." in out
    assert "### " not in out
