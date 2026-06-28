"""AKShare-based Chinese news fetcher tests — graceful degradation and lazy import.

Tests that akshare_cn module degrades gracefully when AKShare is not installed
and correctly delegates to AKShare when it is available (mocked).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows import akshare_cn


@pytest.mark.unit
class TestAkshareCNResilience:
    """Test that akshare_cn.fetch_eastmoney_news degrades gracefully."""

    def test_missing_akshare_returns_placeholder(self):
        """When AKShare is not installed, should return placeholder mentioning install."""
        with patch.object(akshare_cn, "_akshare", False):  # Mark as unavailable
            out = akshare_cn.fetch_eastmoney_news("0700.HK")
        assert "akshare" in out.lower()
        assert "not installed" in out.lower()

    def test_non_chinese_ticker_returns_placeholder(self):
        """US tickers should return placeholder (not applicable or AKShare not installed)."""
        out = akshare_cn.fetch_eastmoney_news("NVDA")
        assert "not applicable" in out.lower() or "akshare" in out.lower()

    def test_mocked_akshare_success(self):
        """When AKShare is available and returns data, should format correctly."""
        # Create mock DataFrame
        import pandas as pd

        mock_df = pd.DataFrame({
            "新闻标题": ["腾讯业绩超预期", "腾讯回购股份"],
            "新闻内容": ["内容摘要1...", "内容摘要2..."],
            "发布时间": ["2024-01-01 10:00", "2024-01-02 11:00"],
            "文章来源": ["东方财富", "证券时报"],
            "新闻链接": ["http://example.com/1", "http://example.com/2"],
        })

        mock_ak = MagicMock()
        mock_ak.stock_news_em.return_value = mock_df

        with patch.object(akshare_cn, "_akshare", mock_ak):
            out = akshare_cn.fetch_eastmoney_news("0700.HK")

        assert "Eastmoney" in out or "东方财富" in out
        assert "腾讯" in out
        assert "东方财富" in out or "证券时报" in out

    def test_mocked_akshare_empty_df_returns_placeholder(self):
        """Empty DataFrame should return 'no news found' placeholder."""
        import pandas as pd

        mock_df = pd.DataFrame()
        mock_ak = MagicMock()
        mock_ak.stock_news_em.return_value = mock_df

        with patch.object(akshare_cn, "_akshare", mock_ak):
            out = akshare_cn.fetch_eastmoney_news("0700.HK")

        assert "no" in out.lower() and "news" in out.lower()

    def test_mocked_akshare_exception_returns_placeholder(self):
        """If AKShare raises exception, should catch and return placeholder."""
        mock_ak = MagicMock()
        mock_ak.stock_news_em.side_effect = Exception("Network error")

        with patch.object(akshare_cn, "_akshare", mock_ak):
            out = akshare_cn.fetch_eastmoney_news("0700.HK")

        assert "failed" in out.lower() or "unavailable" in out.lower()

    def test_hk_ticker_converted_to_5_digit(self):
        """0700.HK should be converted to 00700 for Eastmoney."""
        assert akshare_cn.to_eastmoney_code("0700.HK") == "00700"

    def test_sz_ticker_converted_to_6_digit(self):
        """000001.SZ should be converted to 000001 for Eastmoney."""
        assert akshare_cn.to_eastmoney_code("000001.SZ") == "000001"

    def test_ss_ticker_converted_to_6_digit(self):
        """600519.SS should be converted to 600519 for Eastmoney."""
        assert akshare_cn.to_eastmoney_code("600519.SS") == "600519"

    def test_fetch_eastmoney_comment_degrades_gracefully(self):
        """Comment fetcher should also degrade gracefully without AKShare."""
        with patch.object(akshare_cn, "_akshare", False):
            out = akshare_cn.fetch_eastmoney_comment("000001.SZ")
        assert "akshare" in out.lower() or "not applicable" in out.lower()
