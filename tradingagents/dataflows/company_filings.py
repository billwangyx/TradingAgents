"""Exchange filing text for the research manager.

US filings come from data.sec.gov submissions, then the archived HTML.
Hong Kong filings are the HKEX interim and annual reports, plus a results
announcement when that PDF downloads. A-share filings are cninfo periodic
reports, and only when the PDF body itself downloads.

An earnings release or a transcript is attached only when a public full text
was retrieved. yfinance and Alpha Vantage statements are not a substitute.
"""

from __future__ import annotations

import gzip
import html
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tradingagents.dataflows.pdf_text import extract_pdf_text
from tradingagents.dataflows.symbol_utils import detect_market

# data.sec.gov answers 403 unless the User-Agent names a contact. A bare
# product token is rejected; "Name email@domain" is accepted.
USER_AGENT = "TradingAgents Research bill.wangyx@gmail.com"

TRANSCRIPT_GAP = (
    "Gap: no public full-text earnings transcript was retrieved. "
    "Do not invent quotes."
)
EARNINGS_RELEASE_GAP = (
    "Gap: no public full-text earnings release was retrieved. "
    "Do not invent a release or its figures."
)

_GET = Callable[..., bytes]

_KEY_LINE = re.compile(
    r"(?i)("
    r"revenue|net sales|net income|net profit|profit for the period|"
    r"operating profit|gross profit|total revenue|"
    r"收入|營收|营收|收益|利润|利潤|溢利|盈利|營業額|营业额|毛利"
    r")"
)
_GROUPED_AMOUNT = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_INDUSTRY = re.compile(r"行业|行業|industry", re.IGNORECASE)


class FilingRequestError(Exception):
    """A filing host refused or failed the request. Not a fabricated filing."""


def default_get(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: float = 60,
) -> bytes:
    """GET or POST ``url``. SEC and HKEX both receive the descriptive User-Agent."""
    head = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        head.update(headers)
    if data is not None and "Content-Type" not in head:
        head["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=data, headers=head)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except HTTPError as exc:
        detail = exc.read(160)
        raise FilingRequestError(f"HTTP {exc.code} for {url}: {detail[:120]!r}") from exc
    except URLError as exc:
        raise FilingRequestError(f"request failed for {url}: {exc.reason}") from exc


def excerpt_text(text: str, limit: int = 8000) -> str:
    """Keep windows around financial lines. Figures are copied, not computed.

    Windows that also contain a grouped amount (for example ``3,267.3``) are
    kept first, so a long filing does not crowd out the headline figures.
    """
    cleaned = (text or "").replace("\x00", "")
    if not cleaned.strip():
        return ""
    candidates: list[tuple[int, int, int]] = []
    for match in _KEY_LINE.finditer(cleaned):
        start = max(0, match.start() - 500)
        end = min(len(cleaned), match.end() + 700)
        score = 3 if _GROUPED_AMOUNT.search(cleaned[start:end]) else 1
        candidates.append((score, start, end))
    if not candidates:
        return cleaned.strip()[:limit]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[int, int]] = []
    used = 0
    for _score, start, end in candidates:
        if any(start <= right and end >= left for left, right in chosen):
            continue
        if used >= limit:
            break
        chosen.append((start, end))
        used += end - start
    chosen.sort()
    merged: list[tuple[int, int]] = []
    for start, end in chosen:
        if merged and start <= merged[-1][1] + 80:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    body = "\n\n".join(cleaned[start:end].strip() for start, end in merged)
    if len(body) > limit:
        return body[:limit].rstrip() + "\n[excerpt truncated]"
    return body


def industry_window(text: str, limit: int = 700) -> str:
    """A short filing quote that mentions the industry, or empty."""
    cleaned = text or ""
    match = _INDUSTRY.search(cleaned)
    if not match:
        return ""
    start = max(0, match.start() - 180)
    end = min(len(cleaned), match.end() + limit)
    return cleaned[start:end].strip()


def fetch_company_filings(
    ticker: str,
    *,
    as_of: str | None = None,
    transcript_text: str | None = None,
    get: _GET | None = None,
) -> str:
    """Filing pack for ``ticker``. Failures are Gap lines, not invented filings."""
    symbol = (ticker or "").strip().upper()
    getter = get or default_get
    market = detect_market(symbol)
    if market == "HK":
        body = _hong_kong_filings(symbol, as_of=as_of, get=getter)
    elif market == "CN":
        body = _china_filings(symbol, as_of=as_of, get=getter)
    else:
        body = _us_filings(symbol, as_of=as_of, get=getter)
    return (
        f"Exchange filings for {symbol}. Quoted from retrieved text. "
        "Do not invent figures. Do not replace this with yfinance.\n\n"
        f"{body.rstrip()}\n\n{_transcript_block(transcript_text)}"
    )


