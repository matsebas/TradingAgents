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


def test_format_renders_role_with_guidance():
    out = format_portfolio_context(
        {"avg_cost": 33.0, "role": "anchor"}, "SPY"
    )
    assert "Position role: **anchor**" in out
    assert "thesis change" in out.lower()
    assert "absorb cycles" in out.lower()


def test_format_role_speculative_directs_against_rsi_sells():
    out = format_portfolio_context(
        {"avg_cost": 3.96, "role": "speculative"}, "IBIT"
    )
    assert "Position role: **speculative**" in out
    assert "thesis break" in out.lower()
    assert "drawdowns" in out.lower()


def test_format_role_tactical_uses_trailing_stop_framing():
    out = format_portfolio_context(
        {"avg_cost": 7.72, "role": "tactical"}, "NVDA"
    )
    assert "Position role: **tactical**" in out
    assert "trailing" in out.lower()


def test_format_unknown_role_renders_label_without_guidance():
    out = format_portfolio_context(
        {"avg_cost": 10.0, "role": "weirdrole"}, "X"
    )
    # The role label still surfaces, but no guidance line is emitted for
    # unrecognised values.
    assert "Position role: **weirdrole**" in out
    assert "Decision guidance" not in out


# --- portfolio_aggregate rendering ---------------------------------------


def test_format_renders_portfolio_aggregate_block():
    agg = {
        "total_positions": 3,
        "by_role": {
            "anchor": {
                "count": 1,
                "cost_basis_weight_pct": 50.0,
                "avg_unrealized_return_pct": 0.10,
                "tickers": ["SPY"],
            },
            "tactical": {
                "count": 2,
                "cost_basis_weight_pct": 50.0,
                "avg_unrealized_return_pct": 0.20,
                "tickers": ["NVDA", "AMZN"],
            },
        },
        "top_concentrations": [["SPY", 50.0], ["NVDA", 30.0], ["AMZN", 20.0]],
    }
    out = format_portfolio_context(
        {"avg_cost": 100.0, "role": "anchor", "portfolio_aggregate": agg},
        "SPY",
    )
    assert "Portfolio-Level Context" in out
    assert "Total positions: 3" in out
    assert "anchor" in out and "tactical" in out
    # Bucket lines should show counts and weights.
    assert "1 positions" in out
    assert "50.0%" in out
    # P&L per bucket appears with a sign.
    assert "+10.00%" in out and "+20.00%" in out
    # Top concentrations line.
    assert "SPY 50.0%" in out
    # The whole-book directive must be present.
    assert "concentration past target" in out


def test_format_omits_portfolio_aggregate_when_missing():
    out = format_portfolio_context(
        {"avg_cost": 100.0, "role": "anchor"}, "SPY"
    )
    assert "Portfolio-Level Context" not in out


def test_format_aggregate_handles_dataclass_input():
    from tradingagents.agents.utils.portfolio_aggregate import (
        compute_portfolio_aggregate,
    )

    holdings = {
        "SPY": {"quantity": 10, "avg_cost": 100, "role": "anchor"},
        "NVDA": {"quantity": 5, "avg_cost": 100, "role": "tactical"},
    }
    agg_obj = compute_portfolio_aggregate(holdings)
    assert agg_obj is not None

    # Pass the dataclass directly — format_portfolio_context should use to_dict().
    out = format_portfolio_context(
        {"avg_cost": 100, "role": "anchor", "portfolio_aggregate": agg_obj},
        "SPY",
    )
    assert "Portfolio-Level Context" in out
    assert "anchor" in out and "tactical" in out


# --- previous_decision rendering -----------------------------------------


def test_format_renders_previous_decision_with_stability_directive():
    out = format_portfolio_context(
        {
            "avg_cost": 100.0,
            "role": "anchor",
            "previous_decision": {
                "ticker": "SPY",
                "decision": "SELL",
                "date": "2026-04-17",
                "days_ago": 11,
            },
        },
        "SPY",
    )
    assert "Previous Decision" in out
    assert "SELL" in out
    assert "2026-04-17" in out
    assert "11 days ago" in out
    # The stability directive must require structural reasoning to flip.
    assert "MUST cite a structural change" in out
    assert "RSI/MACD/Bollinger" in out


def test_format_omits_previous_decision_when_missing():
    out = format_portfolio_context(
        {"avg_cost": 100.0, "role": "anchor"}, "SPY"
    )
    assert "Previous Decision" not in out
    assert "previous decision" not in out.lower()


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
    assert "Portfolio Context (binding rules)" in llm.captured


def test_risk_judge_anchor_directive_blocks_rsi_sells():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    judge(_minimal_state({"avg_cost": 33.0, "role": "anchor"}))
    # The judge prompt must call out anchors and require a thesis change.
    assert "anchors" in llm.captured.lower()
    assert "structural" in llm.captured.lower()
    assert "short-term yield" in llm.captured.lower()


def test_risk_judge_prompt_requires_entry_and_exit_triggers():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    judge(_minimal_state({"avg_cost": 100.0, "role": "tactical"}))

    # Both triggers must be required, regardless of recommendation direction.
    assert "Entry Trigger" in llm.captured
    assert "Exit Trigger" in llm.captured
    assert "Falsification Criteria" in llm.captured


def test_risk_judge_prompt_requires_previous_decision_consistency_check():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    judge(
        _minimal_state(
            {
                "avg_cost": 100.0,
                "role": "anchor",
                "previous_decision": {
                    "ticker": "SPY",
                    "decision": "SELL",
                    "date": "2026-04-17",
                    "days_ago": 11,
                },
            }
        )
    )
    # The previous-decision context surfaces in the prompt.
    assert "Previous Decision" in llm.captured
    assert "2026-04-17" in llm.captured
    # The structured Consistency Check section is required.
    assert "Previous-Decision Consistency Check" in llm.captured
    # Flipping must require a structural reason (not technical alone).
    assert "STRUCTURAL change" in llm.captured or "structural change" in llm.captured.lower()


def test_trader_prompt_includes_role_directive():
    from tradingagents.agents.trader.trader import create_trader

    llm = _StubLLM()
    trader = create_trader(llm, _StubMemory())
    trader(_minimal_state({"avg_cost": 33.0, "role": "anchor"}))
    user_msg = next(m for m in llm.captured if m["role"] == "user")
    assert "anchors absorb cycles" in user_msg["content"].lower()
    assert "thesis change" in user_msg["content"].lower()


def test_risk_judge_prompt_has_no_portfolio_block_when_context_missing():
    from tradingagents.agents.managers.risk_manager import create_risk_manager

    llm = _StubLLM()
    judge = create_risk_manager(llm, _StubMemory())
    judge(_minimal_state(portfolio_context=None))

    assert isinstance(llm.captured, str)
    assert "Existing Position Context" not in llm.captured
