"""Tests for the candidate-specific comparative table in the markdown report."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.graph.portfolio import (
    PortfolioResult,
    _candidate_decision_label,
    _is_candidate_result,
    _render_candidate_summary,
)


def _candidate_result(ticker, decision, score=7.5, has_gap=True, overlap_level="none",
                      overlap_with=None, entry_quality="optimal",
                      rec_pct=2.0, rec_usd=1000.0, role="tactical"):
    state = {
        "portfolio_context": {
            "is_candidate": True,
            "role": role,
            "candidate_fit": {
                "role_gap": {
                    "role": role,
                    "has_gap": has_gap,
                    "current_weight_pct": 30.0 if has_gap else 44.0,
                    "target_weight_pct": 45.0,
                    "headroom_pct": 15.0 if has_gap else 1.0,
                },
                "sector_overlap": {
                    "level": overlap_level,
                    "candidate_sector": "Healthcare",
                    "candidate_industry": "Drug Manufacturers",
                    "overlapping_tickers": tuple(overlap_with or []),
                },
                "recommended_initial_weight_pct": rec_pct,
                "recommended_initial_size_usd": rec_usd,
            },
        },
        "trade_decision_structured": {
            "decision": decision,
            "role": role,
            "entry_quality": entry_quality,
            "candidate": {
                "score": score,
                "role_gap_aligned": has_gap,
                "sector_overlap": overlap_level,
                "sector_overlap_with": list(overlap_with or []),
                "thesis_strength": "high",
                "recommended_size_pct": rec_pct,
                "recommended_size_usd": rec_usd,
            },
        },
    }
    return PortfolioResult(
        ticker=ticker, decision=decision, state=state, error=None, duration_s=1.0
    )


def _holding_result(ticker, decision):
    state = {
        "portfolio_context": {"avg_cost": 100, "role": "tactical"},  # NOT a candidate
        "trade_decision_structured": {"decision": decision, "role": "tactical"},
    }
    return PortfolioResult(
        ticker=ticker, decision=decision, state=state, error=None, duration_s=1.0
    )


# --- _is_candidate_result ------------------------------------------------


def test_is_candidate_true_for_candidate_ctx():
    r = _candidate_result("NVO", "BUY")
    assert _is_candidate_result(r) is True


def test_is_candidate_false_for_holding():
    r = _holding_result("NVDA", "HOLD")
    assert _is_candidate_result(r) is False


def test_is_candidate_false_when_state_missing():
    r = PortfolioResult(ticker="X", decision=None, state=None, error="boom", duration_s=0)
    assert _is_candidate_result(r) is False


# --- decision label mapping ---------------------------------------------


def test_label_mapping():
    assert _candidate_decision_label("BUY") == "ADD"
    assert _candidate_decision_label("HOLD") == "WATCHLIST"
    assert _candidate_decision_label("SELL") == "REJECT"
    assert _candidate_decision_label("buy") == "ADD"  # case-insensitive
    assert _candidate_decision_label(None) == "—"


# --- _render_candidate_summary ------------------------------------------


def test_render_returns_empty_when_no_candidates():
    holdings_only = [_holding_result("NVDA", "HOLD"), _holding_result("SPY", "HOLD")]
    out = _render_candidate_summary(holdings_only)
    assert out == []


def test_render_filters_out_holdings():
    mixed = [
        _holding_result("NVDA", "HOLD"),
        _candidate_result("NVO", "BUY"),
        _holding_result("SPY", "HOLD"),
    ]
    out = _render_candidate_summary(mixed)
    md = "\n".join(out)
    assert "Candidate Evaluation" in md
    assert "NVO" in md
    # Holdings must NOT appear in the candidate table
    assert "| NVDA |" not in md
    assert "| SPY |" not in md


def test_render_uses_candidate_labels_not_buy_hold_sell():
    candidates = [
        _candidate_result("NVO", "BUY"),
        _candidate_result("WAIT", "HOLD"),
        _candidate_result("BAD", "SELL"),
    ]
    out = _render_candidate_summary(candidates)
    md = "\n".join(out)
    assert "**ADD**" in md
    assert "**WATCHLIST**" in md
    assert "**REJECT**" in md


def test_render_shows_score_and_size():
    candidates = [_candidate_result("NVO", "BUY", score=8.2, rec_pct=2.5, rec_usd=1250)]
    out = _render_candidate_summary(candidates)
    md = "\n".join(out)
    assert "8.2" in md
    assert "2.5%" in md
    assert "$1,250" in md


def test_render_shows_full_overlap_with_tickers():
    candidates = [
        _candidate_result(
            "AVGO", "HOLD",
            has_gap=False, overlap_level="full", overlap_with=["NVDA", "SMH"],
        ),
    ]
    out = _render_candidate_summary(candidates)
    md = "\n".join(out)
    assert "full" in md.lower()
    assert "NVDA, SMH" in md
    assert "AT/OVER" in md
