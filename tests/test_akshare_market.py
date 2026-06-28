"""AKShare HK/CN price vendor: routing, formatting, and graceful errors.

The vendor must behave like a well-mannered member of the get_stock_data
fallback chain:
  - non HK/CN symbol      -> NoMarketDataError (router falls through to yfinance)
  - akshare not installed  -> VendorNotConfiguredError (router tries next vendor)
  - empty / bad schema     -> NoMarketDataError
  - valid HK data          -> CSV-with-header string matching yfinance's shape
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows import akshare_market
from tradingagents.dataflows.errors import NoMarketDataError, VendorNotConfiguredError


def _hk_frame() -> pd.DataFrame:
    """A minimal Eastmoney-style HK daily frame (Chinese columns)."""
    return pd.DataFrame(
        {
            "日期": ["2026-06-17", "2026-06-18"],
            "开盘": [445.6, 440.0],
            "收盘": [445.4, 440.2],
            "最高": [454.0, 446.2],
            "最低": [445.4, 435.6],
            "成交量": [16962334, 30119117],
            "成交额": [7.59e9, 1.32e10],
        }
    )


class _FakeAk:
    def __init__(self, frame=None, exc=None):
        self._frame = frame
        self._exc = exc

    def stock_hk_hist(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._frame

    def stock_zh_a_hist(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._frame


@pytest.mark.unit
class TestAkshareMarketVendor:
    def test_non_chinese_symbol_raises_no_market_data(self):
        """US/global symbols must defer to the next vendor, not error loudly."""
        with pytest.raises(NoMarketDataError):
            akshare_market.get_stock_data("AAPL", "2026-06-01", "2026-06-20")

    def test_akshare_missing_raises_not_configured(self):
        with patch.object(akshare_market, "_get_akshare", return_value=None):
            with pytest.raises(VendorNotConfiguredError):
                akshare_market.get_stock_data("0700.HK", "2026-06-01", "2026-06-20")

    def test_hk_happy_path_returns_csv_with_header(self):
        fake = _FakeAk(frame=_hk_frame())
        with patch.object(akshare_market, "_get_akshare", return_value=fake):
            out = akshare_market.get_stock_data("0700.HK", "2026-06-01", "2026-06-20")
        assert "# Stock data for 00700.HK (from 0700.HK)" in out
        assert "AKShare/Eastmoney" in out
        # Header row uses the English OHLCV names, not the Chinese originals.
        assert "Date,Open,Close,High,Low,Volume" in out
        assert "日期" not in out
        assert "2026-06-18" in out

    def test_empty_frame_raises_no_market_data(self):
        fake = _FakeAk(frame=pd.DataFrame())
        with patch.object(akshare_market, "_get_akshare", return_value=fake):
            with pytest.raises(NoMarketDataError):
                akshare_market.get_stock_data("0700.HK", "2026-06-01", "2026-06-20")

    def test_fetch_exception_raises_no_market_data(self):
        fake = _FakeAk(exc=ConnectionError("boom"))
        with patch.object(akshare_market, "_get_akshare", return_value=fake):
            with pytest.raises(NoMarketDataError):
                akshare_market.get_stock_data("0700.HK", "2026-06-01", "2026-06-20")

    def test_unexpected_schema_raises_no_market_data(self):
        bad = pd.DataFrame({"foo": [1], "bar": [2]})
        fake = _FakeAk(frame=bad)
        with patch.object(akshare_market, "_get_akshare", return_value=fake):
            with pytest.raises(NoMarketDataError):
                akshare_market.get_stock_data("0700.HK", "2026-06-01", "2026-06-20")
