"""Integration-level test for propagate_portfolio.

Mocks propagate_async so we don't hit any LLM / network — we only verify
the orchestration: ordering, fail-soft behaviour, and concurrency cap.
"""

import asyncio
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.graph.portfolio import PortfolioResult
from tradingagents.graph.trading_graph import TradingAgentsGraph


class _FakeGraph:
    """Stand-in for ``TradingAgentsGraph`` with just the bits we need."""

    def __init__(self, behaviour):
        self.behaviour = behaviour  # dict ticker -> ("ok"|"raise", delay_s)
        self._in_flight = 0
        self.max_observed = 0
        self._lock = asyncio.Lock()

    async def propagate_async(self, ticker, trade_date, on_node=None):
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
