"""AKShare-based OHLCV price vendor for HK and mainland-China equities.

Yahoo Finance frequently returns 401 "Invalid Crumb" for Hong Kong tickers,
so this module provides a keyless, non-Yahoo price source for HK/CN markets
via Eastmoney data exposed through AKShare:

    - HK stocks  -> ak.stock_hk_hist  (symbol "00700")
    - A-shares   -> ak.stock_zh_a_hist (symbol "600519" / "000001")

It plugs into the same vendor-routing contract as ``y_finance.get_YFin_data_online``:
returns the identical CSV-with-header string on success, and raises the typed
vendor errors the router understands:

    - non HK/CN symbol  -> NoMarketDataError  (router falls through to yfinance)
    - akshare missing    -> VendorNotConfiguredError (router tries next vendor)
    - empty/failed fetch -> NoMarketDataError

AKShare is an optional dependency (``pip install "tradingagents[cn]"``); the
lazy import keeps the core install lean and degrades gracefully when absent.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from .errors import NoMarketDataError, VendorNotConfiguredError
from .symbol_utils import detect_market, to_eastmoney_code

logger = logging.getLogger(__name__)

# Lazy import handle for akshare (None = not yet tried, False = unavailable)
_akshare = None

# Eastmoney/AKShare daily-history columns are Chinese; map the OHLCV subset we
# need onto the English names the rest of the pipeline (stockstats, CSV header)
# expects. Extra columns (成交额/振幅/...) are dropped.
_COLUMN_MAP = {
    "日期": "Date",
    "开盘": "Open",
    "收盘": "Close",
    "最高": "High",
    "最低": "Low",
    "成交量": "Volume",
}


def _get_akshare():
    """Lazy importer for akshare — returns module or None if unavailable."""
    global _akshare
    if _akshare is None:
        try:
            import akshare as ak
            _akshare = ak
        except ImportError:
            logger.debug("AKShare not installed; HK/CN price vendor unavailable")
            _akshare = False
    return _akshare if _akshare is not False else None


def _fetch_hist(ak, market: str, code: str, start: str, end: str):
    """Fetch raw daily history DataFrame from the market-appropriate AKShare API."""
    if market == "HK":
        return ak.stock_hk_hist(
            symbol=code, period="daily", start_date=start, end_date=end, adjust=""
        )
    # mainland A-shares (Shanghai/Shenzhen)
    return ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end, adjust=""
    )


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return OHLCV price data for an HK/CN ``symbol`` as a CSV-with-header string.

    Output format matches ``y_finance.get_YFin_data_online`` so it is a drop-in
    vendor for ``get_stock_data``. Raises ``NoMarketDataError`` for non-HK/CN
    symbols (so the router falls through to Yahoo for US/global names) and on
    empty results, and ``VendorNotConfiguredError`` when akshare is not installed.
    """
    market = detect_market(symbol)
    if market not in ("HK", "CN"):
        # Not our market — defer to other vendors without a wasted network call.
        raise NoMarketDataError(
            symbol, symbol, "akshare price vendor covers HK/CN markets only"
        )

    code = to_eastmoney_code(symbol)
    if code is None:
        raise NoMarketDataError(symbol, symbol, "could not derive an Eastmoney code")

    ak = _get_akshare()
    if ak is None:
        raise VendorNotConfiguredError(
            "akshare not installed; run: pip install \"tradingagents[cn]\""
        )

    # Validate dates and convert to AKShare's compact YYYYMMDD form.
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")

    try:
        raw = _fetch_hist(ak, market, code, start_compact, end_compact)
    except Exception as exc:  # AKShare wraps network/parse errors broadly
        logger.warning("AKShare price fetch failed for %s (%s): %s", symbol, code, exc)
        raise NoMarketDataError(symbol, code, f"akshare fetch error: {exc}") from exc

    if raw is None or raw.empty:
        raise NoMarketDataError(
            symbol, code, f"no rows between {start_date} and {end_date}"
        )

    # Keep and rename only the OHLCV columns; bail out clearly if the upstream
    # schema changed (rather than silently emitting a malformed frame).
    present = {cn: en for cn, en in _COLUMN_MAP.items() if cn in raw.columns}
    if "日期" not in present or "收盘" not in present:
        raise NoMarketDataError(
            symbol, code, f"unexpected akshare schema: {list(raw.columns)}"
        )
    data = raw[list(present.keys())].rename(columns=present)

    data["Date"] = data["Date"].astype(str)
    data = data.set_index("Date")

    numeric_columns = ["Open", "High", "Low", "Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    csv_string = data.to_csv()

    label = f"{code}.{market} (from {symbol})"
    header = f"# Stock data for {label} from {start_date} to {end_date}\n"
    header += f"# Source: AKShare/Eastmoney\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string
