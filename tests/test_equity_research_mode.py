"""Research-mode graph, NEWS_EMPTY, YTD helper, and the deep-note CLI."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
from langgraph.graph import END

import tradingagents.dataflows.config as config_module
import tradingagents.dataflows.market_data_validator as validator
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_empty import (
    NEWS_VENDOR_ORDER,
    detect_news_empty,
    news_payload_is_empty,
)
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.research_mode import risk_truncated_node
from tradingagents.graph.setup import GraphSetup
from tradingagents.llm_clients.model_catalog import (
    resolve_deep_think_model,
    resolve_quick_think_model,
)

_ROOT = Path(__file__).resolve().parents[1]


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


class _Msg:
    def __init__(self, name, content):
        self.name = name
        self.content = content


def _ohlc(dates, closes) -> pd.DataFrame:
    stamps = pd.to_datetime(list(dates))
    return pd.DataFrame({
        "Date": stamps,
        "Open": closes,
        "High": closes,
        "Low": closes,
        "Close": closes,
        "Volume": [1] * len(closes),
    })


@pytest.mark.unit
def test_research_mode_ends_after_research_manager_and_full_graph_keeps_trader():
    logic = ConditionalLogic()
    assert logic.route_after_research_manager({"research_mode": True}) == END
    assert logic.route_after_research_manager({"research_mode": False}) == "Trader"
    assert logic.route_after_research_manager({}) == "Trader"

    state = Propagator().create_initial_state("HHH", "2026-10-02", research_mode=True)
    assert state["research_mode"] is True
    assert logic.route_after_research_manager(state) == END
    plain = Propagator().create_initial_state("HHH", "2026-10-02")
    assert plain["research_mode"] is False
    assert plain["news_empty"] is False


@pytest.mark.unit
def test_compiled_graph_keeps_trading_nodes_and_can_stop_after_research_manager():
    def _tool(state):
        return state

    tools = dict.fromkeys(("market", "social", "news", "fundamentals"), _tool)
    workflow = GraphSetup(object(), object(), tools, ConditionalLogic()).setup_graph(("market",))
    compiled = workflow.compile()
    drawing = compiled.get_graph()
    pairs = {(edge.source, edge.target) for edge in drawing.edges}
    assert ("Research Manager", END) in pairs
    assert ("Research Manager", "Trader") in pairs
    assert ("Trader", "Aggressive Analyst") in pairs
    assert ("Trader", "Risk Truncated") in pairs
    assert ("Risk Truncated", END) in pairs
    assert ("Portfolio Manager", END) in pairs


@pytest.mark.unit
def test_news_empty_shortens_debate_and_skips_risk():
    logic = ConditionalLogic(max_debate_rounds=5, max_risk_discuss_rounds=3)
    empty = {
        "news_empty": True,
        "investment_debate_state": {"count": 2, "current_response": "Bull Analyst: short"},
        "risk_debate_state": {"count": 0, "latest_speaker": ""},
    }
    assert logic.should_continue_debate(empty) == "Research Manager"
    assert logic.route_after_trader(empty) == "Risk Truncated"
    assert logic.should_continue_risk_analysis(empty) == "Portfolio Manager"

    full = {
        "news_empty": False,
        "investment_debate_state": {"count": 2, "current_response": "Bull Analyst: more"},
        "risk_debate_state": {"count": 0, "latest_speaker": ""},
    }
    assert logic.should_continue_debate(full) == "Bear Researcher"
    assert logic.route_after_trader(full) == "Aggressive Analyst"

    note = risk_truncated_node({"risk_debate_state": {"count": 0}})
    assert note["final_trade_decision"].startswith("NEWS_EMPTY:")
    assert "Do not invent headlines" in note["final_trade_decision"]
    assert "research only" in note["final_trade_decision"]


@pytest.mark.unit
def test_detect_news_empty_from_vendor_text():
    assert detect_news_empty([_Msg("get_news", "No news found for HHH")])
    assert detect_news_empty([
        _Msg("get_news", "NEWS_EMPTY: No news found for HHH after trying yfinance. Do not invent headlines.")
    ])
    assert not detect_news_empty([
        _Msg("get_news", "## HHH News, from 2026-01-01 to 2026-01-08:\n\n### Real headline\n")
    ])
    assert not news_payload_is_empty('{"feed": [{"title": "Real headline"}]}')
    assert news_payload_is_empty('{"feed": []}')
    assert news_payload_is_empty(
        "<Eastmoney news not applicable for HHH: not a Chinese/HK market symbol>"
    )


@pytest.mark.unit
def test_news_falls_back_before_news_empty_and_does_not_invent_headlines():
    _reset_config()
    try:
        yf = mock.Mock(return_value="No news found for HHH")
        av = mock.Mock(
            return_value="## HHH News, from 2026-01-01 to 2026-01-08:\n\n### Real headline\n"
        )
        ak = mock.Mock(return_value="unused")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {"yfinance": yf, "alpha_vantage": av, "akshare": ak}},
        ):
            hit = interface.route_to_vendor("get_news", "HHH", "2026-01-01", "2026-01-08")
        assert "Real headline" in hit
        assert not hit.startswith("NEWS_EMPTY")
        ak.assert_not_called()

        yf2 = mock.Mock(return_value="No news found for HHH")
        av2 = mock.Mock(return_value="Error fetching news for HHH: 401")
        ak2 = mock.Mock(
            return_value="<Eastmoney news not applicable for HHH: not a Chinese/HK market symbol>"
        )
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {"yfinance": yf2, "alpha_vantage": av2, "akshare": ak2}},
        ):
            empty = interface.route_to_vendor("get_news", "HHH", "2026-01-01", "2026-01-08")
        assert empty.startswith("NEWS_EMPTY:")
        assert "Do not invent headlines" in empty
        assert "yfinance, alpha_vantage, akshare" in empty
        assert "### " not in empty
        yf2.assert_called_once()
        av2.assert_called_once()
        ak2.assert_called_once()

        set_config({"data_vendors": {"news_data": "yfinance"}})
        yf3 = mock.Mock(return_value="No news found for HHH")
        av3 = mock.Mock(return_value="## HHH News\n\n### Should not run\n")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {"yfinance": yf3, "alpha_vantage": av3, "akshare": mock.Mock()}},
        ):
            only = interface.route_to_vendor("get_news", "HHH", "2026-01-01", "2026-01-08")
        assert only.startswith("NEWS_EMPTY:")
        av3.assert_not_called()
    finally:
        _reset_config()


@pytest.mark.unit
def test_default_news_vendor_order_is_yahoo_then_alpha_vantage_then_akshare():
    assert default_config.DEFAULT_CONFIG["data_vendors"]["news_data"].split(",") == list(
        NEWS_VENDOR_ORDER
    )


@pytest.mark.unit
def test_ytd_helper_on_synthetic_series(monkeypatch):
    frame = _ohlc(["2026-01-02", "2026-03-02"], [100.0, 110.0])
    line = validator.format_calendar_ytd(frame, "2026-03-02")
    assert "+10.00%" in line
    assert "first close of year 100.00 on 2026-01-02" in line
    assert "close 110.00 on 2026-03-02" in line

    def _raise(_fn):
        raise RuntimeError("HTTP Error 401: Unauthorized")

    monkeypatch.setattr(validator, "yf_retry", _raise)
    status, value = validator.lookup_yahoo_ytd_return("HHH")
    assert status == "empty" and value is None

    monkeypatch.setattr(validator, "lookup_yahoo_ytd_return", lambda symbol: ("empty", None))
    filled = validator.format_verified_ytd(frame, "2026-03-02", "HHH")
    assert "+10.00%" in filled
    assert "401" in filled
    assert not filled.startswith("—")

    monkeypatch.setattr(validator, "lookup_yahoo_ytd_return", lambda symbol: ("ok", 0.25))
    yahoo = validator.format_verified_ytd(frame, "2026-03-02", "HHH")
    assert yahoo.startswith("+25.00%")
    assert "ytdReturn" in yahoo

    missing = validator.format_calendar_ytd(
        _ohlc(["2025-12-31"], [50.0]), "2026-05-01"
    )
    assert missing.startswith("— (Gap:")
    assert "2026" in missing


@pytest.mark.unit
def test_deepseek_flash_is_the_quick_default_only_for_deepseek():
    assert resolve_quick_think_model("deepseek", "deepseek-flash") == "deepseek-v4-flash"
    assert resolve_quick_think_model("deepseek", "gpt-5.4-mini") == "deepseek-v4-flash"
    assert resolve_quick_think_model("deepseek", None) == "deepseek-v4-flash"
    assert resolve_quick_think_model("deepseek", "deepseek-v4-pro") == "deepseek-v4-pro"
    assert resolve_quick_think_model("openai", "gpt-5.4-mini") == "gpt-5.4-mini"
    assert resolve_deep_think_model("deepseek", "gpt-5.5") == "deepseek-v4-pro"
    assert resolve_deep_think_model("deepseek", "deepseek-v4-flash") == "deepseek-v4-flash"

    from tradingagents.cli.deep_note import build_deep_note_config

    cfg = build_deep_note_config()
    assert cfg["research_mode"] is True
    assert cfg["llm_provider"] == "deepseek"
    assert cfg["quick_think_llm"] == "deepseek-v4-flash"
    assert cfg["deep_think_llm"] == "deepseek-v4-pro"


@pytest.mark.unit
def test_deep_note_cli_help():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "tradingagents.cli", "deep-note", "--help"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "--ticker" in out
    assert "--date" in out
    assert "--out" in out
    assert "--research-dir" in out
    assert "deepseek-flash" in out
    assert "research" in out.lower()
    assert "order" in out.lower()


@pytest.mark.unit
def test_note_template_puts_gaps_and_holders_first():
    doc = (_ROOT / "docs" / "deep-note-harness.md").read_text(encoding="utf-8")
    skeleton = doc.split("## Skeleton", 1)[1]
    gaps = skeleton.index("## Gaps")
    holder = skeleton.index("## Controlling / major shareholder")
    voice = skeleton.index("## Management / strategy voice")
    peers = skeleton.index("## Peers")
    assert gaps < holder < voice < peers
    assert "yfinance → alpha_vantage → akshare" in doc or "yfinance, alpha_vantage, akshare" in doc
    assert "research_mode" in doc
    assert "deepseek-flash" in doc

    html = (_ROOT / "docs" / "templates" / "deep-note-skeleton.html").read_text(encoding="utf-8")
    assert html.index("Exhibit 1 · Gaps") < html.index("Controlling / major shareholder")
    assert html.index("Controlling / major shareholder") < html.index("Management / strategy")
    assert "not a Morgan Stanley" in html
    assert "do not invent a headline" in html.lower() or "Do not invent" in html
