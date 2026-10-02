# TradingAgents/graph/conditional_logic.py

from langgraph.graph import END

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.graph.research_mode import NEWS_EMPTY_DEBATE_ROUNDS


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if sentiment-analyst tool round should continue.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Sentiment"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue.

        ``NEWS_EMPTY`` caps the bull/bear exchange at one pass each so an
        empty headline set does not run a configured multi-round debate.
        """
        rounds = self.max_debate_rounds
        if state.get("news_empty"):
            rounds = min(rounds, NEWS_EMPTY_DEBATE_ROUNDS)

        if (
            state["investment_debate_state"]["count"] >= 2 * rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def route_after_research_manager(self, state: AgentState) -> str:
        """Research mode stops after the research manager.

        The full trading graph (trader, risk, portfolio manager) stays wired
        and runs when ``research_mode`` is false. Deep-note turns the flag on.
        """
        if state.get("research_mode"):
            return END
        return "Trader"

    def route_after_trader(self, state: AgentState) -> str:
        """Skip the risk desk when ticker news is empty."""
        if state.get("news_empty"):
            return "Risk Truncated"
        return "Aggressive Analyst"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue.

        If an empty-news run still enters the risk loop, leave it immediately
        instead of spending a round on missing headlines.
        """
        if state.get("news_empty"):
            return "Portfolio Manager"
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
