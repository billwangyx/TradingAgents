"""Tests for market detection and Chinese data source symbol conversion.

Tests detect_market(), to_eastmoney_code(), and to_xueqiu_symbol() functions
from tradingagents.dataflows.symbol_utils.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows.symbol_utils import (
    detect_market,
    to_eastmoney_code,
    to_xueqiu_symbol,
)


@pytest.mark.unit
class TestMarketDetection:
    """Test detect_market() for correct market classification."""

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("0700.HK", "HK"),
            ("0700.hk", "HK"),  # lowercase
            ("3690.HK", "HK"),
            ("00001.HK", "HK"),  # 5-digit HK
            ("AAPL", None),  # US
            ("NVDA", None),
            ("TSLA", None),
            ("MSFT", None),
            ("000001.SZ", "CN"),  # Shenzhen
            ("000001.sz", "CN"),  # lowercase
            ("600519.SS", "CN"),  # Shanghai
            ("601318.SS", "CN"),
            ("300059.SZ", "CN"),  # ChiNext
        ],
    )
    def test_detect_market(self, ticker, expected):
        """Market detection should work for various ticker formats."""
        assert detect_market(ticker) == expected

    def test_detect_market_none_and_empty(self):
        """None and empty strings should return None."""
        assert detect_market(None) is None
        assert detect_market("") is None
        assert detect_market("   ") is None


@pytest.mark.unit
class TestEastmoneyCodeConversion:
    """Test to_eastmoney_code() for correct symbol conversion."""

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            # HK: 5 digits with leading zeros
            ("0700.HK", "00700"),
            ("3690.HK", "03690"),
            ("1.HK", "00001"),  # single digit
            ("99999.HK", "99999"),  # already 5 digits
            # A-shares: 6 digits, no suffix
            ("000001.SZ", "000001"),
            ("600519.SS", "600519"),
            ("300059.SZ", "300059"),
        ],
    )
    def test_to_eastmoney_code_chinese(self, ticker, expected):
        """Chinese/HK tickers should convert to Eastmoney format."""
        assert to_eastmoney_code(ticker) == expected

    @pytest.mark.parametrize(
        "ticker",
        ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL"],
    )
    def test_to_eastmoney_code_us_returns_none(self, ticker):
        """US tickers should return None."""
        assert to_eastmoney_code(ticker) is None

    def test_to_eastmoney_code_none_and_empty(self):
        """None and empty strings should return None."""
        assert to_eastmoney_code(None) is None
        assert to_eastmoney_code("") is None


@pytest.mark.unit
class TestXueqiuSymbolConversion:
    """Test to_xueqiu_symbol() for correct Xueqiu format conversion."""

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            # HK: HK + 5-digit code
            ("0700.HK", "HK00700"),
            ("3690.HK", "HK03690"),
            ("1.HK", "HK00001"),
            # Shanghai: SH prefix
            ("600519.SS", "SH600519"),
            ("000001.SS", "SH000001"),
            ("601318.SS", "SH601318"),
            # Shenzhen: SZ prefix
            ("000001.SZ", "SZ000001"),
            ("300059.SZ", "SZ300059"),
            ("000858.SZ", "SZ000858"),
        ],
    )
    def test_to_xueqiu_symbol_chinese(self, ticker, expected):
        """Chinese/HK tickers should convert to Xueqiu format."""
        assert to_xueqiu_symbol(ticker) == expected

    @pytest.mark.parametrize(
        "ticker",
        ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL"],
    )
    def test_to_xueqiu_symbol_us_returns_none(self, ticker):
        """US tickers should return None."""
        assert to_xueqiu_symbol(ticker) is None

    def test_to_xueqiu_symbol_none_and_empty(self):
        """None and empty strings should return None."""
        assert to_xueqiu_symbol(None) is None
        assert to_xueqiu_symbol("") is None


@pytest.mark.unit
class TestMarketRoutingIntegration:
    """Integration tests for market-based data source selection.

    These tests verify that the market detection logic correctly
    routes to appropriate data sources in the sentiment analyst.
    """

    def test_hk_market_routes_to_cn_sources(self):
        """HK tickers should be detected as HK market."""
        ticker = "0700.HK"
        assert detect_market(ticker) == "HK"
        assert to_xueqiu_symbol(ticker) is not None
        assert to_eastmoney_code(ticker) is not None

    def test_cn_market_routes_to_cn_sources(self):
        """CN (A-share) tickers should be detected as CN market."""
        ticker_sz = "000001.SZ"
        ticker_ss = "600519.SS"
        assert detect_market(ticker_sz) == "CN"
        assert detect_market(ticker_ss) == "CN"
        assert to_xueqiu_symbol(ticker_sz) is not None
        assert to_xueqiu_symbol(ticker_ss) is not None

    def test_us_market_routes_to_us_sources(self):
        """US tickers should be detected as non-CN/HK (None)."""
        ticker = "NVDA"
        assert detect_market(ticker) is None
        assert to_xueqiu_symbol(ticker) is None
        assert to_eastmoney_code(ticker) is None
