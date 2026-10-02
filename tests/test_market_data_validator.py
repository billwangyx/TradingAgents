"""Tests for the deterministic market-data verification snapshot (#830/#881)."""

from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator


@pytest.fixture(autouse=True)
def _stub_dividend_yield(monkeypatch):
    """Keep snapshot tests off the Yahoo info endpoint."""
    monkeypatch.setattr(
        validator,
        "yf_retry",
        lambda fn: {"dividendYield": 0.012},
    )


def _sample_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame({
        "Date": dates,
        "Open": [c - 0.5 for c in closes],
        "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 + i for i in range(len(dates))],
    })


@pytest.mark.unit
class TestVerifiedSnapshot:
    def test_excludes_future_rows(self, monkeypatch):
        data = pd.concat([
            _sample_ohlcv(),
            pd.DataFrame({"Date": [pd.Timestamp("2026-06-01")], "Open": [999.0],
                          "High": [999.0], "Low": [999.0], "Close": [999.0], "Volume": [999]}),
        ], ignore_index=True)
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: data)

        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "Verified market data snapshot for COF" in snap
        assert "Requested analysis date: 2026-05-13" in snap
        assert "Latest trading row used: 2026-05-13" in snap
        assert "999.00" not in snap          # future row excluded
        assert "boll_lb" in snap             # indicators present
        assert "Calendar YTD simple return" in snap
        assert "Dividend yield" in snap
        assert "0.012 (Yahoo info dividendYield, as returned)" in snap

    def test_uses_previous_trading_day_when_date_is_weekend(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        # 2026-05-16 is a Saturday; latest row should be Fri 2026-05-15
        snap = validator.build_verified_market_snapshot("COF", "2026-05-16")
        assert "Latest trading row used: 2026-05-15" in snap
        assert "Recent verified closes" in snap

    def test_raises_when_no_rows_on_or_before_date(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2020-01-01")

    def test_raises_on_empty_data(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: pd.DataFrame())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2026-05-13")

    def test_look_back_window_capped_at_30(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-20", look_back_days=999)
        # last-N closes table has at most 30 data rows
        close_rows = [ln for ln in snap.splitlines() if ln.startswith("| 2026-")]
        assert 0 < len(close_rows) <= 30

    def test_calendar_ytd_is_simple_return_off_prior_year_close(self, monkeypatch):
        dates = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"])
        frame = pd.DataFrame({
            "Date": dates,
            "Open": [99.0, 109.0, 120.0, 131.0],
            "High": [101.0, 111.0, 122.0, 133.0],
            "Low": [98.0, 108.0, 119.0, 130.0],
            "Close": [100.0, 110.0, 121.0, 132.0],
            "Volume": [1, 1, 1, 1],
        })
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: frame)
        snap = validator.build_verified_market_snapshot("COF", "2026-01-05")
        # 132 / 110 - 1 = +20%
        assert "+20.00%" in snap
        assert "prior-year close 110.00 on 2025-12-31" in snap

    def test_calendar_ytd_gaps_when_prior_year_close_is_missing(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "— (Gap: no close before 2026-01-01" in snap

    def test_missing_dividend_yield_is_an_em_dash_with_reason(self):
        assert validator.format_dividend_yield(None).startswith("— (")
        assert "do not invent a yield" in validator.format_dividend_yield(None)
        assert validator.format_dividend_yield(0).startswith("0 (Yahoo info dividendYield")

    def test_dividend_lookup_failure_is_an_em_dash(self, monkeypatch):
        def _raise(fn):
            raise RuntimeError("yahoo info down")

        monkeypatch.setattr(validator, "yf_retry", _raise)
        line = validator.lookup_yahoo_dividend_yield("COF")
        assert line.startswith("— (Gap: Yahoo dividend yield lookup failed")
        assert "RuntimeError" in line

    def test_dividend_lookup_missing_field_names_the_reason(self, monkeypatch):
        monkeypatch.setattr(validator, "yf_retry", lambda fn: {})
        line = validator.lookup_yahoo_dividend_yield("COF")
        assert line.startswith("— (")
        assert "no dividendYield" in line


@pytest.mark.unit
class TestTool:
    def test_tool_delegates_to_builder(self, monkeypatch):
        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        out = get_verified_market_snapshot.invoke(
            {"symbol": "COF", "curr_date": "2026-05-20"}
        )
        assert "Verified market data snapshot for COF" in out
