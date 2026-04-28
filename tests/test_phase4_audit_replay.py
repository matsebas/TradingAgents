"""Phase 4 audit replay — deterministic validation of the 2026-04-28 decisions.

Each test reconstructs what the Risk Judge of the OLD system actually said
in reports/portfolio_2026-04-28.md, expresses it as the structured JSON the
NEW system would require, and feeds it through ``validate_decision`` with
the real ``portfolio_context`` of the position. The assertion is whether the
new safety net catches the issues we identified in the audit:

* SMH (tactical, P&L +29.53%): old system recommended BUY tier 25% — should
  be flagged unless both weight and entry-quality gates pass.
* AMZN (tactical, P&L +22.81%): old system recommended scaled BUY 0.5u —
  should be flagged similarly.
* NVDA (tactical, P&L +21.06%): old system recommended BUY +15% (35 units)
  — should be flagged.
* IBIT (speculative, P&L +13.66%): old system said HOLD — should pass
  cleanly (no contradictions).
* SPY (anchor, P&L +10.28%): old system said HOLD after previous SELL —
  the flip-back-to-HOLD must cite structural reason; if only technicals,
  the validator must catch it.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.managers.decision_validator import validate_decision


# --- SMH --- BUY at +29.53% with no weight/entry-quality gates ----------


def test_smh_old_buy_is_flagged_by_new_validator():
    payload = {
        "ticker": "SMH",
        "decision": "BUY",
        "qty_change": 66,  # ~25% of 263
        "entry_plan": {
            "tier_now_pct": 25,
            "tier_pullback_target": "EMA 20d",
            "basis": "Per old Risk Judge: 'leaning into momentum of structural shift'",
        },
        "stop_loss": {"type": "trailing", "value": "10%", "basis": "tactical winner"},
        "triggers": {
            "entry_trigger": "Test of EMA 20d for remaining tier",
            "exit_trigger": "10% trailing stop",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "BUY",
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "tactical winner — prefer trailing-stop discipline",
        "role": "tactical",
        # The OLD prose said "RSI at 58 is the sweet spot" / "riding upper
        # Bollinger" — that is, entry quality was NOT optimal. The old prompt
        # didn't force this field to be honest; the new one does.
        "entry_quality": "stretched",
        "portfolio_weight_math": None,  # old system didn't compute it
        "falsification_criteria": [
            "guidance from NVDA/TSMC/AVGO pivots to 'CapEx optimization'",
            "RSI sustained above 80 (frothy territory)",
        ],
        "rationale": (
            "BUY based on momentum and structural AI CapEx. RSI 58.84 healthy. "
            "Add 25% now, 75% on EMA 20d test."
        ),
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "tactical",
            "unrealized_return_pct": 0.2953,  # +29.53%
        },
    )
    assert not outcome.ok, "SMH old BUY should be flagged — tactical winner without gates"
    issues = " ".join(outcome.issues).lower()
    # At least one of: weight gate failure, entry quality not optimal.
    assert "weight gate" in issues or "entry_quality" in issues


# --- AMZN --- scaled BUY 0.5u at +22.81% --------------------------------


def test_amzn_old_buy_is_flagged():
    payload = {
        "ticker": "AMZN",
        "decision": "BUY",
        "qty_change": 1,  # original payload showed scaled 0.5u; round up to int
        "entry_plan": {
            "tier_now_pct": 50,
            "tier_pullback_target": "SMA 50d",
            "basis": "Scaled to acknowledge MACD cooling",
        },
        "stop_loss": {
            "type": "hard",
            "value": "below SMA 200d",
            "basis": "thesis-break level",
        },
        "triggers": {
            "entry_trigger": "Retracement to SMA 50d holds",
            "exit_trigger": "Close below SMA 200d",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "BUY",
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "tactical winner — trailing-stop discipline preferred",
        "role": "tactical",
        # Old report said MACD histogram shrinking — entry was cooling, not optimal.
        "entry_quality": "stretched",
        "portfolio_weight_math": None,
        "falsification_criteria": [
            "AWS margin contraction over 2 quarters",
            "Ad-revenue growth drops below 15%",
        ],
        "rationale": (
            "Scaled BUY: AWS 'harvesting phase', advertising flywheel, but "
            "respect the technical cooling (shrinking MACD)."
        ),
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "tactical",
            "unrealized_return_pct": 0.2281,
        },
    )
    assert not outcome.ok, "AMZN old BUY should be flagged for tactical winner gates"


# --- NVDA --- BUY +15% at +21.06% ----------------------------------------


def test_nvda_old_buy_is_flagged():
    payload = {
        "ticker": "NVDA",
        "decision": "BUY",
        "qty_change": 35,  # +15% of 235
        "entry_plan": {
            "tier_now_pct": 100,
            "tier_pullback_target": None,
            "basis": "Disciplined expansion at current level (~$216)",
        },
        "stop_loss": {"type": "trailing", "value": "15%", "basis": "tactical winner"},
        "triggers": {
            "entry_trigger": "n/a — already adding",
            "exit_trigger": "15% trailing stop",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "BUY",
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "tactical winner — prefer trailing-stop discipline",
        "role": "tactical",
        "entry_quality": "stretched",  # at $216, breakout level — not optimal entry
        # Old report didn't have weight math — the PM critique is precisely
        # that nobody (system OR PM) showed the portfolio-level math.
        "portfolio_weight_math": None,
        "falsification_criteria": [
            "Operating margins decline 2 consecutive quarters",
            "PEG ratio exceeds 1.5",
        ],
        "rationale": "Tactical scale-in: PEG 0.74 supports 'cheap-on-growth' thesis.",
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "tactical",
            "unrealized_return_pct": 0.2106,
        },
    )
    assert not outcome.ok, "NVDA old BUY should be flagged for tactical winner gates"


# --- IBIT --- HOLD (no contradictions expected) --------------------------


def test_ibit_hold_passes_cleanly():
    payload = {
        "ticker": "IBIT",
        "decision": "HOLD",
        "qty_change": 0,
        "stop_loss": {
            "type": "hard",
            "value": "$40.50",
            "basis": "preserve original capital intact",
        },
        "triggers": {
            "entry_trigger": "Close above $45.50 on strong volume",
            "exit_trigger": "Close below $40.50",
            "profit_take_levels": ["$52 → trim 25%"],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "BUY",
            "is_flip": True,
            "structural_reason": (
                "Position role re-classified as speculative; size discipline "
                "now takes precedence over momentum continuation."
            ),
        },
        "cited_role_guidance": "speculative — adds only on confirmed breakout",
        "role": "speculative",
        "entry_quality": "n/a",
        "portfolio_weight_math": None,
        "falsification_criteria": [
            "BTC supply/demand thesis breaks (regulatory ETF restriction)",
            "Counterparty / custody failure event",
        ],
        "rationale": (
            "HOLD per speculative role: 13.66% gain protected, await $45.50 "
            "breakout confirmation before adding."
        ),
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "speculative",
            "unrealized_return_pct": 0.1366,
        },
    )
    assert outcome.ok, f"IBIT HOLD should pass cleanly; issues: {outcome.issues}"


# --- SPY --- the canonical instability case ------------------------------


def test_spy_flip_to_hold_with_only_technical_reason_is_caught():
    """The old system flipped SPY from SELL (04-17) to HOLD (04-28) without
    citing a structural reason. The new validator must reject this flip."""
    payload = {
        "ticker": "SPY",
        "decision": "HOLD",
        "qty_change": 0,
        "stop_loss": {"type": "trailing", "value": "$702", "basis": "below EMA 10d"},
        "triggers": {
            "entry_trigger": "Retracement to SMA 50d ($676.78)",
            "exit_trigger": "Close below $702",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "SELL",
            "is_flip": True,
            # The old prose pointed to MACD/Bollinger/EMA alignment — that's
            # technical-only, which the new validator must catch.
            "structural_reason": (
                "10/50/200 EMAs aligned, RSI in healthy range, MACD positive."
            ),
        },
        "cited_role_guidance": "anchors absorb cycles; no structural change",
        "role": "anchor",
        "entry_quality": "stretched",
        "portfolio_weight_math": None,
        "falsification_criteria": [
            "Concentration risk in mega-cap tech materializes via guidance miss",
            "Macro regime shift (sustained rate-path inversion)",
        ],
        "rationale": "HOLD: tape is strong, valuation gravity is real but not yet binding.",
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "anchor",
            "unrealized_return_pct": 0.1028,
        },
    )
    assert not outcome.ok, "SPY flip with technical-only reason must be flagged"
    issues = " ".join(outcome.issues).lower()
    assert "structural" in issues or "technical" in issues


def test_spy_continuing_hold_passes():
    """If SPY was HOLD on 04-17 and stays HOLD on 04-28, no flip → pass."""
    payload = {
        "ticker": "SPY",
        "decision": "HOLD",
        "qty_change": 0,
        "stop_loss": {"type": "trailing", "value": "$702", "basis": "below EMA 10d"},
        "triggers": {
            "entry_trigger": "Retracement to SMA 50d",
            "exit_trigger": "Close below $702",
            "profit_take_levels": [],
        },
        "previous_decision": {
            "previous_date": "2026-04-17",
            "previous_decision": "HOLD",
            "is_flip": False,
            "structural_reason": None,
        },
        "cited_role_guidance": "anchors absorb cycles",
        "role": "anchor",
        "entry_quality": "n/a",
        "portfolio_weight_math": None,
        "falsification_criteria": [
            "Concentration risk in mega-cap tech materializes",
            "Sustained rate-path inversion",
        ],
        "rationale": "Continuity HOLD: no structural change, no thesis break.",
    }
    outcome = validate_decision(
        payload,
        portfolio_context={
            "role": "anchor",
            "unrealized_return_pct": 0.1028,
        },
    )
    assert outcome.ok