def _transcript_block(text: str | None) -> str:
    body = (text or "").strip()
    if len(body) < 80:
        return "### Earnings transcript\n" + TRANSCRIPT_GAP
    clipped = body[:8000]
    return (
        "### Earnings transcript\n"
        "Public full text supplied with this run. Quoted, not paraphrased from memory.\n"
        f"{clipped}"
    )


def _block(title: str, url: str, body: str = "", error: str = "") -> str:
    lines = [f"### {title}"]
    if url:
        lines.append(f"Source: {url}")
    if error:
        line = error.strip()
        if not line.startswith("Gap:"):
            line = f"Gap: {line}"
        if "Do not invent" not in line:
            line += " Do not invent figures."
        lines.append(line)
    elif not (body or "").strip():
        lines.append("Gap: no text was extracted from the downloaded body. Do not invent figures.")
    else:
        lines.append(body.strip())
    return "\n".join(lines)


def _call(get: _GET, url: str, **kwargs) -> bytes:
    try:
        return get(url, **kwargs)
    except TypeError:
        if kwargs.get("data") is None:
            return get(url)
        return get(url, kwargs.get("data"))


# ---------------------------------------------------------------------------
# United States — data.sec.gov submissions, then the archive
# ---------------------------------------------------------------------------


def _us_filings(ticker: str, *, as_of: str | None, get: _GET) -> str:
    try:
        cik = _cik_for_ticker(get, ticker)
    except FilingRequestError as exc:
        return _block("US filings", "https://data.sec.gov/submissions/", error=str(exc))
    if cik is None:
        return _block(
            "US filings",
            "https://www.sec.gov/files/company_tickers.json",
            error=f"no CIK for {ticker} in the SEC company ticker list.",
        )
    padded = f"{cik:010d}"
    submissions_url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    try:
        payload = json.loads(_call(get, submissions_url))
    except (FilingRequestError, json.JSONDecodeError, UnicodeError) as exc:
        return _block("US filings", submissions_url, error=str(exc))

    recent = (payload.get("filings") or {}).get("recent") or {}
    picked = _pick_forms(recent, ("10-Q", "10-K", "8-K"), as_of)
    parts = []
    for form in ("10-Q", "10-K"):
        filing = picked.get(form)
        if not filing:
            parts.append(_block(f"US {form}", submissions_url, error=f"no {form} on or before the as-of date."))
            continue
        url = _archive_url(cik, filing["accession"], filing["document"])
        parts.append(_downloaded_html(f"US {form} filed {filing['date']}", url, get))
    parts.append(_us_earnings_release(cik, picked.get("8-K"), get))
    return "\n\n".join(parts)


def _cik_for_ticker(get: _GET, ticker: str) -> int | None:
    raw = _call(get, "https://www.sec.gov/files/company_tickers.json")
    payload = json.loads(raw)
    want = ticker.upper()
    for row in payload.values():
        if str(row.get("ticker", "")).upper() == want:
            return int(row["cik_str"])
    return None


def _pick_forms(recent: dict, forms: tuple[str, ...], as_of: str | None) -> dict:
    picked: dict = {}
    labels = recent.get("form") or []
    for index, form in enumerate(labels):
        if form not in forms or form in picked:
            continue
        filed = (recent.get("filingDate") or [""])[index]
        if as_of and filed > as_of:
            continue
        picked[form] = {
            "date": filed,
            "accession": (recent.get("accessionNumber") or [""])[index],
            "document": (recent.get("primaryDocument") or [""])[index],
        }
    return picked


def _archive_url(cik: int, accession: str, document: str) -> str:
    acc = (accession or "").replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{document}"


def _downloaded_html(title: str, url: str, get: _GET) -> str:
    try:
        raw = _call(get, url)
    except FilingRequestError as exc:
        return _block(title, url, error=str(exc))
    text = excerpt_text(_html_to_text(raw))
    return _block(title, url, body=text)


