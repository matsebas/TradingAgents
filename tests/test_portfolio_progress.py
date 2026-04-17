"""Tests for PortfolioProgress rendering (no Live loop, pure state -> table)."""

import os
import sys

import pytest
from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.graph.portfolio import PortfolioProgress, _extract_short_decision


def _table_to_text(progress: PortfolioProgress) -> str:
    console = Console(record=True, width=200)
    console.print(progress._render())
    return console.export_text()


def test_initial_state_is_all_pending():
    p = PortfolioProgress(["NVDA", "AMZN", "SPY"])
    text = _table_to_text(p)
    assert "NVDA" in text and "AMZN" in text and "SPY" in text
    assert text.count("pending") == 3


def test_start_marks_ticker_running():
    p = PortfolioProgress(["NVDA", "AMZN"])
    p.start("NVDA")
    text = _table_to_text(p)
    assert "running" in text
    # AMZN still pending
    assert text.count("pending") == 1


def test_on_node_updates_phase_and_skips_utility_nodes():
    p = PortfolioProgress(["NVDA"])
    p.start("NVDA")

    # Real agent node -> visible display label
    p.on_node("NVDA", "Market Analyst")
    assert "📊 Market" in p.states["NVDA"].phase

    # Utility nodes are ignored so the phase does not flicker to noise
    p.on_node("NVDA", "tools_market")
    assert "📊 Market" in p.states["NVDA"].phase

    p.on_node("NVDA", "Msg Clear Market")
    assert "📊 Market" in p.states["NVDA"].phase

    # Next real node advances the phase
    p.on_node("NVDA", "Bull Researcher")
    assert "🐂 Bull" in p.states["NVDA"].phase


def test_finish_success_shows_short_decision():
    p = PortfolioProgress(["NVDA"])
    p.start("NVDA")
    p.finish("NVDA", decision="FINAL TRADE DECISION: BUY strongly")
    assert p.states["NVDA"].status == "completed"
    assert p.states["NVDA"].final_label == "BUY"

    text = _table_to_text(p)
    assert "BUY" in text
    assert "done" in text


def test_finish_error_captures_truncated_message():
    p = PortfolioProgress(["XYZ"])
    p.start("XYZ")
    long_err = "RateLimitError: " + "x" * 200
    p.finish("XYZ", error=long_err)
    assert p.states["XYZ"].status == "error"
    assert len(p.states["XYZ"].final_label) <= 60

    text = _table_to_text(p)
    assert "error" in text


def test_extract_short_decision_edge_cases():
    assert _extract_short_decision(None) is None
    assert _extract_short_decision("") is None
    assert _extract_short_decision("Recommendation: buy now") == "BUY"
    assert _extract_short_decision("no canonical verb here") == "no canonical verb here"
