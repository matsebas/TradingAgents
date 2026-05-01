"""Tests for broker-feature awareness — manual_monitor stops + actionable orders."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.utils.portfolio_context import (
    _format_broker_constraints,
    format_portfolio_context,
)
from tradingagents.graph.portfolio import (
    PortfolioResult,
    _broker_action_label,
    _broker_entry_text,
    _broker_exit_text,
    _broker_features_for_result,
    _is_broker_restricted,
    _render_broker_orders,
)


# --- _format_broker_constraints -----------------------------------------


def test_format_omits_block_when_empty():
    assert _format_broker_constraints(None) == ""
    assert _format_broker_constraints([]) == ""
    assert _format_broker_constraints("") == ""


def test_format_omits_block_when_full_capability():
    out = _format_broker_constraints(["gtd", "stop_loss", "bracket"])
    assert out == ""


def test_format_emits_block_when_gtd_only():
    out = _format_broker_constraints(["gtd"])
    assert "Broker constraints" in out
    assert "GTD" in out
    assert "manual_monitor" in out
    assert "automatic stop-loss" in out


def test_format_emits_block_when_partial_capability():
    out = _format_broker_constraints(["gtd", "stop_loss"])
    assert "Broker constraints" in out
    assert "bracket" in out  # missing
    assert "automatic stop-loss" not in out  # has it


def test_format_handles_string_input():
    out = _format_broker_constraints("gtd")
    assert "Broker constraints" in out


def test_format_emits_strict_block_when_no_gtd():
    out = _format_broker_constraints(["stop_loss"])
    # Edge case: broker has stops but no GTD. Can't price-condition orders.
    assert "Broker constraints" in out
    assert "manually" in out.lower()


def test_format_renders_via_portfolio_context():
    out = format_portfolio_context(
        {
            "avg_cost": 100.0,
            "role": "tactical",
            "broker_features": ["gtd"],
        },
        "NVDA",
    )
    # Position block + broker block in same render.
    assert "PPPC" in out
    assert "Broker constraints" in out
    assert "GTD" in out


# --- _broker_action_label -----------------------------------------------


def test_action_label_for_holding():
    assert _broker_action_label("BUY", is_candidate=False) == "**ADD** (scale up)"
    assert _broker_action_label("SELL", is_candidate=False) == "**TRIM / EXIT**"
    # HOLD on existing position has no broker action — only monitoring.
    assert _broker_action_label("HOLD", is_candidate=False) == "—"


def test_action_label_for_candidate():
    assert _broker_action_label("BUY", is_candidate=True) == "**ADD** (initiate)"
    assert _broker_action_label("HOLD", is_candidate=True) == "WATCHLIST"
    assert _broker_action_label("SELL", is_candidate=True) == "REJECT"


# --- _broker_entry_text -------------------------------------------------


def test_entry_text_uses_pullback_target_and_qty():
    structured = {
        "qty_change": 35,
        "entry_plan": {
            "tier_now_pct": 50,
            "tier_pullback_target": "$38 (SMA 50d)",
            "basis": "starter tier",
        },
        "triggers": {"entry_trigger": "fallback text"},
    }
    entry, qty = _broker_entry_text(structured)
    assert "$38" in entry
    assert "qty +35" in qty
    assert "50% now" in qty


def test_entry_text_falls_back_to_trigger_when_no_plan():
    structured = {
        "qty_change": 0,
        "entry_plan": None,
        "triggers": {"entry_trigger": "If price toca $40, comprar 10 nominales"},
    }
    entry, qty = _broker_entry_text(structured)
    assert "If price toca $40" in entry
    assert qty == "—"


# --- _broker_exit_text --------------------------------------------------


def test_exit_text_for_manual_monitor():
    structured = {
        "stop_loss": {"type": "manual_monitor", "value": "$35", "basis": "x"},
        "triggers": {"exit_trigger": ""},
    }
    out = _broker_exit_text(structured)
    assert "Monitor" in out
    assert "$35" in out
    assert "GTD sell" in out


def test_exit_text_for_trailing_translates_to_manual():
    structured = {
        "stop_loss": {"type": "trailing", "value": "10%", "basis": "x"},
        "triggers": {"exit_trigger": ""},
    }
    out = _broker_exit_text(structured)
    # Trailing is automatic — but the broker can't auto-execute, so we
    # phrase it as something to monitor.
    assert "trailing 10%" in out.lower()
    assert "auto-trailing" in out.lower()


def test_exit_text_for_hard_stop():
    structured = {
        "stop_loss": {"type": "hard", "value": "$405", "basis": "x"},
        "triggers": {"exit_trigger": ""},
    }
    out = _broker_exit_text(structured)
    assert "$405" in out
    assert "GTD sell" in out


def test_exit_text_returns_dash_when_empty():
    structured = {
        "stop_loss": {"type": "hard", "value": "", "basis": "x"},
        "triggers": {"exit_trigger": ""},
    }
    out = _broker_exit_text(structured)
    assert out == "—"


# --- _is_broker_restricted ----------------------------------------------


def test_restricted_when_only_gtd():
    assert _is_broker_restricted({"gtd"}) is True


def test_not_restricted_when_full_capability():
    assert _is_broker_restricted({"gtd", "stop_loss", "bracket"}) is False


def test_not_restricted_when_empty():
    assert _is_broker_restricted(set()) is False


def test_restricted_when_missing_one():
    assert _is_broker_restricted({"gtd", "stop_loss"}) is True
    assert _is_broker_restricted({"gtd", "bracket"}) is True


# --- _render_broker_orders end-to-end -----------------------------------


def _result_with_broker(ticker, decision, *, broker_feats, is_candidate=False,
                       limit_price="$38 (SMA 50d)", stop_value="$35",
                       qty=0, tier_now=50):
    state = {
        "portfolio_context": {
            "broker_features": broker_feats,
            "is_candidate": is_candidate,
            "role": "candidate" if is_candidate else "tactical",
        },
        "trade_decision_structured": {
            "decision": decision,
            "qty_change": qty,
            "entry_plan": {
                "tier_now_pct": tier_now,
                "tier_pullback_target": limit_price,
                "basis": "x",
            },
            "stop_loss": {"type": "manual_monitor", "value": stop_value, "basis": "x"},
            "triggers": {"entry_trigger": "x", "exit_trigger": "x"},
        },
    }
    return PortfolioResult(
        ticker=ticker, decision=decision, state=state, error=None, duration_s=1.0
    )


def test_render_omits_when_no_broker_restriction():
    """Full-capability broker → no broker-actionable section (default behaviour
    for legacy callers without the config flag)."""
    results = [
        _result_with_broker("NVDA", "HOLD", broker_feats=["gtd", "stop_loss", "bracket"]),
    ]
    out = _render_broker_orders(results)
    assert out == []


def test_render_omits_when_broker_features_unset():
    results = [_result_with_broker("NVDA", "HOLD", broker_feats=[])]
    out = _render_broker_orders(results)
    assert out == []


def test_render_emits_section_when_gtd_only():
    results = [
        _result_with_broker("YPF", "HOLD", broker_feats=["gtd"], is_candidate=True),
        _result_with_broker("SMH", "HOLD", broker_feats=["gtd"]),
    ]
    out = _render_broker_orders(results)
    md = "\n".join(out)
    assert "Broker-Actionable Orders" in md
    assert "GTD-only" in md
    # Watchlist row for the candidate
    assert "WATCHLIST" in md
    # Holding HOLD has no action but does have a monitor exit
    assert "SMH" in md and "Monitor" in md


def test_render_skips_section_entirely_when_only_empty_holding_holds():
    """If every result is a HOLD on a holding with empty stop AND empty exit
    trigger → no rows would be generated, so suppress the whole section
    rather than emit an empty header table."""
    state = {
        "portfolio_context": {"broker_features": ["gtd"], "role": "tactical"},
        "trade_decision_structured": {
            "decision": "HOLD",
            "qty_change": 0,
            "entry_plan": None,
            "stop_loss": {"type": "hard", "value": "", "basis": "x"},
            "triggers": {"entry_trigger": "", "exit_trigger": ""},
        },
    }
    r = PortfolioResult(
        ticker="X", decision="HOLD", state=state, error=None, duration_s=0
    )
    out = _render_broker_orders([r])
    # Empty list — no section rendered when no actionable rows.
    assert out == []


def test_render_buy_candidate_row_shows_add_initiate():
    results = [
        _result_with_broker(
            "GLD", "BUY", broker_feats=["gtd"], is_candidate=True,
            limit_price="$420", qty=2, tier_now=100,
        ),
    ]
    out = _render_broker_orders(results)
    md = "\n".join(out)
    assert "ADD" in md and "initiate" in md
    assert "$420" in md
    assert "qty +2" in md


def test_broker_features_for_result_returns_set():
    r = _result_with_broker("X", "HOLD", broker_feats=["GTD", "stop_loss"])
    feats = _broker_features_for_result(r)
    assert feats == {"gtd", "stop_loss"}  # normalized


def test_broker_features_for_result_with_no_state():
    r = PortfolioResult(ticker="X", decision=None, state=None, error="boom", duration_s=0)
    assert _broker_features_for_result(r) == set()
