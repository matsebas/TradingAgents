"""Tests for candidate-fit math (role gap, sector overlap, sizing)."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.utils.portfolio_fit import (
    DEFAULT_ROLE_TARGETS,
    CandidateFit,
    RoleGap,
    SectorOverlap,
    compute_portfolio_fit,
    is_buy_blocked_by_overlap_and_at_target,
)


def _stub_lookup(table):
    """Build a sector_lookup_fn from a dict {ticker: (sector, industry)}."""
    def fn(ticker):
        info = table.get(ticker.upper())
        if info is None:
            return SimpleNamespace(sector=None, industry=None)
        return SimpleNamespace(sector=info[0], industry=info[1])
    return fn


# --- Role gap ------------------------------------------------------------


def test_role_gap_has_gap_when_below_target():
    aggregate = {
        "by_role": {
            "anchor": {"cost_basis_weight_pct": 20.0},
            "tactical": {"cost_basis_weight_pct": 60.0},
        },
        "total_cost_basis_usd": 50000.0,
    }
    fit = compute_portfolio_fit(
        "NVO", "anchor",
        portfolio_aggregate=aggregate,
        holdings={"SPY": {}},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug Manufacturers"),
                                       "SPY": ("US Equity", "Broad Market")}),
    )
    assert fit.role_gap.has_gap is True
    assert fit.role_gap.headroom_pct == 20.0  # 40 - 20
    assert fit.role_gap.target_weight_pct == 40.0


def test_role_gap_no_gap_when_at_target():
    aggregate = {
        "by_role": {"tactical": {"cost_basis_weight_pct": 45.0}},
        "total_cost_basis_usd": 10000.0,
    }
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=aggregate,
        holdings={"SMH": {}},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug Manufacturers"),
                                       "SMH": ("Technology", "Semiconductors")}),
    )
    assert fit.role_gap.has_gap is False
    assert fit.role_gap.headroom_pct == 0.0


def test_role_gap_negative_headroom_when_over_target():
    aggregate = {
        "by_role": {"speculative": {"cost_basis_weight_pct": 25.0}},
    }
    fit = compute_portfolio_fit(
        "MSTR", "speculative",
        portfolio_aggregate=aggregate,
        holdings={"IBIT": {}},
        sector_lookup_fn=_stub_lookup({"MSTR": ("Crypto", "Bitcoin"),
                                       "IBIT": ("Crypto", "Bitcoin")}),
    )
    assert fit.role_gap.has_gap is False
    assert fit.role_gap.headroom_pct == -10.0  # 15 - 25


# --- Sector overlap ------------------------------------------------------


def test_sector_overlap_full_when_same_sector_and_industry():
    fit = compute_portfolio_fit(
        "NVDA", "tactical",
        portfolio_aggregate={"by_role": {}, "total_cost_basis_usd": 0},
        holdings={"SMH": {}},
        sector_lookup_fn=_stub_lookup({"NVDA": ("Technology", "Semiconductors"),
                                       "SMH": ("Technology", "Semiconductors")}),
    )
    assert fit.sector_overlap.level == "full"
    assert "SMH" in fit.sector_overlap.overlapping_tickers


def test_sector_overlap_partial_when_same_sector_different_industry():
    fit = compute_portfolio_fit(
        "GOOGL", "tactical",
        portfolio_aggregate={"by_role": {}, "total_cost_basis_usd": 0},
        holdings={"NVDA": {}},
        sector_lookup_fn=_stub_lookup({"GOOGL": ("Technology", "Internet Content"),
                                       "NVDA": ("Technology", "Semiconductors")}),
    )
    # Different industries, same sector → partial
    # Note: real GOOGL is Communication Services, but for test purposes
    # we force same sector to exercise the partial branch.
    assert fit.sector_overlap.level == "partial"


def test_sector_overlap_none_when_no_match():
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate={"by_role": {}, "total_cost_basis_usd": 0},
        holdings={"SMH": {}, "IBIT": {}},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug Manufacturers"),
                                       "SMH": ("Technology", "Semiconductors"),
                                       "IBIT": ("Crypto", "Bitcoin")}),
    )
    assert fit.sector_overlap.level == "none"
    assert fit.sector_overlap.overlapping_tickers == ()


def test_sector_overlap_none_when_candidate_sector_unknown():
    """If yfinance doesn't return sector for the candidate, we can't claim
    overlap — degrade to 'none' rather than blocking."""
    fit = compute_portfolio_fit(
        "UNKNOWN_TICKER", "tactical",
        portfolio_aggregate={"by_role": {}, "total_cost_basis_usd": 0},
        holdings={"SMH": {}},
        sector_lookup_fn=_stub_lookup({"SMH": ("Technology", "Semiconductors")}),
    )
    assert fit.sector_overlap.level == "none"
    assert fit.sector_overlap.candidate_sector is None


# --- Sizing --------------------------------------------------------------


def test_recommended_size_uses_total_book():
    aggregate = {
        "by_role": {},
        "total_cost_basis_usd": 50000.0,
    }
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=aggregate,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug Manufacturers")}),
    )
    # Default 2% of $50,000 = $1,000
    assert fit.recommended_initial_weight_pct == 2.0
    assert fit.recommended_initial_size_usd == 1000.0


def test_recommended_size_is_none_without_total_book():
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=None,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug Manufacturers")}),
    )
    assert fit.recommended_initial_size_usd is None


def test_initial_weight_pct_override():
    aggregate = {"by_role": {}, "total_cost_basis_usd": 10000.0}
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=aggregate,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug")}),
        initial_weight_pct=3.0,
    )
    assert fit.recommended_initial_size_usd == 300.0


def test_total_deployable_usd_added_to_sizing_base():
    """When equity book is small (CEDEAR ratios) but FCI liquidity is large,
    sizing should scale against (book + deployable) — not just book."""
    aggregate = {"by_role": {}, "total_cost_basis_usd": 5000.0}
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=aggregate,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug")}),
        total_deployable_usd=29000.0,  # $29k of FCI + cash
    )
    # 2% of (5000 + 29000) = 2% of 34000 = $680
    assert fit.recommended_initial_size_usd == 680.0


def test_total_deployable_usd_alone_sufficient_for_sizing():
    """Candidate-only run with no equity book but with cash → size from cash."""
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=None,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug")}),
        total_deployable_usd=10000.0,
    )
    assert fit.recommended_initial_size_usd == 200.0  # 2% of 10000


def test_no_sizing_when_neither_book_nor_liquidity():
    fit = compute_portfolio_fit(
        "NVO", "tactical",
        portfolio_aggregate=None,
        holdings={},
        sector_lookup_fn=_stub_lookup({"NVO": ("Healthcare", "Drug")}),
        total_deployable_usd=None,
    )
    assert fit.recommended_initial_size_usd is None


# --- Hard gate: full overlap + at target ---------------------------------


def test_buy_blocked_when_full_overlap_and_at_target():
    fit = CandidateFit(
        role_gap=RoleGap(
            role="tactical",
            has_gap=False,
            current_weight_pct=44.0,  # within 2pt tolerance of 45
            target_weight_pct=45.0,
            headroom_pct=1.0,
        ),
        sector_overlap=SectorOverlap(
            level="full",
            candidate_sector="Technology",
            candidate_industry="Semiconductors",
            overlapping_tickers=("NVDA",),
        ),
        recommended_initial_weight_pct=2.0,
        recommended_initial_size_usd=1000.0,
    )
    assert is_buy_blocked_by_overlap_and_at_target(fit) is True


def test_buy_not_blocked_when_full_overlap_but_under_target():
    fit = CandidateFit(
        role_gap=RoleGap(
            role="tactical",
            has_gap=True,
            current_weight_pct=20.0,  # well below 45 target
            target_weight_pct=45.0,
            headroom_pct=25.0,
        ),
        sector_overlap=SectorOverlap(
            level="full",
            candidate_sector="Technology",
            candidate_industry="Semiconductors",
            overlapping_tickers=("NVDA",),
        ),
        recommended_initial_weight_pct=2.0,
        recommended_initial_size_usd=500.0,
    )
    assert is_buy_blocked_by_overlap_and_at_target(fit) is False


def test_buy_not_blocked_when_partial_overlap_at_target():
    fit = CandidateFit(
        role_gap=RoleGap(
            role="tactical",
            has_gap=False,
            current_weight_pct=44.0,
            target_weight_pct=45.0,
            headroom_pct=1.0,
        ),
        sector_overlap=SectorOverlap(
            level="partial",
            candidate_sector="Technology",
            candidate_industry="Software",
            overlapping_tickers=("NVDA",),
        ),
        recommended_initial_weight_pct=2.0,
        recommended_initial_size_usd=1000.0,
    )
    assert is_buy_blocked_by_overlap_and_at_target(fit) is False


# --- to_dict round-trip --------------------------------------------------


def test_to_dict_is_json_friendly():
    import json

    fit = CandidateFit(
        role_gap=RoleGap(role="tactical", has_gap=True, current_weight_pct=20,
                         target_weight_pct=45, headroom_pct=25),
        sector_overlap=SectorOverlap(level="none", candidate_sector="Healthcare",
                                     candidate_industry="Drug", overlapping_tickers=()),
        recommended_initial_weight_pct=2.0,
        recommended_initial_size_usd=1000.0,
    )
    json.dumps(fit.to_dict())
