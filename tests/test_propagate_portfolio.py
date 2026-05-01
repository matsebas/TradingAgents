"""Integration-level test for propagate_portfolio.

Mocks propagate_async so we don't hit any LLM / network — we only verify
the orchestration: ordering, fail-soft behaviour, and concurrency cap.
"""

import asyncio
import os
import sys
import textwrap
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.graph.portfolio import PortfolioResult
from tradingagents.graph.trading_graph import (
    TradingAgentsGraph,
    _augment_portfolio_context,
)


class _FakeGraph:
    """Stand-in for ``TradingAgentsGraph`` with just the bits we need."""

    def __init__(self, behaviour):
        self.behaviour = behaviour  # dict ticker -> ("ok"|"raise", delay_s)
        self._in_flight = 0
        self.max_observed = 0
        self._lock = asyncio.Lock()

    async def propagate_async(self, ticker, trade_date, on_node=None, portfolio_context=None):
        async with self._lock:
            self._in_flight += 1
            self.max_observed = max(self.max_observed, self._in_flight)
        try:
            kind, delay = self.behaviour[ticker]
            if on_node is not None:
                on_node("Market Analyst")
            await asyncio.sleep(delay)
            if kind == "raise":
                raise RuntimeError(f"simulated failure for {ticker}")
            state = {"company_of_interest": ticker, "final_trade_decision": f"BUY {ticker}"}
            return state, f"BUY {ticker}"
        finally:
            async with self._lock:
                self._in_flight -= 1

    # Reuse the real propagate_portfolio method
    propagate_portfolio = TradingAgentsGraph.propagate_portfolio


@pytest.mark.asyncio
async def test_propagate_portfolio_preserves_order_and_is_fail_soft():
    fake = _FakeGraph(
        behaviour={
            "NVDA": ("ok", 0.01),
            "AMZN": ("raise", 0.01),
            "SPY": ("ok", 0.01),
        }
    )

    results = await fake.propagate_portfolio(
        ["NVDA", "AMZN", "SPY"], "2026-04-16", max_concurrency=2
    )

    assert [r.ticker for r in results] == ["NVDA", "AMZN", "SPY"]
    assert isinstance(results[0], PortfolioResult)

    assert results[0].ok and results[0].decision == "BUY NVDA"
    assert not results[1].ok
    assert "simulated failure" in results[1].error
    assert results[2].ok and results[2].decision == "BUY SPY"


# --- _augment_portfolio_context ------------------------------------------


def _write_prior_report(reports_dir: Path, date: str, rows: list[tuple[str, str]]) -> None:
    body = textwrap.dedent(
        f"""\
        # Portfolio Analysis — {date}

        | Ticker | Decision | Duration | Log | Error |
        |--------|----------|---------:|-----|-------|
        """
    )
    for ticker, decision in rows:
        body += f"| {ticker} | {decision} | 100s | x |  |\n"
    body += "\n## Detailed decisions\n"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"portfolio_{date}.md").write_text(body, encoding="utf-8")


def test_augment_returns_none_when_nothing_to_inject(tmp_path: Path):
    out = _augment_portfolio_context(
        None, "NVDA", "2026-04-28", None, reports_dir=str(tmp_path / "missing")
    )
    assert out is None


def test_augment_injects_aggregate_and_previous_decision(tmp_path: Path):
    _write_prior_report(tmp_path, "2026-04-23", [("SPY", "HOLD")])
    base_ctx = {"avg_cost": 100.0, "role": "anchor"}
    agg_dict = {
        "total_positions": 1,
        "by_role": {"anchor": {"count": 1, "cost_basis_weight_pct": 100.0,
                               "avg_unrealized_return_pct": 0.0, "tickers": ["SPY"]}},
        "top_concentrations": [["SPY", 100.0]],
    }
    out = _augment_portfolio_context(
        base_ctx, "SPY", "2026-04-28", agg_dict, reports_dir=str(tmp_path)
    )
    assert out is not None
    # Original keys preserved
    assert out["avg_cost"] == 100.0
    assert out["role"] == "anchor"
    # New keys — aggregate is deep-copied per ticker, so equal but not the same object.
    assert out["portfolio_aggregate"] == agg_dict
    assert out["portfolio_aggregate"] is not agg_dict
    assert out["previous_decision"]["decision"] == "HOLD"
    assert out["previous_decision"]["date"] == "2026-04-23"


