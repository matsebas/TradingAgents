"""Tests for portfolio-level aggregates injected into the Risk Judge."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.agents.utils.portfolio_aggregate import (
    PortfolioAggregate,
    RoleBucket,
    compute_portfolio_aggregate,
)


# --- compute_portfolio_aggregate -----------------------------------------


def test_returns_none_for_empty_holdings():
    assert compute_portfolio_aggregate(None) is None
    assert compute_portfolio_aggregate({}) is None


def test_returns_none_when_no_position_has_qty_and_avg_cost():
    # Holdings present but every position is missing one of qty / avg_cost.
    holdings = {
        "NVDA": {"avg_cost": 100.0, "role": "tactical"},
        "SPY": {"quantity": 10, "role": "anchor"},
    }
    assert compute_portfolio_aggregate(holdings) is None


def test_basic_aggregate_weights_and_buckets():
    # Three positions, two roles. Cost basis: SPY 1000, NVDA 500, IBIT 250.
    # Total = 1750. Weights: 57.14, 28.57, 14.29.
    holdings = {
        "SPY": {
            "quantity": 10,
            "avg_cost": 100.0,
            "role": "anchor",
            "unrealized_return_pct": 0.10,
        },
        "NVDA": {
            "quantity": 5,
            "avg_cost": 100.0,
            "role": "tactical",
            "unrealized_return_pct": 0.21,
        },
        "IBIT": {
            "quantity": 25,
            "avg_cost": 10.0,
            "role": "speculative",
            "unrealized_return_pct": 0.13,
        },
    }
    agg = compute_portfolio_aggregate(holdings)
    assert isinstance(agg, PortfolioAggregate)
    assert agg.total_positions == 3

    # By role
    anchor = agg.by_role["anchor"]
    assert anchor.count == 1
    assert abs(anchor.cost_basis_weight_pct - 57.14) < 0.05
    assert abs((anchor.avg_unrealized_return_pct or 0) - 0.10) < 1e-9
    assert anchor.tickers == ("SPY",)

    tactical = agg.by_role["tactical"]
    assert tactical.count == 1
    assert abs(tactical.cost_basis_weight_pct - 28.57) < 0.05

    spec = agg.by_role["speculative"]
    assert spec.count == 1
    assert abs(spec.cost_basis_weight_pct - 14.29) < 0.05

    # Top concentrations are sorted desc by weight, capped at 3.
    tickers = [t for t, _ in agg.top_concentrations]
    assert tickers == ["SPY", "NVDA", "IBIT"]


def test_avg_unrealized_pnl_per_bucket():
    # Two tactical positions with different P&L → bucket avg is mean of both.
    holdings = {
        "NVDA": {"quantity": 1, "avg_cost": 100, "role": "tactical", "unrealized_return_pct": 0.20},
        "AMZN": {"quantity": 1, "avg_cost": 100, "role": "tactical", "unrealized_return_pct": 0.10},
    }
    agg = compute_portfolio_aggregate(holdings)
    assert agg is not None
    assert abs((agg.by_role["tactical"].avg_unrealized_return_pct or 0) - 0.15) < 1e-9


def test_skips_positions_without_qty_or_avg_cost_but_keeps_total_count():
    holdings = {
        "NVDA": {"quantity": 5, "avg_cost": 100, "role": "tactical"},
        # No quantity → excluded from weight calculations but still in total_positions.
        "AMZN": {"avg_cost": 50, "role": "tactical"},
    }
    agg = compute_portfolio_aggregate(holdings)
    assert agg is not None
    assert agg.total_positions == 2  # holdings size, not weighted size
    assert agg.by_role["tactical"].count == 1
    assert agg.by_role["tactical"].tickers == ("NVDA",)


def test_pppc_alias_is_accepted():
    # Some upstreams use pppc instead of avg_cost.
    holdings = {
        "X": {"quantity": 10, "pppc": 50.0, "role": "tactical"},
    }
    agg = compute_portfolio_aggregate(holdings)
    assert agg is not None
    assert agg.by_role["tactical"].count == 1


def test_default_role_is_tactical_when_missing():
    holdings = {
        "X": {"quantity": 10, "avg_cost": 50.0},
    }
    agg = compute_portfolio_aggregate(holdings)
    assert agg is not None
    assert "tactical" in agg.by_role


def test_to_dict_round_trip_is_json_friendly():
    import json

    holdings = {
        "SPY": {"quantity": 10, "avg_cost": 100, "role": "anchor"},
    }
    agg = compute_portfolio_aggregate(holdings)
    assert agg is not None
    d = agg.to_dict()
    # Must be JSON-serialisable so _log_state can persist it.
    json.dumps(d)


def test_role_bucket_dataclass_is_immutable():
    bucket = RoleBucket(
        count=1, cost_basis_weight_pct=100.0, avg_unrealized_return_pct=0.0, tickers=("X",)
    )
    import dataclasses
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        bucket.count = 2  # type: ignore[misc]
