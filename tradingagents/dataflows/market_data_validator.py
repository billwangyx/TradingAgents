"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import yfinance as yf
from stockstats import wrap

from tradingagents.dataflows.stockstats_utils import load_ohlcv, yf_retry
from tradingagents.dataflows.symbol_utils import normalize_symbol

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    ``load_ohlcv`` already normalizes the Date column and filters out
    look-ahead rows, but we re-apply the cutoff defensively — this is a
    verification path, so it must not trust its input to be pre-filtered.
    """
    data = load_ohlcv(symbol, curr_date)
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df


def _ytd_from_ohlc(df: pd.DataFrame, curr_date: str):
    """First close of the calendar year to the latest close, or None.

    Simple price return, not total return. ``None`` means the verified window
    has no usable close inside that year, so the caller writes a Gap instead
    of a percent.
    """
    cutoff = pd.Timestamp(curr_date).normalize()
    year_start = pd.Timestamp(year=cutoff.year, month=1, day=1)
    frame = df.copy()
    frame["_day"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["_day"])
    if "Close" not in frame.columns:
        return None
    year_rows = frame[(frame["_day"] >= year_start) & (frame["_day"] <= cutoff)]
    if year_rows.empty:
        return None
    base_row = year_rows.iloc[0]
    end_row = year_rows.iloc[-1]
    base = base_row.get("Close")
    end = end_row.get("Close")
    if pd.isna(base) or pd.isna(end) or float(base) == 0:
        return None
    simple = (float(end) / float(base)) - 1
    return simple, base, base_row["Date"], end, end_row["Date"]


def format_calendar_ytd(df: pd.DataFrame, curr_date: str) -> str:
    """Calendar YTD simple return from verified OHLC.

    First available close of the calendar year versus the latest close on or
    before ``curr_date``. A missing year of history is an em dash plus the
    reason, never a guessed percent.
    """
    computed = _ytd_from_ohlc(df, curr_date)
    if computed is None:
        year = pd.Timestamp(curr_date).year
        return (
            f"— (Gap: no close in calendar year {year} in the verified OHLCV "
            f"window; YTD needs price history and is not invented)"
        )
    simple, base, base_day, end, end_day = computed
    return (
        f"{simple:+.2%} (simple return: close {_fmt(end)} on {_fmt(end_day)} / "
        f"first close of year {_fmt(base)} on {_fmt(base_day)} - 1)"
    )


def _ytd_number(value) -> float | None:
    """Yahoo ``ytdReturn`` as a float ratio, or None when the field is blank."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _yahoo_ytd_auth_failure(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(token in blob for token in ("401", "unauthorized", "invalid crumb", "crumb"))


def lookup_yahoo_ytd_return(symbol: str) -> tuple[str, float | None]:
    """Read Yahoo ``ytdReturn``.

    Returns ``("ok", ratio)``, ``("empty", None)`` when the field is blank or
    the quote lookup is a 401/crumb failure, or ``("error", None)`` for any
    other lookup failure. Callers compute from OHLC in the last two cases.
    """
    try:
        canonical = normalize_symbol(symbol)
        info = yf_retry(lambda: yf.Ticker(canonical).info)
    except Exception as exc:
        if _yahoo_ytd_auth_failure(exc):
            return "empty", None
        return "error", None
    if not isinstance(info, dict):
        return "empty", None
    number = _ytd_number(info.get("ytdReturn"))
    if number is None:
        return "empty", None
    return "ok", number


def format_verified_ytd(df: pd.DataFrame, curr_date: str, symbol: str) -> str:
    """KPI line: Yahoo ``ytdReturn`` when present, otherwise OHLC.

    Gap only when Yahoo has no usable print and the year's close history is
    missing. Does not invent a percent.
    """
    status, value = lookup_yahoo_ytd_return(symbol)
    if status == "ok" and value is not None:
        return f"{value:+.2%} (Yahoo info ytdReturn, as returned)"
    local = format_calendar_ytd(df, curr_date)
    if local.startswith("—"):
        return local
    if status == "empty":
        note = "Yahoo ytdReturn empty or 401; computed from OHLC"
    else:
        note = "Yahoo ytdReturn unavailable; computed from OHLC"
    return f"{local} ({note})"


def format_dividend_yield(value) -> str:
    """Render Yahoo's dividendYield, or an em dash that says why it is absent."""
    if value is None:
        return "— (Yahoo info has no dividendYield; do not invent a yield)"
    if isinstance(value, str) and not value.strip():
        return "— (Yahoo info dividendYield is blank; do not invent a yield)"
    if isinstance(value, float) and pd.isna(value):
        return "— (Yahoo info dividendYield is blank; do not invent a yield)"
    return f"{value} (Yahoo info dividendYield, as returned)"


def lookup_yahoo_dividend_yield(symbol: str) -> str:
    """Read dividendYield from Yahoo info. Failures stay an em dash plus a reason."""
    try:
        canonical = normalize_symbol(symbol)
        info = yf_retry(lambda: yf.Ticker(canonical).info)
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:180] if str(exc).strip() else type(exc).__name__
        return f"— (Gap: Yahoo dividend yield lookup failed: {type(exc).__name__}: {detail})"
    if not isinstance(info, dict):
        return "— (Gap: Yahoo info was not a field map; dividendYield unavailable)"
    return format_dividend_yield(info.get("dividendYield"))


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## Verified market data snapshot for {symbol.upper()}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += [
        "",
        "### Calendar YTD simple return",
        "",
        format_verified_ytd(df, curr_date, symbol),
        "",
        "### Dividend yield (Yahoo info)",
        "",
        lookup_yahoo_dividend_yield(symbol),
    ]

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} rows)", "",
              "| Date | Close |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, the calendar "
        "YTD simple return, dividend yield, price levels, and indicator values. "
        "Copy any em-dash line into Gaps with its reason. If another tool output "
        "conflicts with this snapshot, flag the discrepancy rather than inventing "
        "a reconciled number. Do not claim historical validation, support/"
        "resistance bounces, or exact percentage moves unless directly supported "
        "by tool output with concrete dates and prices.",
    ]
    return "\n".join(lines)