def test_augment_omits_previous_decision_when_no_prior_report(tmp_path: Path):
    out = _augment_portfolio_context(
        {"avg_cost": 1.0}, "NVDA", "2026-04-28", None, reports_dir=str(tmp_path)
    )
    assert out is not None
    assert "previous_decision" not in out


def test_augment_does_not_mutate_input_dict(tmp_path: Path):
    base_ctx = {"avg_cost": 100.0}
    out = _augment_portfolio_context(
        base_ctx, "X", "2026-04-28", None, reports_dir=str(tmp_path)
    )
    assert "portfolio_aggregate" not in base_ctx
    assert out is not base_ctx


# --- liquidity injection for candidates ----------------------------------


def test_augment_injects_liquidity_only_for_candidates(tmp_path: Path):
    liquidity = {"total_deployable_usd": 30000.0}

    holding_ctx = {"avg_cost": 100, "role": "tactical"}  # is_candidate not set
    candidate_ctx = {"role": "tactical", "is_candidate": True, "quantity": 0}

    out_holding = _augment_portfolio_context(
        holding_ctx, "NVDA", "2026-04-28", None,
        reports_dir=str(tmp_path), liquidity=liquidity,
    )
    out_candidate = _augment_portfolio_context(
        candidate_ctx, "NVO", "2026-04-28", None,
        reports_dir=str(tmp_path), liquidity=liquidity,
    )

    # Holdings get NO liquidity block (it's noise — they're not entering).
    assert "liquidity" not in out_holding
    # Candidates DO get the liquidity block — sizing depends on it.
    assert out_candidate["liquidity"]["total_deployable_usd"] == 30000.0
    # Deep-copied: not the same object reference.
    assert out_candidate["liquidity"] is not liquidity


# --- propagate_portfolio with candidates ---------------------------------


@pytest.mark.asyncio
async def test_propagate_portfolio_runs_holdings_and_candidates(tmp_path: Path):
    fake = _FakeGraph(
        behaviour={
            "NVDA": ("ok", 0.01),  # holding
            "AMZN": ("ok", 0.01),  # holding
            "NVO": ("ok", 0.01),   # candidate
        }
    )

    holdings = {"NVDA": {"avg_cost": 100, "quantity": 1, "role": "tactical"}}
    candidates = {"NVO": {"role": "tactical", "is_candidate": True, "quantity": 0, "avg_cost": 0}}

    results = await fake.propagate_portfolio(
        ["NVDA", "AMZN"], "2026-04-28",
        max_concurrency=3,
        holdings=holdings,
        candidates=candidates,
    )

    # Order: holdings first (input order), candidates after.
    assert [r.ticker for r in results] == ["NVDA", "AMZN", "NVO"]
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_propagate_portfolio_candidate_only_run(tmp_path: Path):
    fake = _FakeGraph(behaviour={"NVO": ("ok", 0.01)})
    results = await fake.propagate_portfolio(
        [],  # no holdings
        "2026-04-28",
        max_concurrency=2,
        candidates={"NVO": {"role": "tactical", "is_candidate": True, "quantity": 0, "avg_cost": 0}},
    )
    assert [r.ticker for r in results] == ["NVO"]


@pytest.mark.asyncio
async def test_propagate_portfolio_candidates_optional(tmp_path: Path):
    """Backward compat: existing callers don't pass candidates kwarg."""
    fake = _FakeGraph(behaviour={"NVDA": ("ok", 0.01)})
    results = await fake.propagate_portfolio(
        ["NVDA"], "2026-04-28", max_concurrency=2
    )
    assert [r.ticker for r in results] == ["NVDA"]


@pytest.mark.asyncio
async def test_propagate_portfolio_respects_concurrency_cap():
    fake = _FakeGraph(
        behaviour={t: ("ok", 0.05) for t in ["A", "B", "C", "D", "E", "F"]}
    )

    await fake.propagate_portfolio(
        ["A", "B", "C", "D", "E", "F"], "2026-04-16", max_concurrency=3
    )

    assert fake.max_observed <= 3
    assert fake.max_observed >= 2  # enough work in flight to prove parallelism
