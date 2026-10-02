"""Research-mode stops and the empty-news risk truncation.

Deep-note runs default to research mode: analysts, one bull pass, one bear
pass, the research manager, then stop. The trader, the risk desk, and the
portfolio manager stay in the graph for a full trading run
(``research_mode=False``). They are not the deep-note default, and they do
not place orders either way.

When ticker news is ``NEWS_EMPTY``, the risk desk is not asked to debate the
absence of headlines. A short deterministic note is written instead.
"""

from __future__ import annotations

# One bull pass and one bear pass, then the research manager.
NEWS_EMPTY_DEBATE_ROUNDS = 1

RISK_TRUNCATED_NOTE = (
    "NEWS_EMPTY: ticker news vendors returned no headlines. "
    "The risk debate was skipped so an empty news set is not argued for a full round. "
    "Do not invent headlines, prices, or an order. This output is research only."
)


def risk_truncated_node(state):
    """Record a truncated risk note and stop. No model call."""
    prior = state.get("risk_debate_state") or {}
    updated = {
        "aggressive_history": prior.get("aggressive_history", ""),
        "conservative_history": prior.get("conservative_history", ""),
        "neutral_history": prior.get("neutral_history", ""),
        "history": RISK_TRUNCATED_NOTE,
        "latest_speaker": "Risk Truncated",
        "current_aggressive_response": prior.get("current_aggressive_response", ""),
        "current_conservative_response": prior.get("current_conservative_response", ""),
        "current_neutral_response": prior.get("current_neutral_response", ""),
        "judge_decision": RISK_TRUNCATED_NOTE,
        "count": prior.get("count", 0),
    }
    return {
        "risk_debate_state": updated,
        "final_trade_decision": RISK_TRUNCATED_NOTE,
    }
