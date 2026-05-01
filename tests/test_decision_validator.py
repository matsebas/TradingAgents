"""Tests for the structured-decision validator and auto-downgrade.

These pin the contract: outputs that contradict role-guidance must either
be flagged or auto-downgraded to HOLD before reaching the user. This is
the safety net that closes the asymmetry the PM framework lacks.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.managers.decision_validator import (
    auto_downgrade_to_hold,
    extract_decision_json,
    validate_decision,
)
from tradingagents.agents.utils.decision_schema import TradeDecision


# --- extract_decision_json -----------------------------------------------


def test_extract_returns_none_when_no_fence():
    assert extract_decision_json("just prose, no JSON") is None
    assert extract_decision_json("") is None


def test_extract_returns_none_for_invalid_json():
    text = "Some text\n\n```json\n{not valid json}\n```"
    assert extract_decision_json(text) is None


def test_extract_picks_last_fenced_block():
    text = (
        "intro\n```json\n{\"decision\":\"BUY\"}\n```\n"
        "more prose\n```json\n{\"decision\":\"HOLD\"}\n```"
    )
    parsed = extract_decision_json(text)
    assert parsed == {"decision": "HOLD"}


# --- validate_decision: schema --------------------------------------------


def _valid_payload(**overrides):
    payload = {
        "ticker": "NVDA",
        "decision": "HOLD",
        "qty_change": 0,
        "stop_loss": {"type": "trailing", "value": "10%", "basis": "default"},
        "triggers": {
            "entry_trigger": "Add on confirmed breakout above $X",
            "exit_trigger": "Exit on trailing stop hit",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": None,
            "previous_decision": None,
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "tactical default action",
        "role": "tactical",
        "entry_quality": "n/a",
        "falsification_criteria": ["earnings miss > 10%", "guidance cut"],
        "rationale": "HOLD per role guidance.",
    }
    payload.update(overrides)
    return payload


def test_valid_minimal_hold_passes():
    outcome = validate_decision(_valid_payload(), portfolio_context={"role": "tactical"})
    assert outcome.ok
    assert isinstance(outcome.decision, TradeDecision)


def test_buy_without_entry_plan_is_rejected():
    outcome = validate_decision(
        _valid_payload(decision="BUY"),
        portfolio_context={"role": "tactical"},
    )
    assert not outcome.ok
    assert any("entry_plan" in i for i in outcome.issues)


def test_buy_with_entry_plan_passes_for_tactical_loser():
    payload = _valid_payload(
        decision="BUY",
        entry_plan={
            "tier_now_pct": 50,
            "tier_pullback_target": "SMA 50d",
            "basis": "below target weight, optimal entry",
        },
        entry_quality="optimal",
        portfolio_weight_math={
            "current_weight_pct": 5.0,
            "target_weight_pct": 10.0,
            "action_brings_to_pct": 6.0,
            "weight_gate_passes": True,
        },
    )
    outcome = validate_decision(
        payload,
        portfolio_context={"role": "tactical", "unrealized_return_pct": -0.05},
    )
    assert outcome.ok


# --- validate_decision: cross-run flip ------------------------------------


def test_flip_with_technical_only_reason_is_rejected():
    payload = _valid_payload(
        decision="HOLD",
        previous_decision={
            "previous_date": "2026-04-17",
            "previous_decision": "SELL",
            "is_flip": True,
            "structural_reason": "RSI dropped from 75 to 58, MACD turned positive",
        },
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert not outcome.ok
    assert any("technical" in i.lower() or "structural" in i.lower() for i in outcome.issues)


def test_flip_with_structural_reason_passes():
    payload = _valid_payload(
        decision="HOLD",
        previous_decision={
            "previous_date": "2026-04-17",
            "previous_decision": "SELL",
            "is_flip": True,
            "structural_reason": (
                "Underlying constituents posted Q1 earnings above guidance; "
                "fundamental thesis improved vs prior run."
            ),
        },
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert outcome.ok


def test_flip_with_vague_short_reason_is_rejected():
    """A non-technical but trivially short reason ("volatility", "vibes")
    must NOT clear the gate — that's what would let an LLM rationalize a
    flip with structurally empty prose."""
    payload = _valid_payload(
        decision="HOLD",
        previous_decision={
            "previous_date": "2026-04-17",
            "previous_decision": "SELL",
            "is_flip": True,
            "structural_reason": "volatility",  # no technical token, no structural keyword, too short
        },
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert not outcome.ok


def test_flip_with_long_non_keyword_reason_passes():
    """If the reason is substantive (length >= 8 words) and not technical,
    accept it even without our explicit structural keywords — the LLM can
    write structural reasoning in many ways."""
    payload = _valid_payload(
        decision="HOLD",
        previous_decision={
            "previous_date": "2026-04-17",
            "previous_decision": "SELL",
            "is_flip": True,
            "structural_reason": (
                "The macroeconomic environment has shifted significantly "
                "with new constraints emerging that alter the landscape."
            ),
        },
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert outcome.ok


def test_lying_is_flip_is_overridden_when_decisions_differ():
    """Regression: an LLM emitted is_flip=false while changing SELL→HOLD,
    bypassing the structural-reason gate. The validator must derive is_flip
    from the actual values and reject this."""
    payload = _valid_payload(
        decision="HOLD",
        previous_decision={
            "previous_date": "2026-04-27",
            "previous_decision": "SELL",
            "is_flip": False,  # LLM lying
            "structural_reason": None,
        },
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert not outcome.ok
    issues = " ".join(outcome.issues).lower()
    # Must catch BOTH issues: missing structural reason AND mis-declared is_flip.
    assert "is_flip=false" in issues or "is_flip=true" in issues
    assert "structural" in issues


def test_continuing_previous_decision_does_not_require_reason():
    payload = _valid_payload(
        previous_decision={
            "previous_date": "2026-04-17",
            "previous_decision": "HOLD",
            "is_flip": False,
            "structural_reason": None,
        },
    )
    outcome = validate_decision(payload)
    assert outcome.ok


# --- validate_decision: tactical winner gates -----------------------------


def test_tactical_winner_buy_without_weight_gate_is_rejected():
    payload = _valid_payload(
        decision="BUY",
        entry_plan={
            "tier_now_pct": 25,
            "tier_pullback_target": None,
            "basis": "momentum",
        },
        entry_quality="optimal",
        portfolio_weight_math={
            "current_weight_pct": 12.0,
            "target_weight_pct": 10.0,
            "action_brings_to_pct": 14.0,
            "weight_gate_passes": False,
        },
    )
    outcome = validate_decision(
        payload,
        portfolio_context={"role": "tactical", "unrealized_return_pct": 0.30},
    )
    assert not outcome.ok
    assert any("weight gate" in i.lower() for i in outcome.issues)


def test_tactical_winner_buy_with_stretched_entry_is_rejected():
    payload = _valid_payload(
        decision="BUY",
        entry_plan={
            "tier_now_pct": 25,
            "tier_pullback_target": None,
            "basis": "momentum",
        },
        entry_quality="stretched",
        portfolio_weight_math={
            "current_weight_pct": 5.0,
            "target_weight_pct": 10.0,
            "action_brings_to_pct": 6.0,
            "weight_gate_passes": True,
        },
    )
    outcome = validate_decision(
        payload,
        portfolio_context={"role": "tactical", "unrealized_return_pct": 0.30},
    )
    assert not outcome.ok
    assert any("entry_quality" in i for i in outcome.issues)


def test_tactical_winner_buy_with_both_gates_passes():
    payload = _valid_payload(
        decision="BUY",
        entry_plan={
            "tier_now_pct": 25,
            "tier_pullback_target": "SMA 50d",
            "basis": "weight below target, optimal entry on retracement",
        },
        entry_quality="optimal",
        portfolio_weight_math={
            "current_weight_pct": 7.0,
            "target_weight_pct": 10.0,
            "action_brings_to_pct": 8.0,
            "weight_gate_passes": True,
        },
    )
    outcome = validate_decision(
        payload,
        portfolio_context={"role": "tactical", "unrealized_return_pct": 0.30},
    )
    assert outcome.ok


# --- validate_decision: anchor SELL ---------------------------------------


def test_anchor_sell_on_technical_reasoning_is_rejected():
    payload = _valid_payload(
        decision="SELL",
        rationale="RSI extended above 75, Bollinger upper band touched repeatedly.",
        cited_role_guidance="anchors absorb cycles",
        role="anchor",
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert not outcome.ok
    assert any("anchor sell" in i.lower() for i in outcome.issues)


def test_anchor_sell_with_structural_reasoning_passes():
    payload = _valid_payload(
        decision="SELL",
        rationale=(
            "Index methodology change reduces constituent quality starting Q3; "
            "regime shift in monetary policy with sustained rate-path inversion."
        ),
        cited_role_guidance="anchors require structural thesis change",
        role="anchor",
    )
    outcome = validate_decision(payload, portfolio_context={"role": "anchor"})
    assert outcome.ok


# --- auto_downgrade_to_hold -----------------------------------------------


# --- validate_decision: candidate (initiation) gates --------------------


def _candidate_payload(**overrides):
    payload = _valid_payload(
        decision="BUY",
        role="candidate",
        entry_quality="optimal",
        rationale=(
            "Strong fundamental thesis: company posted 30% YoY revenue "
            "growth with operating margin expansion. Healthcare sector "
            "underrepresented in book — fills a real role gap."
        ),
        entry_plan={
            "tier_now_pct": 50,
            "tier_pullback_target": "SMA 50d",
            "basis": "starter at 2% of book",
        },
    )
    payload["candidate"] = {
        "score": 7.5,
        "role_gap_aligned": True,
        "sector_overlap": "none",
        "sector_overlap_with": [],
        "thesis_strength": "high",
        "recommended_size_pct": 2.0,
        "recommended_size_usd": 1000.0,
    }
    payload.update(overrides)
    return payload


def test_candidate_buy_with_full_overlap_and_no_gap_is_rejected():
    payload = _candidate_payload()
    payload["candidate"]["sector_overlap"] = "full"
    payload["candidate"]["role_gap_aligned"] = False
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert not outcome.ok
    assert any("blocked" in i.lower() for i in outcome.issues)


def test_candidate_buy_with_full_overlap_but_role_gap_passes():
    """Full overlap is OK if the role bucket has headroom."""
    payload = _candidate_payload()
    payload["candidate"]["sector_overlap"] = "full"
    payload["candidate"]["role_gap_aligned"] = True
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert outcome.ok


def test_candidate_buy_with_chasing_entry_is_rejected():
    payload = _candidate_payload(entry_quality="chasing")
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert not outcome.ok
    assert any("chasing" in i.lower() for i in outcome.issues)


def test_candidate_buy_without_candidate_attributes_is_rejected():
    payload = _candidate_payload()
    payload.pop("candidate")
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert not outcome.ok
    assert any("candidate" in i.lower() for i in outcome.issues)


def test_candidate_buy_with_low_thesis_is_rejected():
    payload = _candidate_payload()
    payload["candidate"]["thesis_strength"] = "low"
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert not outcome.ok
    assert any("thesis_strength" in i for i in outcome.issues)


def test_candidate_buy_with_technical_only_rationale_is_rejected():
    payload = _candidate_payload(
        rationale="RSI broke above 50 with bullish MACD crossover."
    )
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert not outcome.ok
    assert any("technical" in i.lower() for i in outcome.issues)


def test_candidate_hold_does_not_require_full_attributes():
    """WATCHLIST (HOLD) is permissive — it's the safe default for unclear cases."""
    payload = _candidate_payload(decision="HOLD")
    payload["entry_plan"] = None  # HOLD doesn't need an entry plan
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert outcome.ok


