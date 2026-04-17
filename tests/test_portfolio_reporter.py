"""Tests for PortfolioReporter (pure formatting / persistence logic)."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.graph.portfolio import PortfolioReporter, PortfolioResult


def _result(ticker, decision=None, error=None, duration=1.0):
    return PortfolioResult(
        ticker=ticker,
        decision=decision,
        state={"dummy": True} if decision else None,
        error=error,
        duration_s=duration,
    )


def test_short_decision_extracts_canonical_tokens():
    assert _result("NVDA", "FINAL DECISION: BUY strongly").short_decision() == "BUY"
    assert _result("AAPL", "Recommend: SELL now").short_decision() == "SELL"
    assert _result("SPY", "I would HOLD").short_decision() == "HOLD"


def test_short_decision_handles_gemini_list_content():
    # Gemini sometimes returns content as a list of dicts.
    gemini_shape = [
        {"type": "text", "text": "BUY", "extras": {"signature": "abc"}}
    ]
    r = PortfolioResult(ticker="NVDA", decision=gemini_shape, state={"x": 1})
    assert r.decision == "BUY"  # normalised to plain string
    assert r.short_decision() == "BUY"
    assert r.ok is True


def test_short_decision_handles_empty_gemini_list():
    r = PortfolioResult(ticker="XYZ", decision=[])
    assert r.decision is None
    assert r.short_decision() == "-"


def test_short_decision_error_case():
    assert _result("XYZ", error="boom").short_decision() == "ERROR"


def test_ok_property():
    assert _result("NVDA", "BUY").ok is True
    assert _result("NVDA", error="x").ok is False
    assert _result("NVDA").ok is False


def test_save_json_roundtrip(tmp_path):
    reporter = PortfolioReporter()
    results = [
        _result("NVDA", "BUY signal"),
        _result("AMZN", "HOLD"),
        _result("XYZ", error="RateLimit"),
    ]

    out = reporter.save_json(results, "2026-04-16", out_dir=tmp_path)
    assert out.exists()

    data = json.loads(out.read_text())
    assert data["trade_date"] == "2026-04-16"
    assert len(data["results"]) == 3

    by_ticker = {r["ticker"]: r for r in data["results"]}
    assert by_ticker["NVDA"]["decision_short"] == "BUY"
    assert by_ticker["XYZ"]["decision_short"] == "ERROR"
    assert by_ticker["XYZ"]["error"] == "RateLimit"
    assert by_ticker["XYZ"]["log_path"] is None
    assert by_ticker["NVDA"]["log_path"].endswith(
        "full_states_log_2026-04-16.json"
    )


def test_render_table_does_not_raise(capsys):
    from rich.console import Console

    reporter = PortfolioReporter(console=Console(record=True, width=200))
    results = [
        _result("NVDA", "BUY"),
        _result("AMZN", "HOLD"),
        _result("XYZ", error="Boom"),
    ]
    # Should not raise; output goes to the recording console.
    reporter.render_table(results, "2026-04-16", pppc_by_ticker={"NVDA": "1.23"})


def test_save_markdown_has_table_and_summary(tmp_path):
    reporter = PortfolioReporter()
    results = [
        _result("NVDA", "FINAL: BUY strong"),
        _result("AMZN", "HOLD for now"),
        _result("XYZ", error="RateLimit"),
    ]

    out = reporter.save_markdown(results, "2026-04-16", out_dir=tmp_path)
    assert out.exists()
    content = out.read_text()

    assert "# Portfolio Analysis — 2026-04-16" in content
    assert "**Total:** 3" in content
    assert "**OK:** 2" in content
    assert "**Errors:** 1" in content
    assert "| NVDA | BUY" in content
    assert "| AMZN | HOLD" in content
    assert "| XYZ | ERROR" in content
    assert "RateLimit" in content
    # Detailed section only for OK results
    assert "### NVDA — BUY" in content
    assert "### XYZ" not in content


def test_save_csv_roundtrip(tmp_path):
    import csv as _csv

    reporter = PortfolioReporter()
    results = [
        _result("NVDA", "BUY now", duration=2.5),
        _result("XYZ", error="boom", duration=0.1),
    ]

    out = reporter.save_csv(results, "2026-04-16", out_dir=tmp_path)
    assert out.exists()

    with out.open(encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))

    assert len(rows) == 2
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    xyz = next(r for r in rows if r["ticker"] == "XYZ")

    assert nvda["decision_short"] == "BUY"
    assert nvda["decision_full"] == "BUY now"
    assert nvda["error"] == ""
    assert nvda["duration_s"] == "2.50"
    assert nvda["log_path"].endswith("full_states_log_2026-04-16.json")

    assert xyz["decision_short"] == "ERROR"
    assert xyz["error"] == "boom"
    assert xyz["log_path"] == ""
