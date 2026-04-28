"""Golden tests for role-based decision guidance.

These tests pin the contract that the Risk Judge sees through the prompt —
they fail loudly if a future prompt tweak drops a binding rule.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.utils.portfolio_context import (
    role_guidance_for,
    _ROLE_GUIDANCE_BASE,
    _TACTICAL_WINNER_HARDENED,
)


# --- role_guidance_for ---------------------------------------------------


def test_returns_none_for_missing_or_unknown_role():
    assert role_guidance_for(None) is None
    assert role_guidance_for("") is None
    assert role_guidance_for("nonsense") is None


def test_anchor_guidance_enumerates_thesis_changes():
    g = role_guidance_for("anchor")
    assert g is not None
    # Every enumerated thesis-change criterion must be present so the LLM
    # cannot manufacture its own.
    assert "monetary policy" in g.lower()
    assert "operating-income" in g.lower() or "operating income" in g.lower()
    assert "dividend cut" in g.lower() or "distribution halt" in g.lower()
    assert "geopolitical" in g.lower()
    assert "index methodology" in g.lower()
    # Default action must be HOLD with raised stop.
    assert "hold" in g.lower() and "trailing stop" in g.lower()
    # Technical-extension exemption must be explicit.
    assert "rsi" in g.lower() and "is not a thesis change" in g.lower()
    # Backward-compatible phrasing for the trader-prompt assertion.
    assert "anchors absorb cycles" in g.lower()


def test_tactical_base_requires_both_gates_for_buy():
    g = role_guidance_for("tactical", ctx={"unrealized_return_pct": 0.05})
    # P&L < +20% → base guidance, not hardened
    assert g is _ROLE_GUIDANCE_BASE["tactical"]
    assert "both gates" in g.lower()
    assert "below the role's target band" in g.lower()
    assert "1× atr" in g.lower() or "1x atr" in g.lower() or "1× ATR".lower() in g.lower()
    assert "upper bollinger" in g.lower()


def test_tactical_winner_above_20pct_uses_hardened_rule():
    g = role_guidance_for("tactical", ctx={"unrealized_return_pct": 0.21})
    assert g is _TACTICAL_WINNER_HARDENED
    assert "default action: hold" in g.lower()
    assert "tightened trailing stop" in g.lower()
    assert "do not chase price" in g.lower()


def test_tactical_at_exactly_20pct_uses_hardened_rule():
    # Boundary: == 0.20 is hardened (>= threshold).
    g = role_guidance_for("tactical", ctx={"unrealized_return_pct": 0.20})
    assert g is _TACTICAL_WINNER_HARDENED


def test_tactical_winner_with_no_ctx_falls_back_to_base():
    # If we don't know the P&L, we can't apply the hardened rule.
    g = role_guidance_for("tactical", ctx=None)
    assert g is _ROLE_GUIDANCE_BASE["tactical"]


def test_tactical_winner_with_unparseable_pnl_falls_back_to_base():
    g = role_guidance_for("tactical", ctx={"unrealized_return_pct": "n/a"})
    assert g is _ROLE_GUIDANCE_BASE["tactical"]


def test_speculative_blocks_average_up_on_momentum():
    g = role_guidance_for("speculative")
    assert g is not None
    assert "30%" in g  # drawdown tolerance
    assert "breakout" in g.lower() and "30-day range" in g.lower()
    assert "never average up" in g.lower() or "never average-up" in g.lower()
    assert "thesis break" in g.lower()


# --- format wiring (the user-visible block) ------------------------------


def test_tactical_winner_guidance_renders_in_format_output():
    """Make sure the hardened rule actually surfaces in the prompt block,
    not just in the function. This catches wiring regressions in
    format_portfolio_context where role context isn't passed down."""
    from tradingagents.agents.utils.portfolio_context import format_portfolio_context

    out = format_portfolio_context(
        {
            "avg_cost": 100.0,
            "role": "tactical",
            "unrealized_return_pct": 0.21,  # SMH-style winner
        },
        "SMH",
    )
    assert "Default action: HOLD" in out
    assert "tightened trailing stop" in out
    assert "weight is BELOW" in out


def test_tactical_loser_renders_base_guidance_in_format_output():
    from tradingagents.agents.utils.portfolio_context import format_portfolio_context

    out = format_portfolio_context(
        {
            "avg_cost": 100.0,
            "role": "tactical",
            "unrealized_return_pct": -0.05,
        },
        "AMZN",
    )
    # Base rule mentions both gates but NOT the hardened "default HOLD" line.
    assert "both gates" in out.lower()
    assert "default action: hold" not in out.lower()