def _us_earnings_release(cik: int, eight_k: dict | None, get: _GET) -> str:
    if not eight_k:
        return _block("Earnings release", "", error=EARNINGS_RELEASE_GAP)
    index_url = _archive_url(cik, eight_k["accession"], "index.json")
    try:
        payload = json.loads(_call(get, index_url))
    except (FilingRequestError, json.JSONDecodeError, UnicodeError) as exc:
        return _block("Earnings release", index_url, error=f"{EARNINGS_RELEASE_GAP} ({exc})")
    items = (payload.get("directory") or {}).get("item") or []
    exhibit = ""
    for item in items:
        name = str(item.get("name") or "")
        lowered = name.lower()
        if "ex991" in lowered or "ex-99" in lowered or "ex99" in lowered:
            exhibit = name
            break
    if not exhibit:
        return _block(
            "Earnings release",
            index_url,
            error="no EX-99 exhibit in the latest 8-K index. " + EARNINGS_RELEASE_GAP,
        )
    url = _archive_url(cik, eight_k["accession"], exhibit)
    return _downloaded_html(f"Earnings release (8-K exhibit {exhibit})", url, get)


def _html_to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|tr|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Hong Kong — HKEX interim / annual reports and results announcements
# ---------------------------------------------------------------------------

_HKEX = "https://www1.hkexnews.hk"


def _hong_kong_filings(ticker: str, *, as_of: str | None, get: _GET) -> str:
    code = _hk_code(ticker)
    if not code:
        return _block("Hong Kong filings", _HKEX, error=f"{ticker} has no HKEX stock code.")
    try:
        stock_id, _name = _hk_stock_id(get, code)
    except (FilingRequestError, json.JSONDecodeError, ValueError) as exc:
        return _block("Hong Kong filings", _HKEX + "/search/prefix.do", error=str(exc))
    if not stock_id:
        return _block(
            "Hong Kong filings",
            _HKEX + "/search/prefix.do",
            error=f"HKEX prefix search did not return stock code {code}.",
        )

    reports = _hk_rows(get, stock_id, title="", t1code="40000", lang="zh", as_of=as_of)
    interim = _first(reports, _is_interim_report)
    annual = _first(reports, _is_annual_report)
    interim_results = _first(
        _hk_rows(get, stock_id, title="中期業績", t1code="-2", lang="zh", as_of=as_of),
        _is_interim_results,
    )
    final_results = _first(
        _hk_rows(get, stock_id, title="全年業績", t1code="-2", lang="zh", as_of=as_of),
        _is_final_results,
    )
    parts = [
        _hk_pdf("Hong Kong interim report", interim, get),
        _hk_pdf("Hong Kong annual report", annual, get),
        _hk_earnings_release(interim_results, final_results, get),
    ]
    return "\n\n".join(parts)


def _hk_code(ticker: str) -> str:
    match = re.match(r"^(\d+)\.HK$", ticker.upper())
    if not match:
        return ""
    return match.group(1).zfill(5)


def _hk_stock_id(get: _GET, code: str) -> tuple[int | None, str]:
    url = (
        f"{_HKEX}/search/prefix.do?&callback=callback&lang=ZH&type=A"
        f"&name={code}&market=SEHK"
    )
    raw = _call(get, url).decode("utf-8", errors="replace")
    payload = json.loads(raw[raw.find("(") + 1 : raw.rfind(")")])
    for item in payload.get("stockInfo") or []:
        if str(item.get("code")) == code:
            return item.get("stockId"), str(item.get("name") or "")
    return None, ""


def _hk_rows(get: _GET, stock_id: int, *, title: str, t1code: str, lang: str, as_of: str | None) -> list:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    to_date = (as_of or today).replace("-", "")
    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": str(stock_id),
        "documentType": "-1",
        "fromDate": "20190101",
        "toDate": to_date,
        "title": title,
        "searchType": "1",
        "t1code": t1code,
        "t2Gcode": "-2",
        "t2code": "-2",
        "rowRange": "100",
        "lang": lang,
    }
    url = f"{_HKEX}/search/titleSearchServlet.do?{urlencode(params)}"
    try:
        raw = _call(get, url)
        outer = json.loads(raw)
    except (FilingRequestError, json.JSONDecodeError, UnicodeError):
        return []
    result = outer.get("result") or "[]"
    if isinstance(result, str):
        try:
            rows = json.loads(html.unescape(result))
        except json.JSONDecodeError:
            return []
    else:
        rows = result
    cleaned = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in ("TITLE", "SHORT_TEXT", "LONG_TEXT", "FILE_LINK", "DATE_TIME"):
            row[key] = html.unescape(str(row.get(key) or ""))
        if as_of and _row_day(row) and _row_day(row) > as_of:
            continue
        cleaned.append(row)
    return cleaned


