"""Filing text reaches the research manager, transcripts gap, peers stay caller-supplied."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pymupdf
import pytest

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import PortfolioRating, ResearchPlan
from tradingagents.agents.utils.deep_research_note import (
    HEADINGS,
    compose_deep_research_note,
    section_body,
)
from tradingagents.agents.utils.local_fundamental_pack import build_local_fundamental_pack
from tradingagents.agents.utils.peer_table import (
    build_peer_table,
    load_peer_names,
    parse_peer_line,
)
from tradingagents.dataflows.company_filings import (
    TRANSCRIPT_GAP,
    fetch_company_filings,
)

_FILING = (
    "我们的总收入增至人民币3,267.3百万元。"
    "我们的净利润增至人民币806.6百万元。"
)
_YFINANCE = "YFINANCE_ONLY price 999.99 revenue was not in a filing."
_INVENTED_PEER = "Imaginary Peer Ltd"


def _state(**overrides):
    state = {
        "company_of_interest": "1318.HK",
        "fundamentals_report": "",
        "local_fundamental_pack": "",
        "company_filings": "",
        "peer_table": "",
        "peer_names": "",
        "news_report": "",
        "market_report": "",
        "investment_debate_state": {
            "history": "Bull Analyst: growth. Bear Analyst: competition.",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 2,
        },
    }
    state.update(overrides)
    return state


def _llm(plan: ResearchPlan, captured: dict):
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or plan
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _plan(rating: PortfolioRating, rationale: str) -> ResearchPlan:
    return ResearchPlan(
        recommendation=rating,
        rationale=rationale,
        strategic_actions="Keep the existing position size.",
    )


@pytest.mark.unit
def test_filing_text_reaches_the_manager_and_the_fundamentals_section():
    captured = {}
    filings = (
        "### Hong Kong interim report\nSource: https://www1.hkexnews.hk/example.pdf\n"
        + _FILING
        + "\n\n### Earnings transcript\n"
        + TRANSCRIPT_GAP
    )
    peers = "珀莱雅\n上海家化\n贝泰妮\n丸美股份"
    table = (
        "| Peer | Public financials | Current valuation | Price trend |\n"
        "| --- | --- | --- | --- |\n"
        "| 珀莱雅 (603605.SS) | Gap: the public quote has no statement figures. "
        "| Public price: 54.7 CNY | 6-month public closes 61.51 → 54.70 CNY |"
    )
    llm = _llm(_plan(PortfolioRating.HOLD, f"Balanced. {_INVENTED_PEER} is irrelevant."), captured)
    result = create_research_manager(llm)(_state(
        fundamentals_report=_YFINANCE,
        company_filings=filings,
        peer_table=table,
        peer_names=peers,
    ))
    prompt = captured["prompt"]
    note = result["investment_plan"]
    assert prompt.index(_FILING) < prompt.index("**Debate History:**")
    assert "3,267.3" in prompt and "806.6" in prompt
    assert note.startswith(HEADINGS[0])
    for earlier, later in zip(HEADINGS, HEADINGS[1:], strict=False):
        assert note.index(earlier) < note.index(later)
    fundamentals = section_body(note, 1)
    assert "3,267.3" in fundamentals
    assert "806.6" in fundamentals
    assert "YFINANCE_ONLY" not in fundamentals
    assert "999.99" not in fundamentals
    peers_section = section_body(note, 3)
    assert "珀莱雅" in peers_section
    assert _INVENTED_PEER not in peers_section
    assert "Company fundamentals" in section_body(note, 5)
    assert "珀莱雅" in section_body(note, 5)


@pytest.mark.unit
def test_missing_transcript_is_recorded_as_a_gap():
    filings = fetch_company_filings(
        "AAPL",
        as_of="2026-08-01",
        transcript_text="",
        get=_sec_get,
    )
    assert TRANSCRIPT_GAP in filings
    assert "Net sales were 100 million" in filings
    note = compose_deep_research_note(company_filings=filings, manager_plan="**Recommendation**: Hold")
    fundamentals = section_body(note, 1)
    assert TRANSCRIPT_GAP in fundamentals
    assert "Do not invent quotes." in fundamentals
    assert "Net sales were 100 million" in fundamentals


@pytest.mark.unit
def test_caller_supplied_peer_list_is_not_extended_by_the_model(tmp_path):
    (tmp_path / "peers.txt").write_text(
        "珀莱雅\n上海家化\n贝泰妮\n# comment\n",
        encoding="utf-8",
    )
    names = load_peer_names(research_dir=tmp_path)
    assert names == ["珀莱雅", "上海家化", "贝泰妮"]
    display, ticker = parse_peer_line("珀莱雅 603605.SS")
    assert display == "珀莱雅"
    assert ticker == "603605.SS"

    def resolve(name, explicit, get=None):
        return (explicit or "603605.SS"), ""

    def quote(symbol, get=None):
        return {
            "price": "54.7 CNY",
            "valuation": "Public price: 54.7 CNY",
            "trend": "6-month public closes 61.51 → 54.70 CNY",
            "financials": "",
        }

    table = build_peer_table(names, resolve=resolve, quote=quote)
    assert "珀莱雅" in table
    assert "54.7 CNY" in table
    assert _INVENTED_PEER not in table
    assert "Gap: caller supplied 3 peers" not in table

    short = build_peer_table(["珀莱雅"], resolve=resolve, quote=quote)
    assert "caller supplied 1 peers" in short
    assert "珀莱雅" in short
    assert _INVENTED_PEER not in short

    flagged = "--peers list\n" + _INVENTED_PEER
    cli_names = load_peer_names(peers="珀莱雅,上海家化,贝泰妮,丸美股份")
    assert cli_names == ["珀莱雅", "上海家化", "贝泰妮", "丸美股份"]
    assert flagged not in "\n".join(cli_names)


@pytest.mark.unit
def test_local_pdf_text_reaches_the_pack_and_a_junk_pdf_does_not(tmp_path):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Revenue was 8.0 million\nProfit for the period was 1.5 million\n")
    document.save(tmp_path / "interim.pdf")
    document.close()
    (tmp_path / "ignore.pdf").write_bytes(b"%PDF-1.4 PDF_ONLY_MARKER revenue 9999")
    pack = build_local_fundamental_pack(tmp_path)
    assert "Revenue was 8.0 million" in pack
    assert "1.5 million" in pack
    assert "PDF_ONLY_MARKER" not in pack


@pytest.mark.unit
def test_us_filing_html_is_quoted_and_a_missing_exhibit_is_a_gap():
    text = fetch_company_filings("AAPL", as_of="2026-08-01", get=_sec_get)
    assert "### US 10-Q" in text
    assert "### US 10-K" in text
    assert "Net sales were 100 million" in text
    assert "Net income was 20 million" in text
    assert "no EX-99" in text


def _sec_get(url, **kwargs):
    if url.endswith("company_tickers.json"):
        return json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}).encode()
    if "submissions/CIK" in url:
        return json.dumps({
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K", "10-K"],
                    "filingDate": ["2026-07-31", "2026-07-30", "2025-10-31"],
                    "accessionNumber": [
                        "0000320193-26-000020",
                        "0000320193-26-000018",
                        "0000320193-25-000079",
                    ],
                    "primaryDocument": ["aapl-q.htm", "aapl-8k.htm", "aapl-k.htm"],
                }
            }
        }).encode()
    if url.endswith("aapl-q.htm"):
        return b"<html><body><p>Net sales were 100 million.</p></body></html>"
    if url.endswith("aapl-k.htm"):
        return b"<html><body><p>Net income was 20 million.</p></body></html>"
    if url.endswith("index.json"):
        return json.dumps({"directory": {"item": [{"name": "aapl-8k.htm"}]}}).encode()
    raise AssertionError(url)
