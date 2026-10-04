"""Deep-research note. The section order is fixed.

1. Company fundamentals — exchange filing text, or a gap.
2. Industry.
3. Comparable companies — the caller-supplied peer table.
4. Financials — figures quoted from the filing.
5. Trading conditions, the bull and bear case, and buy/sell timing.

The recommendation sits in section 5. It points back to Company fundamentals
and to one caller-supplied peer. Momentum is timing context only.
"""

from __future__ import annotations

import re

from tradingagents.dataflows.company_filings import excerpt_text, industry_window

HEADINGS = (
    "## 1. Company fundamentals",
    "## 2. Industry",
    "## 3. Comparable companies",
    "## 4. Financials",
    "## 5. Trading conditions, the bull and bear case, and buy/sell timing",
)

_NO_FILING = (
    "Gap: no exchange filing text was retrieved. "
    "Do not fill this section with price, quotes, or yfinance."
)
_NO_PEERS = (
    "Gap: no caller-supplied peer list. Comparable companies are not invented."
)


def section_body(note: str, number: int) -> str:
    """Text of section ``number`` (1-based), including its heading."""
    heading = HEADINGS[number - 1]
    start = note.index(heading)
    if number == len(HEADINGS):
        return note[start:]
    end = note.index(HEADINGS[number])
    return note[start:end]


def compose_deep_research_note(
    *,
    company_filings: str = "",
    local_pack: str = "",
    peer_table: str = "",
    peer_names: list[str] | None = None,
    debate: str = "",
    news_report: str = "",
    news_empty: bool = False,
    market_report: str = "",
    manager_plan: str = "",
) -> str:
    """Assemble the note. Section 1 is filing text. Section 3 is the peer table."""
    names = [name.strip() for name in (peer_names or []) if name and name.strip()]
    parts = [
        _fundamentals(company_filings, local_pack),
        _industry(company_filings, news_report),
        _peers(peer_table),
        _financials(company_filings),
        _trading(
            debate=debate,
            news_report=news_report,
            news_empty=news_empty,
            market_report=market_report,
            manager_plan=manager_plan,
            peer_names=names,
        ),
    ]
    return "\n\n".join(parts).strip() + "\n"


def recommendation_sentence(rating: str, peer_names: list[str]) -> str:
    """Point the rating at the fundamentals section and one supplied peer."""
    stance = rating or "Hold"
    if peer_names:
        return (
            f"Recommendation: {stance}. This recommendation points back to the "
            f"Company fundamentals section and to the named peer {peer_names[0]}. "
            "Momentum and technical indicators address timing only and are not the sole basis."
        )
    return (
        f"Recommendation: {stance}. This recommendation points back to the "
        "Company fundamentals section. Gap: no caller-supplied peer to name. "
        "Do not invent one. Momentum and technical indicators address timing only "
        "and are not the sole basis."
    )


def _useful(text: str) -> bool:
    body = (text or "").strip()
    gap_only = body.startswith("Gap:") and "### " not in body and len(body) < 600
    return bool(body) and not gap_only


def _fundamentals(company_filings: str, local_pack: str) -> str:
    chunks = [HEADINGS[0]]
    if _useful(company_filings):
        chunks.append(company_filings.strip())
    else:
        chunks.append(_NO_FILING)
    if _useful(local_pack):
        chunks.append("### Local research directory\n" + local_pack.strip())
    return "\n\n".join(chunks)


def _industry(company_filings: str, news_report: str) -> str:
    chunks = [HEADINGS[1]]
    window = industry_window(company_filings) if _useful(company_filings) else ""
    if window:
        chunks.append("Quoted from the exchange filing:\n\n" + window)
    else:
        chunks.append(
            "Gap: no public industry discussion was in the retrieved filing. "
            "Do not invent an industry overview."
        )
    macro = _macro_lines(news_report)
    if macro:
        chunks.append(macro)
    else:
        chunks.append(
            "Gap: no public macro source was attached to this note. Do not invent macro prints."
        )
    return "\n\n".join(chunks)


def _peers(peer_table: str) -> str:
    body = peer_table.strip() if peer_table and peer_table.strip() else _NO_PEERS
    return f"{HEADINGS[2]}\n\n{body}"


def _financials(company_filings: str) -> str:
    quoted = excerpt_text(company_filings, limit=2500) if _useful(company_filings) else ""
    if quoted and not quoted.startswith("Gap:"):
        body = "Quoted from the exchange filing text, not calculated.\n\n" + quoted
    else:
        body = (
            "Gap: no filing financials were retrieved. "
            "Do not fill this section with yfinance statements."
        )
    return f"{HEADINGS[3]}\n\n{body}"


def _trading(
    *,
    debate: str,
    news_report: str,
    news_empty: bool,
    market_report: str,
    manager_plan: str,
    peer_names: list[str],
) -> str:
    case = (debate or "").strip()
    if not case:
        case = "Gap: the bull and bear case was not in the debate record."
    if (market_report or "").strip():
        timing = (
            "Timing context only. Momentum and technical indicators are not the sole "
            "basis of the recommendation.\n\n"
            + market_report.strip()[:1000]
        )
    else:
        timing = (
            "Gap: no market report was attached for timing. "
            "Momentum and technical indicators are not the sole basis of the recommendation."
        )
    news = _news_block(news_report, news_empty)
    plan = (manager_plan or "").strip() or "Gap: the research manager returned no plan text."
    rating = _rating_from_plan(plan)
    sentence = recommendation_sentence(rating, peer_names)
    return "\n\n".join([
        HEADINGS[4],
        "Bull and bear case:\n" + case,
        timing,
        news,
        plan,
        sentence,
    ])


def _news_block(news_report: str, news_empty: bool) -> str:
    text = (news_report or "").strip()
    if news_empty or not text or text == "NEWS_EMPTY":
        return (
            "Gap: no public news or material-event source. Do not invent headlines."
        )
    return "Material events from the retrieved news source:\n" + text[:1200]


def _macro_lines(news_report: str) -> str:
    lines = []
    for line in (news_report or "").splitlines():
        if "FRED" in line or "fed funds" in line.lower():
            lines.append(line.strip())
    return "\n".join(lines[:12])


def _rating_from_plan(plan: str) -> str:
    match = re.search(
        r"\*\*Recommendation\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)\b",
        plan or "",
    )
    if match:
        return match.group(1)
    return "Hold"