def _row_day(row: dict) -> str:
    raw = (row.get("DATE_TIME") or "")[:10]
    parts = raw.split("/")
    if len(parts) != 3:
        return ""
    day, month, year = parts
    return f"{year}-{month}-{day}"


def _cancelled(row: dict) -> bool:
    blob = f"{row.get('SHORT_TEXT') or ''} {row.get('LONG_TEXT') or ''} {row.get('TITLE') or ''}"
    lowered = blob.lower()
    return "cancelled" in lowered or "取消" in blob or "已被取代" in blob


def _first(rows: list, predicate) -> dict | None:
    for row in rows:
        if _cancelled(row):
            continue
        if predicate(row):
            return row
    return None


def _is_interim_report(row: dict) -> bool:
    title = row.get("TITLE") or ""
    if "業績" in title or "RESULTS" in title.upper():
        return False
    return any(token in title for token in ("中期報告", "中期报告", "Interim Report"))


def _is_annual_report(row: dict) -> bool:
    title = row.get("TITLE") or ""
    if any(token in title for token in ("中期", "Interim", "半年")):
        return False
    return any(token in title for token in ("年報", "年报", "Annual Report"))


def _is_interim_results(row: dict) -> bool:
    title = (row.get("TITLE") or "").upper()
    original = row.get("TITLE") or ""
    if "POLL" in title or "股東" in original or "股东" in original:
        return False
    return "中期業績" in original or "中期业绩" in original or "INTERIM RESULTS" in title


def _is_final_results(row: dict) -> bool:
    title = (row.get("TITLE") or "").upper()
    original = row.get("TITLE") or ""
    if "POLL" in title or "中期" in original or "INTERIM" in title:
        return False
    return "全年業績" in original or "年度業績" in original or "FINAL RESULTS" in title or "RESULTS ANNOUNCEMENT" in title


def _hk_pdf(title: str, row: dict | None, get: _GET) -> str:
    if not row:
        return _block(title, _HKEX, error=f"no {title} row in the HKEX title search.")
    link = row.get("FILE_LINK") or ""
    url = link if link.startswith("http") else f"{_HKEX}{link}"
    label = f"{title} ({row.get('TITLE') or ''} {row.get('DATE_TIME') or ''})".strip()
    return _downloaded_pdf(label, url, get)


def _hk_earnings_release(interim: dict | None, final: dict | None, get: _GET) -> str:
    row = interim or final
    if not row:
        return _block("Earnings release", _HKEX, error=EARNINGS_RELEASE_GAP)
    link = row.get("FILE_LINK") or ""
    url = link if link.startswith("http") else f"{_HKEX}{link}"
    label = f"Earnings release ({row.get('TITLE') or ''})".strip()
    return _downloaded_pdf(label, url, get)


def _downloaded_pdf(title: str, url: str, get: _GET) -> str:
    try:
        raw = _call(get, url, timeout=120)
    except FilingRequestError as exc:
        return _block(title, url, error=str(exc))
    except TypeError:
        try:
            raw = _call(get, url)
        except FilingRequestError as exc:
            return _block(title, url, error=str(exc))
    if not raw.startswith(b"%PDF"):
        return _block(title, url, error="the response was not a PDF body.")
    try:
        text = extract_pdf_text(raw)
    except Exception as exc:  # PyMuPDF raises several PDF-specific errors
        return _block(title, url, error=f"PDF text extraction failed ({type(exc).__name__}: {exc}).")
    return _block(title, url, body=excerpt_text(text))


# ---------------------------------------------------------------------------
# A-shares — cninfo, and only when the PDF body downloads
# ---------------------------------------------------------------------------

_CNINFO = "http://www.cninfo.com.cn"
_CN_HEADERS = {
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Origin": "http://www.cninfo.com.cn",
    "X-Requested-With": "XMLHttpRequest",
}


