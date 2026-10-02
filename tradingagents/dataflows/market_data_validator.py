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


def format_calendar_ytd(df: pd.DataFrame, curr_date: str) -> str:
    """Calendar YTD simple return from the verified close series.

    Simple return is the latest close on or before ``curr_date`` divided by the
    last close strictly before January 1 of that year, minus one. A missing
    base or end print is an em dash plus the reason, never a guessed percent.
    """
    cutoff = pd.Timestamp(curr_date).normalize()
    year_start = pd.Timestamp(year=cutoff.year, month=1, day=1)
    frame = df.copy()
    frame["_day"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["_day"])
    prior = frame[frame["_day"] < year_start]
    current = frame[frame["_day"] <= cutoff]
    if prior.empty:
        return (
            f"— (Gap: no close before {year_start.date()} in the verified OHLCV "
            f"window; calendar YTD needs the last prior-year close)"
        )
    if current.empty or "Close" not in frame.columns:
        return "— (Gap: no close on or before the analysis date)"
    base_row = prior.iloc[-1]
    end_row = current.iloc[-1]
    base = base_row.get("Close")
    end = end_row.get("Close")
    if pd.isna(base) or pd.isna(end) or float(base) == 0:
        return "— (Gap: prior-year or latest close is missing or zero)"
    simple = (float(end) / float(base)) - 1
    return (
        f"{simple:+.2%} (simple return: close {_fmt(end)} on {_fmt(end_row['Date'])} / "
        f"prior-year close {_fmt(base)} on {_fmt(base_row['Date'])} - 1)"
    )


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
        format_calendar_ytd(df, curr_date),
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
