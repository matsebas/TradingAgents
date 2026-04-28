"""Integration test for the Risk Judge node with structured-output validation.

Stubs the LLM and verifies the full flow:
1. LLM emits a valid structured JSON → accepted as-is.
2. LLM emits a contradiction (BUY without weight gate on tactical winner) →
   retry once, then auto-downgrade to HOLD if still bad.
3. LLM emits no JSON block at all → auto-downgrade to HOLD.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.managers.risk_manager import create_risk_manager


class _ScriptedLLM:
    """LLM stub that returns a queue of pre-canned responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        if not self._responses:
            content = "no more scripted responses"
        else:
            content = self._responses.pop(0)

        class _Msg:
            def __init__(self, c):
                self.content = c

        return _Msg(content)


class _StubMemory:
    def get_memories(self, *a, **kw):
        return []


def _state(portfolio_context=None):
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-04-28",
        "market_report": "M",
        "sentiment_report": "S",
        "news_report": "N",
        "fundamentals_report": "F",
        "investment_plan": "P",
        "investment_debate_state": {"history": "h"},
        "risk_debate_state": {
            "history": "rh",
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


def _valid_json_response(decision="HOLD", **overrides):
    payload = {
        "ticker": "NVDA",
        "decision": decision,
        "qty_change": 0,
        "stop_loss": {"type": "trailing", "value": "10%", "basis": "default"},
        "triggers": {
            "entry_trigger": "Add on confirmed breakout",
            "exit_trigger": "Trailing stop",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": None,
            "previous_decision": None,
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "tactical default",
        "role": "tactical",
        "entry_quality": "n/a",
        "falsification_criteria": ["earnings miss", "guidance cut"],
        "rationale": "HOLD per role guidance.",
    }
    payload.update(overrides)
    body = (
        "### 1. Summary\nfoo\n\n### 9. Structured Decision (JSON)\n\n"
        + "```json\n"
        + json.dumps(payload)
        + "\n```\n"
    )
    return body, payload


def test_valid_json_is_accepted_first_try():
    body, payload = _valid_json_response()
    llm = _ScriptedLLM([body])
    judge = create_risk_manager(llm, _StubMemory())

    result = judge(_state({"avg_cost": 100, "role": "tactical"}))

    assert llm.calls == 1
    structured = result["trade_decision_structured"]
    assert structured["decision"] == "HOLD"
    assert structured["ticker"] == "NVDA"
    # Original prose retained, no auto-downgrade banner.
    assert "AUTO-DOWNGRADED" not in result["final_trade_decision"]


def test_invalid_first_response_triggers_retry_once():
    # First response: BUY without entry_plan → schema violation.
    bad_payload = {
        "ticker": "NVDA",
        "decision": "BUY",  # missing entry_plan triggers issue
        "qty_change": 1,
        "stop_loss": {"type": "trailing", "value": "10%", "basis": "default"},
        "triggers": {
            "entry_trigger": "now",
            "exit_trigger": "stop",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": None, "previous_decision": None,
            "is_flip": False, "structural_reason": None,
        },
        "cited_role_guidance": "tactical default",
        "role": "tactical",
        "entry_quality": "n/a",
        "falsification_criteria": ["x"],
        "rationale": "test",
    }
    bad_body = "prose\n```json\n" + json.dumps(bad_payload) + "\n```"

    # Second response: valid HOLD.
    good_body, _ = _valid_json_response()

    llm = _ScriptedLLM([bad_body, good_body])
    judge = create_risk_manager(llm, _StubMemory())

    result = judge(_state({"avg_cost": 100, "role": "tactical"}))

    assert llm.calls == 2  # one retry happened
    assert result["trade_decision_structured"]["decision"] == "HOLD"
    assert "AUTO-DOWNGRADED" not in result["final_trade_decision"]


def test_no_json_block_auto_downgrades_to_hold():
    # First response: pure prose, no JSON block at all.
    # Second response: also pure prose (validator can't recover).
    llm = _ScriptedLLM([
        "Some narrative answer with no JSON.",
        "Still no JSON despite the retry.",
    ])
    judge = create_risk_manager(llm, _StubMemory())

    result = judge(_state({"avg_cost": 100, "role": "tactical"}))

    assert llm.calls == 2
    structured = result["trade_decision_structured"]
    assert structured["decision"] == "HOLD"
    assert "AUTO-DOWNGRADED" in result["final_trade_decision"]
    assert "no JSON" in result["final_trade_decision"] or "no fenced" in result["final_trade_decision"].lower()


def test_persistent_contradiction_is_auto_downgraded():
    # Tactical winner BUY without weight gate → both attempts fail, downgrade.
    bad_payload = {
        "ticker": "NVDA",
        "decision": "BUY",
        "qty_change": 35,
        "entry_plan": {
            "tier_now_pct": 25,
            "tier_pullback_target": "SMA 50d",
            "basis": "momentum",
        },
        "stop_loss": {"type": "trailing", "value": "15%", "basis": "tactical"},
        "triggers": {
            "entry_trigger": "now",
            "exit_trigger": "stop",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": None, "previous_decision": None,
            "is_flip": False, "structural_reason": None,
        },
        "cited_role_guidance": "tactical winner",
        "role": "tactical",
        "entry_quality": "stretched",  # NOT optimal — gate fails
        "portfolio_weight_math": {
            "current_weight_pct": 12.0,
            "target_weight_pct": 10.0,
            "action_brings_to_pct": 14.0,
            "weight_gate_passes": False,  # gate fails
        },
        "falsification_criteria": ["earnings miss"],
        "rationale": "Add to the runner.",
    }
    bad_body = "prose\n```json\n" + json.dumps(bad_payload) + "\n```"

    llm = _ScriptedLLM([bad_body, bad_body])
    judge = create_risk_manager(llm, _StubMemory())

    result = judge(_state({
        "avg_cost": 100,
        "role": "tactical",
        "unrealized_return_pct": 0.30,  # P&L > +20% triggers winner gates
    }))

    assert llm.calls == 2
    structured = result["trade_decision_structured"]
    assert structured["decision"] == "HOLD"  # auto-downgraded
    assert "AUTO-DOWNGRADED" in result["final_trade_decision"]