def _china_filings(ticker: str, *, as_of: str | None, get: _GET) -> str:
    code = _cn_code(ticker)
    if not code:
        return _block("A-share periodic reports", _CNINFO, error=f"{ticker} has no A-share code.")
    try:
        org = _cn_org(get, code)
    except (FilingRequestError, json.JSONDecodeError, UnicodeError) as exc:
        return _block("A-share periodic reports", _CNINFO, error=str(exc))
    if not org:
        return _block(
            "A-share periodic reports",
            _CNINFO + "/new/information/topSearch/query",
            error=f"cninfo did not return an exact code match for {code}.",
        )
    column, plate = _cn_board(code)
    try:
        rows = _cn_announcements(get, code, org, column, plate)
    except (FilingRequestError, json.JSONDecodeError, UnicodeError) as exc:
        return _block("A-share periodic reports", _CNINFO + "/new/hisAnnouncement/query", error=str(exc))

    annual = _first_cn(rows, ("年度报告",), skip=("半年度", "季度"), as_of=as_of)
    interim = _first_cn(rows, ("半年度报告", "半年度報告"), skip=(), as_of=as_of)
    quarterly = _first_cn(rows, ("季度报告", "季度報告"), skip=(), as_of=as_of)
    parts = [
        _cn_pdf("A-share annual report", annual, get),
        _cn_pdf("A-share interim report", interim or quarterly, get),
    ]
    # A separate earnings release is attached only when its own body downloads.
    release = _first_cn(rows, ("业绩快报", "業績快報"), skip=(), as_of=as_of)
    if release:
        parts.append(_cn_pdf("Earnings release", release, get))
    else:
        parts.append(_block("Earnings release", _CNINFO, error=EARNINGS_RELEASE_GAP))
    return "\n\n".join(parts)


def _cn_code(ticker: str) -> str:
    match = re.match(r"^(\d+)\.(SS|SZ|BJ)$", ticker.upper())
    if not match:
        return ""
    return match.group(1).zfill(6)


def _cn_board(code: str) -> tuple[str, str]:
    if code.startswith(("0", "3")):
        return "szse", "sz"
    if code.startswith(("4", "8")):
        return "bj", "bj"
    return "sse", "sh"


def _cn_org(get: _GET, code: str) -> str:
    raw = _call(
        get,
        _CNINFO + "/new/information/topSearch/query",
        data=urlencode({"keyWord": code, "maxNum": "10"}).encode(),
        headers=_CN_HEADERS,
    )
    rows = json.loads(raw)
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("code")) == code:
            return str(row.get("orgId") or "")
    return ""


def _cn_announcements(get: _GET, code: str, org: str, column: str, plate: str) -> list:
    form = {
        "pageNum": "1",
        "pageSize": "30",
        "column": column,
        "tabName": "fulltext",
        "plate": plate,
        "stock": f"{code},{org}",
        "searchkey": "",
        "secid": "",
        "category": "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh",
        "trade": "",
        "seDate": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    raw = _call(
        get,
        _CNINFO + "/new/hisAnnouncement/query",
        data=urlencode(form).encode(),
        headers=_CN_HEADERS,
    )
    payload = json.loads(raw)
    return payload.get("announcements") or []


def _first_cn(rows: list, needles: tuple[str, ...], *, skip: tuple[str, ...], as_of: str | None) -> dict | None:
    matches = []
    for row in rows:
        title = str(row.get("announcementTitle") or "")
        if any(token in title for token in skip):
            continue
        if not any(token in title for token in needles):
            continue
        stamped = _cn_day(row)
        if as_of and stamped and stamped > as_of:
            continue
        matches.append(row)
    full = [row for row in matches if "摘要" not in str(row.get("announcementTitle") or "")]
    chosen = full or matches
    return chosen[0] if chosen else None


def _cn_day(row: dict) -> str:
    millis = row.get("announcementTime")
    if not isinstance(millis, (int, float)):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _cn_pdf(title: str, row: dict | None, get: _GET) -> str:
    if not row:
        return _block(title, _CNINFO, error=f"cninfo did not list a downloadable {title}.")
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        return _block(title, _CNINFO, error="cninfo row had no adjunct URL.")
    url = f"https://static.cninfo.com.cn/{adjunct}"
    label = f"{title} ({row.get('announcementTitle') or ''})"
    return _downloaded_pdf(label, url, get)


def resolve_cninfo_symbol(name: str, *, get: _GET | None = None) -> str | None:
    """Map an exact cninfo short name to a Yahoo symbol. No fuzzy matches."""
    getter = get or default_get
    try:
        raw = _call(
            getter,
            _CNINFO + "/new/information/topSearch/query",
            data=urlencode({"keyWord": name, "maxNum": "10"}).encode(),
            headers=_CN_HEADERS,
        )
        rows = json.loads(raw)
    except (FilingRequestError, json.JSONDecodeError, UnicodeError, TypeError):
        return None
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("zwjc") or "") != name:
            continue
        code = str(row.get("code") or "")
        suffix = _yahoo_suffix(code)
        if code and suffix:
            return f"{code}.{suffix}"
    return None


def _yahoo_suffix(code: str) -> str:
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("6", "9")):
        return "SS"
    return ""
