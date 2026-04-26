import functools
import time
import json

from tradingagents.agents.utils.portfolio_context import format_portfolio_context


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        portfolio_block = format_portfolio_context(
            state.get("portfolio_context"), company_name
        )

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        user_content = (
            f"Based on a comprehensive analysis by a team of analysts, here is an "
            f"investment plan tailored for {company_name}. This plan incorporates "
            f"insights from current technical market trends, macroeconomic "
            f"indicators, and social media sentiment. Use this plan as a "
            f"foundation for evaluating your next trading decision.\n\n"
            f"Proposed Investment Plan: {investment_plan}\n\n"
        )
        if portfolio_block:
            user_content += (
                f"{portfolio_block}\n\n"
                "Ground your decision on this existing position. Use the "
                "Unrealized P&L % as the ground-truth performance signal "
                "(ratio-invariant). Consider: (a) sizing the action relative "
                "to the current quantity held, (b) whether the thesis "
                "justifies adding to a winner or averaging down a loser, and "
                "(c) take-profit / stop-loss levels relative to the current "
                "P&L, not absolute price levels.\n\n"
            )
        user_content += "Leverage these insights to make an informed and strategic decision."

        context = {
            "role": "user",
            "content": user_content,
        }

        messages = [
            {
                "role": "system",
                "content": f"""You are a trading agent analyzing market data to make investment decisions. Based on your analysis, provide a specific recommendation to buy, sell, or hold. End with a firm decision and always conclude your response with 'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**' to confirm your recommendation. Do not forget to utilize lessons from past decisions to learn from your mistakes. Here is some reflections from similar situatiosn you traded in and the lessons learned: {past_memory_str}""",
            },
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
