"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

import re

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.deep_note import (
    downstream_instruction,
    news_empty_debate_note,
)
from tradingagents.agents.utils.rating import parse_rating
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

# Gap notices this module and the local-pack helper write when nothing was supplied.
# A real fundamentals report that mentions a gap is still material.
_GAP_ONLY_PREFIXES = (
    "Gap: fundamentals_report is missing",
    "Gap: no .txt or .md financial text",
)

_RECOMMENDATION_RE = re.compile(
    r"(\*\*Recommendation\*\*:\s*)(Buy|Overweight|Hold|Underweight|Sell)\b"
)
_PRICE_OR_MA_RE = re.compile(
    r"(?i)(\bprices?\b|\bmoving averages?\b|\b\d+\s*-\s*day\b|"
    r"\b(?:sma|ema|vwma|rsi|macd)\b|均线|股价|移动平均)"
)
_FUNDAMENTAL_TOPIC_RE = re.compile(
    r"(?i)("
    r"\brevenue\b|\bturnover\b|\bearnings\b|\beps\b|\bebitda?\b|"
    r"\bmargins?\b|\bcash flows?\b|\bbalance sheet\b|\bincome statement\b|"
    r"\bdividends?\b|"
    r"net profit|operating profit|gross profit|profit for the period|"
    r"营业收入|期内利润|净利润|营业利润|毛利|现金流|营收"
    r")"
)
_MA_WINDOW_RE = re.compile(r"(?i)\b\d+\s*-\s*day\b")
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+")

_TILT_BLOCKED_NOTE = (
    "Underweight or Overweight was not assigned. The debate is price or "
    "moving-average only and cannot be the sole basis for that rating while "
    "fundamentals_report or a local fundamental pack is present. "
    "Price and technicals remain context. No figures were invented."
)
_MISSING_GAP = (
    "Gap: fundamentals_report is missing and no local fundamental pack was "
    "supplied. Do not invent figures."
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")
        fundamentals_report = state.get("fundamentals_report") or ""
        local_pack = state.get("local_fundamental_pack") or ""

        investment_debate_state = state["investment_debate_state"]

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance whenever the debate's strongest arguments warrant one; reserve Hold for situations where the evidence on both sides is genuinely balanced.

---

{fundamentals_input(fundamentals_report, local_pack)}

---

**Debate History:**
{history}""" + downstream_instruction() + news_empty_debate_note(state) + get_language_instruction()

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )
        investment_plan = constrain_price_only_tilt(
            investment_plan,
            debate=history,
            fundamentals_report=fundamentals_report,
            local_pack=local_pack,
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node


def fundamentals_input(fundamentals_report: str, local_pack: str) -> str:
    """Text the manager sees before it assigns a rating."""
    report = fundamentals_report or ""
    pack = local_pack or ""
    sections = [
        "**fundamentals_report:**",
        report.strip() or "(empty)",
    ]
    if pack.strip():
        sections.extend(["", "**Local fundamental pack:**", pack.strip()])
    if fundamental_material_present(report, pack):
        sections.extend([
            "",
            "When fundamentals_report or the local fundamental pack is present, "
            "do not assign Underweight or Overweight from price or moving averages "
            "alone. Price and technicals may stay as context. Ground that rating in "
            "the fundamental material above. Do not invent figures that are not in "
            "that material.",
        ])
    else:
        sections.extend(["", _MISSING_GAP])
    return "\n".join(sections)


def fundamental_material_present(fundamentals_report: str, local_pack: str) -> bool:
    """True when a report or a local pack actually contains fundamental text."""
    return _substantive(fundamentals_report) or _substantive(local_pack)


def _substantive(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    gap_only = body.startswith(_GAP_ONLY_PREFIXES) and "### " not in body and len(body) < 500
    return not gap_only


def debate_is_price_or_ma_only(debate: str) -> bool:
    """True when the debate's claims are price or moving averages and nothing else."""
    text = (debate or "").strip()
    if not text or not _PRICE_OR_MA_RE.search(text):
        return False
    return not _FUNDAMENTAL_TOPIC_RE.search(text)


def rationale_uses_supplied_fundamentals(rationale: str, material: str) -> bool:
    """True when the written basis quotes the supplied fundamental material."""
    basis = rationale or ""
    source = material or ""
    if not basis.strip() or not source.strip():
        return False
    if _figure_tokens(basis) & _figure_tokens(source):
        return True
    source_l = source.lower()
    for match in _FUNDAMENTAL_TOPIC_RE.finditer(basis):
        if match.group(0).lower() in source_l:
            return True
    return False


def _figure_tokens(text: str) -> set[str]:
    masked = _MA_WINDOW_RE.sub(" ", text or "")
    tokens: set[str] = set()
    for raw in _NUMBER_RE.findall(masked):
        norm = raw.replace(",", "")
        if "." in norm or "," in raw or len(norm) >= 3:
            tokens.add(norm)
    return tokens


def constrain_price_only_tilt(
    plan_text: str,
    *,
    debate: str,
    fundamentals_report: str,
    local_pack: str,
) -> str:
    """Drop Underweight/Overweight when price or a moving average is the only basis.

    Fundamentals missing: leave the plan as the model wrote it. The prompt
    already records that gap. Buy and Sell are unchanged.
    """
    if not fundamental_material_present(fundamentals_report, local_pack):
        if _MISSING_GAP not in (plan_text or ""):
            return (plan_text or "").rstrip() + "\n\n" + _MISSING_GAP
        return plan_text
    if not debate_is_price_or_ma_only(debate):
        return plan_text

    rating = _stated_rating(plan_text)
    if rating not in {"Underweight", "Overweight"}:
        return plan_text

    material = f"{fundamentals_report or ''}\n{local_pack or ''}"
    if rationale_uses_supplied_fundamentals(plan_text, material):
        return plan_text

    rewritten = _set_recommendation(plan_text, "Hold")
    if _TILT_BLOCKED_NOTE not in rewritten:
        rewritten = rewritten.rstrip() + "\n\n" + _TILT_BLOCKED_NOTE
    return rewritten


def _stated_rating(plan_text: str) -> str:
    match = _RECOMMENDATION_RE.search(plan_text or "")
    if match:
        return match.group(2)
    if not plan_text:
        return ""
    return parse_rating(plan_text, default="")


def _set_recommendation(plan_text: str, rating: str) -> str:
    if _RECOMMENDATION_RE.search(plan_text or ""):
        return _RECOMMENDATION_RE.sub(rf"\g<1>{rating}", plan_text, count=1)
    return f"**Recommendation**: {rating}\n\n{plan_text or ''}".rstrip()
