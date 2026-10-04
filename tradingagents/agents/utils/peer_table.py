"""Short peer table from a caller-supplied list.

The model does not choose the companies. Names come from ``--peers``,
``--peers-file``, or ``peers.txt`` in the research directory. Each row is
public price data for that name. Missing quotes stay gaps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from tradingagents.dataflows.company_filings import (
    default_get,
    resolve_cninfo_symbol,
)

_BARE_TICKER = re.compile(r"^(?:[A-Za-z]{1,6}|\d{1,6})(?:\.[A-Za-z]{1,4})?$")
_TICKER_AT_END = re.compile(
    r"^(?P<name>.*?)(?:\s+)(?P<ticker>(?:[A-Za-z]{1,6}|\d{1,6})(?:\.[A-Za-z]{1,4})?)$"
)


def load_peer_names(
    *,
    peers: str | None = None,
    peers_file: Path | str | None = None,
    research_dir: Path | str | None = None,
) -> list[str]:
    """Caller-supplied names, in order. Empty when the caller passed none."""
    if peers and peers.strip():
        return _split_peers(peers)
    path: Path | None = None
    if peers_file:
        path = Path(peers_file)
        if not path.is_file():
            raise FileNotFoundError(f"peer file does not exist: {path}")
    elif research_dir and (Path(research_dir) / "peers.txt").is_file():
        path = Path(research_dir) / "peers.txt"
    if path is None:
        return []
    return _split_peers(path.read_text(encoding="utf-8"))


def _split_peers(text: str) -> list[str]:
    names = []
    for line in text.replace(",", "\n").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        names.append(cleaned)
    return names


def parse_peer_line(line: str) -> tuple[str, str | None]:
    """Split ``珀莱雅 603605.SS`` into a display name and an optional ticker."""
    text = (line or "").strip()
    if _BARE_TICKER.match(text):
        return text, text.upper()
    match = _TICKER_AT_END.match(text)
    if match and _BARE_TICKER.match(match.group("ticker")):
        name = match.group("name").strip() or text
        return name, match.group("ticker").upper()
    return text, None


def resolve_peer_symbol(name: str, ticker: str | None = None, *, get=None) -> tuple[str | None, str]:
    """Resolve one caller-supplied name. Never substitutes a different company."""
    if ticker:
        return ticker, ""
    getter = get or default_get
    if name.isascii():
        symbol = _yahoo_search(name, getter)
        if symbol:
            return symbol, ""
    else:
        symbol = resolve_cninfo_symbol(name, get=getter)
        if symbol:
            return symbol, ""
        symbol = _hkex_name(name, getter)
        if symbol:
            return symbol, ""
    return None, f"Gap: no public quote symbol for {name}."


def fetch_public_quote(symbol: str, *, get=None) -> dict:
    """Price and a close-to-close trend from the public Yahoo chart."""
    getter = get or default_get
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}?range=6mo&interval=1d"
    )
    payload = json.loads(getter(url))
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"no chart result for {symbol}")
    meta = result[0].get("meta") or {}
    closes = [
        value
        for value in ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        if value is not None
    ]
    currency = meta.get("currency") or ""
    price = meta.get("regularMarketPrice")
    trend = ""
    if len(closes) >= 2 and closes[0]:
        change = (closes[-1] - closes[0]) / closes[0] * 100
        trend = (
            f"6-month public closes {closes[0]:.2f} → {closes[-1]:.2f} {currency} "
            f"({change:+.1f}%, computed from those closes)"
        )
    price_text = f"{price} {currency}".strip() if price is not None else ""
    return {
        "price": price_text,
        "trend": trend,
        "financials": "",
        "valuation": f"Public price: {price_text}" if price_text else "",
    }


def build_peer_table(names: list[str], *, get=None, resolve=None, quote=None) -> str:
    """Markdown table. Rows are exactly ``names``; none are added."""
    cleaned = [name.strip() for name in names if name and name.strip()]
    if not cleaned:
        return (
            "Gap: no caller-supplied peer list. Comparable companies are not invented. "
            "Pass 3 to 5 peers with --peers, --peers-file, or peers.txt."
        )
    lines = []
    if not 3 <= len(cleaned) <= 5:
        lines.append(
            f"Gap: caller supplied {len(cleaned)} peers; expected 3 to 5. "
            "No names were added or removed."
        )
    lines.append("Caller-supplied peers only. The model does not add companies.")
    lines.append("")
    lines.append("| Peer | Public financials | Current valuation | Price trend |")
    lines.append("| --- | --- | --- | --- |")
    resolver = resolve or resolve_peer_symbol
    quoter = quote or fetch_public_quote
    for raw in cleaned:
        display, ticker = parse_peer_line(raw)
        try:
            symbol, note = resolver(display, ticker, get=get)
        except Exception as exc:
            symbol, note = None, f"Gap: symbol lookup failed ({exc})."
        if not symbol:
            lines.append(
                f"| {_cell(display)} | {_cell(note or 'Gap')} | Gap: no quote | Gap: no quote |"
            )
            continue
        try:
            snap = quoter(symbol, get=get)
        except Exception as exc:
            lines.append(
                f"| {_cell(display)} ({_cell(symbol)}) | Gap: quote failed ({_cell(str(exc))}) "
                "| Gap: quote failed | Gap: quote failed |"
            )
            continue
        financials = snap.get("financials") or "Gap: the public quote has no statement figures."
        valuation = snap.get("valuation") or (
            f"Public price: {snap['price']}" if snap.get("price") else "Gap: no public price."
        )
        trend = snap.get("trend") or "Gap: no public price history."
        lines.append(
            f"| {_cell(display)} ({_cell(symbol)}) | {_cell(financials)} | "
            f"{_cell(valuation)} | {_cell(trend)} |"
        )
    return "\n".join(lines)


def _cell(value: str) -> str:
    return (value or "").replace("|", "/").replace("\n", " ").strip()


def _yahoo_search(name: str, get) -> str | None:
    url = "https://query1.finance.yahoo.com/v1/finance/search?q=" + quote(name)
    try:
        payload = json.loads(get(url))
    except Exception:
        return None
    for item in payload.get("quotes") or []:
        if item.get("quoteType") == "EQUITY" and item.get("symbol"):
            return str(item["symbol"])
    return None


def _hkex_name(name: str, get) -> str | None:
    url = (
        "https://www1.hkexnews.hk/search/prefix.do?&callback=callback&lang=ZH&type=A"
        f"&name={quote(name)}&market=SEHK"
    )
    try:
        raw = get(url).decode("utf-8", errors="replace")
        payload = json.loads(raw[raw.find("(") + 1 : raw.rfind(")")])
    except Exception:
        return None
    for item in payload.get("stockInfo") or []:
        if str(item.get("name") or "") != name:
            continue
        code = str(item.get("code") or "")
        if code.isdigit():
            return f"{int(code):04d}.HK"
    return None