def test_candidate_lying_overlap_is_overridden_by_precomputed():
    """Regression: same pattern as the is_flip lying fix. The LLM may emit
    sector_overlap='partial' to bypass the hard gate when the precomputed
    fit says 'full'. The validator must trust the precomputed value."""
    payload = _candidate_payload()
    payload["candidate"]["sector_overlap"] = "partial"  # LLM lying
    payload["candidate"]["role_gap_aligned"] = False

    # Precomputed fit (from the orchestrator) says FULL overlap and no gap.
    ctx = {
        "role": "candidate",
        "candidate_fit": {
            "role_gap": {"role": "tactical", "has_gap": False},
            "sector_overlap": {"level": "full", "overlapping_tickers": ["NVDA", "SMH"]},
        },
    }
    outcome = validate_decision(payload, portfolio_context=ctx)
    assert not outcome.ok
    issues = " ".join(outcome.issues).lower()
    # Mismatch flagged AND hard gate fires from the trusted value.
    assert "self-reported" in issues
    assert "blocked" in issues


def test_candidate_lying_role_gap_aligned_is_overridden():
    payload = _candidate_payload()
    payload["candidate"]["role_gap_aligned"] = True  # LLM lying
    payload["candidate"]["sector_overlap"] = "full"

    ctx = {
        "role": "candidate",
        "candidate_fit": {
            "role_gap": {"role": "tactical", "has_gap": False},
            "sector_overlap": {"level": "full"},
        },
    }
    outcome = validate_decision(payload, portfolio_context=ctx)
    assert not outcome.ok


