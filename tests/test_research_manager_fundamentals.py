"""Research manager receives fundamentals, and an optional local text pack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import PortfolioRating, ResearchPlan
from tradingagents.agents.utils.local_fundamental_pack import (
    build_local_fundamental_pack,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.propagation import Propagator

_ROOT = Path(__file__).resolve().parents[1]

# Synthetic figures only. Not a filing.
_REPORT = (
    "Revenue was 12.5 million. Profit for the period was 3.0 million."
)
_PRICE_DEBATE = (
    "Bull Analyst: the price is above the 50-day moving average. "
    "Bear Analyst: the price is under the 200-day moving average."
)
_MA_DEBATE = (
    "Bull Analyst: the 50-day moving average is rising. "
    "Bear Analyst: the 200-day moving average is rolling over."
)


def _state(**overrides):
    state = {
        "company_of_interest": "HHH",
        "fundamentals_report": "",
        "local_fundamental_pack": "",
        "investment_debate_state": {
            "history": "Bull and bear arguments here.",
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


def _recommendation(plan_text: str) -> str:
    for line in plan_text.splitlines():
        if line.startswith("**Recommendation**:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no recommendation line in {plan_text!r}")


@pytest.mark.unit
def test_manager_prompt_includes_fundamentals_report():
    captured = {}
    llm = _llm(_plan(PortfolioRating.HOLD, "Balanced."), captured)
    report = "FUND_MARKER " + _REPORT
    create_research_manager(llm)(_state(fundamentals_report=report))
    prompt = captured["prompt"]
    assert "fundamentals_report" in prompt
    assert report in prompt
    assert "FUND_MARKER" in prompt


@pytest.mark.unit
def test_research_dir_pack_is_short_and_reaches_the_manager(tmp_path):
    (tmp_path / "SOURCES.md").write_text(
        "Synthetic source index. No filing attached.\n", encoding="utf-8"
    )
    (tmp_path / "interim-note.txt").write_text(
        "Revenue was 12.5 million.\nProfit for the period was 3.0 million.\n",
        encoding="utf-8",
    )
    (tmp_path / "ignore.pdf").write_bytes(b"%PDF-1.4 PDF_ONLY_MARKER revenue 9999")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.txt").write_text(
        "NESTED_ONLY revenue was 99.0 million.\n", encoding="utf-8"
    )
    filler = "The weather was fine and WEATHER_FILLER_TOKEN stayed put.\n" * 80
    (tmp_path / "interim-long.txt").write_text(
        filler
        + "营业收入为 10.0 百万元。\n"
        + "期内利润为 2.0 百万元。\n"
        + filler,
        encoding="utf-8",
    )

    pack = build_local_fundamental_pack(tmp_path)
    assert "Synthetic source index" in pack
    assert "Revenue was 12.5 million" in pack
    assert "Profit for the period was 3.0 million" in pack
    assert "营业收入为 10.0 百万元" in pack
    assert "期内利润为 2.0 百万元" in pack
    assert "PDF_ONLY_MARKER" not in pack
    assert "NESTED_ONLY" not in pack
    assert "WEATHER_FILLER_TOKEN" not in pack
    long_source = (tmp_path / "interim-long.txt").read_text(encoding="utf-8")
    assert len(pack) < len(long_source)

    captured = {}
    llm = _llm(_plan(PortfolioRating.HOLD, "Uses the pack."), captured)
    create_research_manager(llm)(_state(
        fundamentals_report="",
        local_fundamental_pack=pack,
    ))
    assert pack in captured["prompt"]
    assert "Revenue was 12.5 million" in captured["prompt"]
    assert "fundamentals_report" in captured["prompt"]


@pytest.mark.unit
def test_long_file_keeps_a_label_and_the_amount_on_the_next_line(tmp_path):
    body = "ignore this paragraph about the weather.\n" * 40
    body += "Revenue\n4.0 million\n"
    body += "ignore this paragraph about the weather.\n" * 40
    (tmp_path / "split.txt").write_text(body, encoding="utf-8")
    pack = build_local_fundamental_pack(tmp_path)
    assert "Revenue" in pack
    assert "4.0 million" in pack
    assert pack.count("ignore this paragraph") == 0


@pytest.mark.unit
def test_deep_note_passes_research_dir_pack_to_propagate(tmp_path, monkeypatch):
    (tmp_path / "SOURCES.md").write_text(
        "Synthetic source index only.\n", encoding="utf-8"
    )
    (tmp_path / "snippet.txt").write_text(
        "Revenue was 12.5 million.\n", encoding="utf-8"
    )
    captured = {}

    class FakeGraph:
        def __init__(self, *args, **kwargs):
            captured["config"] = kwargs.get("config")

        def propagate(self, ticker, date, asset_type="stock", local_fundamental_pack=""):
            captured["ticker"] = ticker
            captured["date"] = date
            captured["pack"] = local_fundamental_pack
            return {"news_empty": False}, "Hold"

        def save_reports(self, final_state, ticker, save_path=None):
            return tmp_path / "report"

    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.TradingAgentsGraph",
        FakeGraph,
    )
    from tradingagents.cli.deep_note import deep_note

    deep_note(ticker="hhh", date="2026-10-02", research_dir=tmp_path)
    assert captured["ticker"] == "HHH"
    assert captured["date"] == "2026-10-02"
    assert captured["config"]["research_mode"] is True
    assert "Revenue was 12.5 million" in captured["pack"]
    assert "Synthetic source index only" in captured["pack"]
    assert captured["config"]["data_vendors"]["fundamental_data"] == "yfinance,alpha_vantage"

    captured.clear()
    deep_note(ticker="HHH", date="2026-10-02", research_dir=None)
    assert captured["pack"] == ""


@pytest.mark.unit
def test_deep_note_rejects_a_missing_research_dir(tmp_path):
    from tradingagents.cli.deep_note import deep_note

    with pytest.raises(typer.BadParameter):
        deep_note(
            ticker="HHH",
            date="2026-10-02",
            research_dir=tmp_path / "does-not-exist",
        )


@pytest.mark.unit
def test_price_only_debate_cannot_set_overweight_when_fundamentals_present():
    captured = {}
    llm = _llm(
        _plan(
            PortfolioRating.OVERWEIGHT,
            "The price is above the 50-day moving average, so increase exposure.",
        ),
        captured,
    )
    result = create_research_manager(llm)(_state(
        fundamentals_report=_REPORT,
        investment_debate_state={
            "history": _PRICE_DEBATE,
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 2,
        },
    ))
    plan = result["investment_plan"]
    assert _REPORT in captured["prompt"]
    assert "do not assign Underweight or Overweight from price or moving averages" in captured["prompt"]
    assert _recommendation(plan) == "Hold"
    assert _recommendation(plan) not in {"Underweight", "Overweight"}
    assert "sole basis" in plan
    assert "12.5" not in plan.split("**Rationale**:", 1)[-1].split("**Strategic Actions**", 1)[0]


@pytest.mark.unit
def test_moving_average_only_debate_cannot_set_underweight_when_pack_present():
    pack = "Revenue was 12.5 million. Profit for the period was 3.0 million."
    llm = _llm(
        _plan(
            PortfolioRating.UNDERWEIGHT,
            "The 200-day moving average is rolling over, so trim exposure.",
        ),
        {},
    )
    result = create_research_manager(llm)(_state(
        local_fundamental_pack=pack,
        investment_debate_state={
            "history": _MA_DEBATE,
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 2,
        },
    ))
    plan = result["investment_plan"]
    assert _recommendation(plan) == "Hold"
    assert "sole basis" in plan
    assert "moving-average only" in plan


@pytest.mark.unit
def test_overweight_stands_when_rationale_uses_the_supplied_fundamentals():
    llm = _llm(
        _plan(
            PortfolioRating.OVERWEIGHT,
            "Revenue was 12.5 million and profit for the period was 3.0 million, "
            "which supports Overweight. The moving average is only context.",
        ),
        {},
    )
    result = create_research_manager(llm)(_state(
        fundamentals_report=_REPORT,
        investment_debate_state={
            "history": _PRICE_DEBATE,
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 2,
        },
    ))
    plan = result["investment_plan"]
    assert _recommendation(plan) == "Overweight"
    assert "sole basis" not in plan


@pytest.mark.unit
def test_missing_fundamentals_keeps_price_rating_and_records_the_gap():
    captured = {}
    llm = _llm(
        _plan(
            PortfolioRating.UNDERWEIGHT,
            "The price is under the 200-day moving average.",
        ),
        captured,
    )
    result = create_research_manager(llm)(_state(
        investment_debate_state={
            "history": _PRICE_DEBATE,
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 2,
        },
    ))
    plan = result["investment_plan"]
    prompt = captured["prompt"]
    assert _recommendation(plan) == "Underweight"
    assert "Gap: fundamentals_report is missing" in prompt
    assert "Gap: fundamentals_report is missing" in plan
    assert "Do not invent figures." in prompt
    assert "12.5" not in prompt
    assert "12.5" not in plan


@pytest.mark.unit
def test_buy_and_sell_are_not_rewritten_from_a_price_debate():
    for rating in (PortfolioRating.BUY, PortfolioRating.SELL):
        llm = _llm(_plan(rating, "The price trend is the whole case."), {})
        result = create_research_manager(llm)(_state(
            fundamentals_report=_REPORT,
            investment_debate_state={
                "history": _PRICE_DEBATE,
                "bull_history": "",
                "bear_history": "",
                "current_response": "",
                "judge_decision": "",
                "count": 2,
            },
        ))
        assert _recommendation(result["investment_plan"]) == rating.value


@pytest.mark.unit
def test_graph_receives_the_pack_string_and_does_not_read_a_directory():
    state = Propagator().create_initial_state(
        "HHH",
        "2026-10-02",
        research_mode=True,
        local_fundamental_pack="Revenue was 12.5 million.",
    )
    assert state["local_fundamental_pack"] == "Revenue was 12.5 million."
    assert state["research_mode"] is True
    for name in ("trading_graph.py", "propagation.py", "setup.py"):
        src = (_ROOT / "tradingagents" / "graph" / name).read_text(encoding="utf-8")
        assert "build_local_fundamental_pack" not in src
    pack_src = (
        _ROOT / "tradingagents" / "agents" / "utils" / "local_fundamental_pack.py"
    ).read_text(encoding="utf-8")
    for banned in ("edgartools", "pypdf", "pytesseract", "requests", "urllib"):
        assert banned not in pack_src
    assert DEFAULT_CONFIG["data_vendors"]["fundamental_data"] == "yfinance,alpha_vantage"


@pytest.mark.unit
def test_deep_note_help_shows_research_dir():
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
    assert "--research-dir" in proc.stdout
    assert "--full-trading-graph" in proc.stdout
