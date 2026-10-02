"""Deep single-stock notes must attempt the shareholder and management layers.

The checklist lives in docs/deep-note-harness.md. These tests lock the prompt
fragments and the agent call sites so a later edit cannot turn the two layers
back into optional color.
"""

from pathlib import Path

import pytest

from tradingagents.agents.utils.deep_note import (
    GAPS_HEADING,
    MANAGEMENT_HEADING,
    SHAREHOLDER_HEADING,
    downstream_instruction,
    market_gap_instruction,
    news_layer_instruction,
    non_stock_gap_instruction,
    stock_layer_instruction,
)

_ROOT = Path(__file__).resolve().parents[1]

# Agent module -> fragment function it must call.
_CALL_SITES = {
    "tradingagents/agents/analysts/fundamentals_analyst.py": "stock_layer_instruction()",
    "tradingagents/agents/analysts/news_analyst.py": "news_layer_instruction(",
    "tradingagents/agents/analysts/market_analyst.py": "market_gap_instruction()",
    "tradingagents/agents/researchers/bull_researcher.py": "downstream_instruction()",
    "tradingagents/agents/researchers/bear_researcher.py": "downstream_instruction()",
    "tradingagents/agents/managers/research_manager.py": "downstream_instruction()",
}


@pytest.mark.unit
def test_stock_layers_are_required_and_attributed():
    text = stock_layer_instruction()
    assert SHAREHOLDER_HEADING in text
    assert MANAGEMENT_HEADING in text
    assert GAPS_HEADING in text
    assert "13D" in text and "13F" in text
    assert "SEC EDGAR" in text
    assert "SEDAR+" in text
    assert "GlobeNewswire" in text
    assert "Motley Fool" in text
    assert "secondary" in text
    assert "Never invent" in text
    assert "no orders" in text
    assert "management-*.md" in text
    # Known egress fallbacks stay next to the Gap rule.
    assert "Akamai" in text
    assert "EX-99" in text
    assert "Do not retry or hammer the CDN" in text
    assert "stockanalysis" in text
    assert "transcripts/" in text
    assert "FRED" in text
    assert "GCS" in text
    assert "YTD" in text
    assert "sell-side NAV" in text


@pytest.mark.unit
def test_news_stock_pass_attempts_both_layers_and_gaps_empty_sources():
    text = news_layer_instruction("stock")
    assert SHAREHOLDER_HEADING in text
    assert MANAGEMENT_HEADING in text
    assert "get_insider_transactions" in text
    assert "do not invent headlines" in text.lower() or "Do not invent headlines" in text
    assert "get_fred_key_series" in text
    assert "FRED" in text
    assert "Akamai" in text
    assert "stockanalysis" in text
    assert "transcripts/" in text
    assert "empty" in text.lower()


@pytest.mark.unit
def test_non_stock_does_not_require_a_controller_pack():
    text = news_layer_instruction("crypto")
    assert text == non_stock_gap_instruction()
    assert SHAREHOLDER_HEADING not in text
    assert "Do not invent a shareholder" in text
    assert GAPS_HEADING in text


@pytest.mark.unit
def test_market_and_downstream_keep_gaps_unknown():
    assert GAPS_HEADING in market_gap_instruction()
    assert "YTD" in market_gap_instruction()
    assert "Dividend yield" in market_gap_instruction()
    assert "Do not invent" in market_gap_instruction()
    downstream = downstream_instruction()
    assert SHAREHOLDER_HEADING in downstream
    assert MANAGEMENT_HEADING in downstream
    assert "unknown" in downstream
    assert "Do not invent" in downstream


@pytest.mark.unit
def test_harness_doc_covers_checklist_and_egress():
    doc = (_ROOT / "docs" / "deep-note-harness.md").read_text(encoding="utf-8")
    for step in (
        "Market data",
        "Filings",
        "Shareholder",
        "Management commentary",
        "Peers",
        "TA graph",
        "Gaps",
        "residue",
    ):
        assert step in doc
    assert "Akamai" in doc
    assert "GlobeNewswire" in doc
    assert "GCS" in doc
    assert "FRED" in doc
    assert "do not invent" in doc.lower() or "Do not invent" in doc
    assert "research" in doc.lower()
    assert "management-and-pershing.md" in doc
    assert "SOURCES.md" in doc
    assert "get_fred_key_series" in doc
    assert "calendar YTD" in doc
    assert "dividendYield" in doc
    assert "Do not retry" in doc or "do not retry" in doc.lower()
    assert "stockanalysis" in doc
    assert "transcripts/" in doc


@pytest.mark.unit
@pytest.mark.parametrize("rel,needle", list(_CALL_SITES.items()))
def test_agent_prompts_call_deep_note_fragment(rel, needle):
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert needle in src, f"{rel} does not apply {needle}"


@pytest.mark.unit
def test_news_analyst_binds_fred_key_series():
    src = (_ROOT / "tradingagents/agents/analysts/news_analyst.py").read_text(encoding="utf-8")
    assert "get_fred_key_series" in src
    graph = (_ROOT / "tradingagents/graph/trading_graph.py").read_text(encoding="utf-8")
    assert "get_fred_key_series" in graph


@pytest.mark.unit
def test_ir_block_records_url_and_does_not_fetch():
    from tradingagents.agents.utils.deep_note_sources import ir_cdn_gap, looks_like_cdn_block

    url = "https://ir.example/news/release"
    line = ir_cdn_gap(url, "Akamai 403")
    assert line.startswith("Gap:")
    assert url in line
    assert "Do not retry or hammer the CDN" in line
    assert "EX-99" in line
    assert looks_like_cdn_block("AkamaiGHost edgesuite.net denied")
    assert not looks_like_cdn_block("connection reset by peer")


@pytest.mark.unit
def test_transcript_secondary_only_is_a_gap_and_saves_under_transcripts(tmp_path):
    from tradingagents.agents.utils.deep_note_sources import (
        assess_transcript_sources,
        save_retrieved_transcript,
        transcript_destination,
    )

    assert assess_transcript_sources([]).startswith("Gap:")
    only_fool = assess_transcript_sources(["Motley Fool"])
    assert only_fool.startswith("Gap:")
    assert "secondary" in only_fool
    quartr = assess_transcript_sources(["Quartr"])
    assert not quartr.startswith("Gap:")
    mixed = assess_transcript_sources(["company IR", "Motley Fool"])
    assert not mixed.startswith("Gap:")

    dest = transcript_destination("HHH", "2026-08-07", "company IR")
    assert dest == "transcripts/hhh/2026-08-07-company-ir.md"
    saved = save_retrieved_transcript(
        tmp_path, "SHOP", "2026-05-06", "Quartr", "CEO: we grew GMV."
    )
    assert saved.parent.parent.name == "transcripts"
    assert saved.read_text(encoding="utf-8").startswith("CEO:")
    with pytest.raises(ValueError, match="Gap:"):
        save_retrieved_transcript(tmp_path, "SHOP", "2026-05-06", "Quartr", "  ")
