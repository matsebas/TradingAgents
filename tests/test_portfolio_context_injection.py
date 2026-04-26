"""Verify that portfolio_context actually reaches the Trader and Risk Judge
prompts — and ONLY those — so we can trust that A/B comparisons measure the
effect of the injection rather than some other change.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.utils.portfolio_context import format_portfolio_context


# --- format_portfolio_context --------------------------------------------


def test_format_returns_empty_string_for_none():
    assert format_portfolio_context(None, "NVDA") == ""


def test_format_returns_empty_string_for_empty_dict():
    assert format_portfolio_context({}, "NVDA") == ""


def test_format_returns_empty_when_only_unrecognised_keys():
    assert format_portfolio_context({"whatever": "nothing"}, "NVDA") == ""


def test_format_renders_avg_cost_and_currency():
    out = format_portfolio_context(
        {"avg_cost": 42.55, "currency": "USD"}, "NVDA"
    )
    assert "NVDA" in out
    assert "PPPC" in out
    assert "42.55" in out
    assert "USD" in out


def test_format_accepts_pppc_alias():
    # Parsed positions set `avg_cost`, but downstream code may also feed `pppc`
    # — both should render.
    out = format_portfolio_context({"pppc": 12.34}, "AMZN")
    assert "12.34" in out


def test_format_renders_optional_fields_when_present():
    out = format_portfolio_context(
        {
            "avg_cost": 10.0,
            "quantity": 200,
            "weight_pct": 12.5,
            "instrument_type": "CEDEARS",
            "notes": "Half of target size.",
        },
        "IBIT",
    )
    assert "200" in out
    assert "12.50%" in out
    assert "CEDEARS" in out
    assert "Half of target size." in out


def test_format_renders_unrealized_pnl_as_percent():
    out = format_portfolio_context(
        {"avg_cost": 10.0, "unrealized_return_pct": 0.219},
        "SMH",
    )
    assert "+21.90%" in out
    # P&L appears before PPPC so the model anchors on the ratio-invariant figure.
    assert out.index("Unrealized") < out.index("PPPC")


def test_format_flags_cedear_ratio_warning():
    out = format_portfolio_context(
        {"avg_cost": 3.96, "instrument_type": "CEDEARS"},
        "IBIT",
    )
    assert "CEDEAR units" in out
    assert "NOT directly comparable" in out


def test_format_omits_cedear_warning_for_non_cedear():
    out = format_portfolio_context(
        {"avg_cost": 123.45, "instrument_type": "STOCK"},
        "AAPL",
    )
    assert "CEDEAR units" not in out
    assert "NOT directly comparable" not in out


# --- prompt wiring -------------------------------------------------------


class _StubLLM:
    """Capture whatever messages / prompt the agent sends to the LLM."""

    def __init__(self, content: str = "FINAL TRANSACTION PROPOSAL: **BUY**"):
        self.captured = None
        self._content = content

    def invoke(self, arg):
        self.captured = arg

        class _Msg:
            def __init__(self, c):
                self.content = c

        return _Msg(self._content)


class _StubMemory:
    def get_memories(self, *a, **kw):
        return []


def _minimal_state(portfolio_context=None):
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-04-23",
        "market_report": "technical report",
        "sentiment_report": "sentiment report",
        "news_report": "news report",
        "fundamentals_report": "fundamentals report",
        "investment_plan": "plan text",
        "investment_debate_state": {"history": "debate"},
        "risk_debate_state": {
            "history": "risk debate",
            "risky_history": "r",
            "safe_history": "s",
            "neutral_history": "n",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
        },
        "portfolio_context": portfolio_context,
    }


def test_trader_prompt_contains_pppc_when_context_present():
    from tradingagents.agents.trader.trader import create_trader

    llm = _StubLLM()
    trader = create_trader(llm, _StubMemory())
    state = _minimal_state({"avg_cost": 99.99, "currency": "USD"})
    trader(state)

    # Trader passes a list of {role, content} dicts.
    assert llm.captured is not None
    user_msg = next(m for m in llm.captured if m["role"] == "user")
    assert "99.99" in user_msg["content"]
    assert "PPPC" in user_msg["content"]


def test_trader_prompt_has_no_portfolio_block_when_context_missing():
    from tradingagents.agents.trader.trader import create_trader

    llm = _StubLLM()
    trader = create_trader(llm, _StubMemory())
    trader(_minimal_state(portfolio_context=None))

    user_msg = next(m for m in llm.captured if m["role"] == "user")
    assert "Current Portfolio Position" not in user_msg["content"]
    assert "PPPC" not in user_msg["content"]


def test_risk_judge_prompt_contains_pppc_when_context_present():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    state = _minimal_state({"avg_cost": 33.33, "currency": "USD"})
    judge(state)

    # Risk manager calls llm.invoke(prompt_string) directly.
    assert isinstance(llm.captured, str)
    assert "33.33" in llm.captured
    assert "Existing Position Context" in llm.captured


def test_risk_judge_prompt_has_no_portfolio_block_when_context_missing():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    judge(_minimal_state(portfolio_context=None))

    assert isinstance(llm.captured, str)
    assert "Existing Position Context" not in llm.captured