def test_candidate_sell_does_not_require_full_attributes():
    """REJECT (SELL) is also permissive — rejecting a thesis is always allowed."""
    payload = _candidate_payload(decision="SELL")
    payload["entry_plan"] = None
    outcome = validate_decision(payload, portfolio_context={"role": "candidate"})
    assert outcome.ok


def test_auto_downgrade_produces_valid_hold_decision():
    downgraded = auto_downgrade_to_hold(
        decision=None,
        issues=["no JSON block emitted"],
        ticker="NVDA",
        portfolio_context={"role": "tactical"},
    )
    assert downgraded.decision == "HOLD"
    assert downgraded.qty_change == 0
    assert "AUTO-DOWNGRADED" in downgraded.rationale
    assert "no JSON block emitted" in downgraded.rationale


def test_auto_downgrade_preserves_role_when_known():
    bad_payload = _valid_payload(decision="BUY")  # missing entry_plan → invalid
    outcome = validate_decision(bad_payload, portfolio_context={"role": "tactical"})
    assert not outcome.ok
    downgraded = auto_downgrade_to_hold(
        outcome.decision, outcome.issues, ticker="NVDA",
        portfolio_context={"role": "tactical"},
    )
    assert downgraded.role == "tactical"
    assert downgraded.decision == "HOLD"
